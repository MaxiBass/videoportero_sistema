"""Videoportero: la visita al videoportero (avisos, apertura, quién atiende).

Fase 1, modo sombra: escucha lo mismo que la automatización que sustituye,
decide con el motor y apunta lo que habría hecho, pero no ejecuta nada. Lo
compara con lo que hacen de verdad las automatizaciones elegidas en las
opciones. Ver docs/DECISIONES.md.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.automation import EVENT_AUTOMATION_TRIGGERED
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_CALL_SERVICE, Platform
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from . import traduccion as tr
from .configuracion import Casa, leer
from .const import EVENTO_ACCION_AVISO, EVENTO_MATRICULA, SENAL_CAMBIO, TOPIC_CARAS
from .historial import Historial, visita_a_dict
from .llamadas import llamadas
from .motor import Banner, Decision, Evento, Motor, TerminaVisita, Tick, Visita
from .sombra import Comparador, alcance, como_la_automatizacion

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR]
DOMINIOS_COMPARADOS = ("notify", "script", "switch", "input_text")

type EntradaVideoportero = ConfigEntry[Sistema]


async def async_setup_entry(hass: HomeAssistant, entry: EntradaVideoportero) -> bool:
    sistema = Sistema(hass, entry)
    await sistema.iniciar()
    entry.runtime_data = sistema
    # Añadir, cambiar o quitar un dispositivo (subentrada) o las opciones no
    # recarga la entrada: así no se pierde una visita en curso.
    entry.async_on_unload(entry.add_update_listener(_al_cambiar_configuracion))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _al_cambiar_configuracion(hass: HomeAssistant, entry: EntradaVideoportero) -> None:
    await entry.runtime_data.cambiar_configuracion()


async def async_unload_entry(hass: HomeAssistant, entry: EntradaVideoportero) -> bool:
    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        entry.runtime_data.parar()
    return ok


class Sistema:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.casa: Casa = leer(hass, entry)
        self.motor = Motor(self.casa.dispositivos, self.casa.ajustes)
        self.comparador = Comparador()
        self.historial = Historial(hass)
        self.banner = ""
        self.ultima: dict[str, Any] | None = None
        self._quitar: list[CALLBACK_TYPE] = []
        self._tick: CALLBACK_TYPE | None = None
        # Ejecuciones de las automatizaciones comparadas: contexto → (hora,
        # scripts que ha lanzado). Ver sombra.Alcance.
        self._contextos: dict[str, tuple[float, set[str]]] = {}
        self._alcance = alcance(self.casa.salidas)
        self._emparejadas = 0

    # ── Arranque y configuración ──

    async def iniciar(self) -> None:
        await self.historial.cargar()
        if self.historial.visitas:
            self.ultima = self.historial.visitas[-1]
        self._estado_inicial()
        await self._suscribir()

    def _leer(self, entidad: str) -> str | None:
        estado = self.hass.states.get(entidad) if entidad else None
        return estado.state if estado else None

    def _estado_inicial(self) -> None:
        e = self.casa.entradas
        self.motor.puerta_abierta = {"on": True, "off": False}.get(self._leer(e.puerta) or "")
        self.motor.apertura_automatica = self._leer(e.apertura_automatica) == "on"

    async def cambiar_configuracion(self) -> None:
        self.casa = leer(self.hass, self.entry)
        self._alcance = alcance(self.casa.salidas)
        self.motor.ajustes = self.casa.ajustes
        self.motor.cambiar_dispositivos(self.casa.dispositivos)
        self._desuscribir()
        await self._suscribir()
        self._avisar_cambio()

    async def _suscribir(self) -> None:
        e = self.casa.entradas
        entidades = [x for x in (e.timbre, e.puerta, e.apertura_automatica, e.audio, *e.app, *e.panel, *e.visible) if x]
        if entidades:
            self._quitar.append(async_track_state_change_event(self.hass, entidades, self._al_estado))
        self._quitar.append(self.hass.bus.async_listen(EVENTO_MATRICULA, self._al_matricula))
        self._quitar.append(self.hass.bus.async_listen(EVENTO_ACCION_AVISO, self._al_accion))
        if self.casa.comparar:
            self._quitar.append(self.hass.bus.async_listen(EVENT_AUTOMATION_TRIGGERED, self._al_automatizacion))
            self._quitar.append(self.hass.bus.async_listen(EVENT_CALL_SERVICE, self._al_llamada))
        self._quitar.append(async_track_time_interval(self.hass, self._al_revisar, timedelta(seconds=10)))
        if e.camara_caras:
            await self._suscribir_caras()

    async def _suscribir_caras(self) -> None:
        from homeassistant.components import mqtt  # noqa: PLC0415  solo si hay caras

        # Espera a que MQTT termine de arrancar (no a que conecte); False si no
        # está configurado o no arranca a tiempo.
        if not await mqtt.async_wait_for_mqtt_client(self.hass):
            _LOGGER.warning("MQTT no está disponible: no llegarán las caras de Frigate")
            return
        self._quitar.append(await mqtt.async_subscribe(self.hass, TOPIC_CARAS, self._al_mqtt))

    def _desuscribir(self) -> None:
        while self._quitar:
            self._quitar.pop()()

    def parar(self) -> None:
        self._desuscribir()
        if self._tick:
            self._tick()
            self._tick = None

    # ── Entradas ──

    @staticmethod
    def _hora(evento: Event) -> datetime:
        return dt_util.as_local(evento.time_fired)

    @callback
    def _al_estado(self, evento: Event[EventStateChangedData]) -> None:
        viejo, nuevo = evento.data["old_state"], evento.data["new_state"]
        self._procesar(
            tr.estado(
                self.casa.entradas,
                self._hora(evento),
                evento.data["entity_id"],
                viejo.state if viejo else None,
                nuevo.state if nuevo else None,
                self._leer,
            )
        )

    @callback
    def _al_matricula(self, evento: Event) -> None:
        self._procesar(tr.matricula(self.casa.entradas, self._hora(evento), evento.data))

    @callback
    def _al_accion(self, evento: Event) -> None:
        self._procesar(tr.accion_aviso(self.casa.entradas, self._hora(evento), evento.data, evento.context.user_id))

    @callback
    def _al_mqtt(self, mensaje: Any) -> None:
        try:
            datos = json.loads(mensaje.payload)
        except (TypeError, ValueError):
            return
        if isinstance(datos, dict):
            self._procesar(tr.cara(self.casa.entradas, dt_util.now(), datos, self._leer))

    @callback
    def _al_tick(self, ahora: datetime) -> None:
        self._tick = None
        self._procesar([Tick(dt_util.as_local(ahora))])

    # ── El motor ──

    @callback
    def _procesar(self, eventos: list[Evento]) -> None:
        if not eventos:
            return
        for ev in eventos:
            visita = self.motor.visita
            decisiones = self.motor.procesar(ev)
            if decisiones:
                self._aplicar(decisiones, ev.hora, visita or self.motor.visita)
        self._programar_tick()
        self._avisar_cambio()

    def _aplicar(self, decisiones: list[Decision], hora: datetime, visita: Visita | None) -> None:
        """Modo sombra: no se ejecuta nada; se apunta para comparar."""
        tag = next((d.tag for d in decisiones if getattr(d, "tag", "").startswith("visita-")), None)
        if tag is None:
            fin = next((d.visita for d in decisiones if isinstance(d, TerminaVisita)), visita)
            tag = fin.tag if fin else None
        if self.casa.comparar:
            for d in como_la_automatizacion(decisiones, self.motor.dispositivos):
                for ll in llamadas(d, self.casa.salidas):
                    self.comparador.esperada(hora.timestamp(), ll, tag)
        for d in decisiones:
            _LOGGER.debug("Decisión (sombra): %s", d)
            if isinstance(d, TerminaVisita):
                self.ultima = visita_a_dict(d.visita, self.motor.dispositivos, d.visita.imagen)
                self.historial.visita(self.ultima)
            elif isinstance(d, Banner):
                self.banner = d.texto

    def _programar_tick(self) -> None:
        if self._tick:
            self._tick()
            self._tick = None
        cuando = self.motor.proximo_tick()
        if cuando is not None:
            self._tick = async_track_point_in_time(self.hass, self._al_tick, cuando)

    def _avisar_cambio(self) -> None:
        async_dispatcher_send(self.hass, SENAL_CAMBIO)

    # ── Comparación con la automatización ──

    @callback
    def _al_automatizacion(self, evento: Event) -> None:
        if evento.data.get("entity_id") in self.casa.comparar:
            self._contextos[evento.context.id] = (time.time(), set())

    @callback
    def _al_llamada(self, evento: Event) -> None:
        contexto = self._contextos.get(evento.context.id)
        if contexto is None:
            return
        dominio = evento.data.get("domain")
        if dominio not in DOMINIOS_COMPARADOS:
            return
        servicio = evento.data.get("service", "")
        datos = dict(evento.data.get("service_data") or {})
        scripts = contexto[1]
        self.comparador.real(
            evento.time_fired.timestamp(),
            dominio,
            servicio,
            datos,
            lambda clave: self._alcance.admite(clave, scripts),
        )
        if dominio == "script" and servicio == "turn_on":
            ents = datos.get("entity_id") or []
            scripts.update([ents] if isinstance(ents, str) else ents)

    @callback
    def _al_revisar(self, _ahora: datetime | None = None) -> None:
        ahora = time.time()
        # Las ejecuciones de hace más de una hora ya no hacen llamadas.
        self._contextos = {c: v for c, v in self._contextos.items() if ahora - v[0] < 3600}
        nuevas = self.comparador.emparejadas - self._emparejadas
        self._emparejadas = self.comparador.emparejadas
        diferencias = self.comparador.revisar(ahora)
        if not nuevas and not diferencias:
            return
        self.historial.comparadas += nuevas
        for d in diferencias:
            _LOGGER.info("Diferencia con la automatización (%s): %s", d.lado, d.resumen())
            self.historial.diferencia(d)
        if nuevas and not diferencias:
            self.historial.guardar()
        self._avisar_cambio()

    # ── Para los sensores ──

    @property
    def estado_visita(self) -> str:
        if self.motor.visita is not None:
            return "en_curso"
        return {"Llamada ya atendida": "atendida", "Puerta abierta automáticamente": "abierta_automaticamente"}.get(
            self.banner, "sin_visita"
        )
