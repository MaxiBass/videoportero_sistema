"""Videoportero: la visita al videoportero (avisos, apertura, quién atiende).

Escucha lo mismo que la automatización que sustituye y decide con el motor.

- Modo sombra (fase 1): no ejecuta nada; apunta lo que habría hecho y lo
  compara con lo que hacen de verdad las automatizaciones elegidas en las
  opciones (DECISIONES §9).
- Activa (fase 2, opción «La integración manda»): hace ella las llamadas y
  apaga esas automatizaciones, sin borrarlas; volver a sombra las enciende
  (DECISIONES §13).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.automation import EVENT_AUTOMATION_TRIGGERED
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_CALL_SERVICE, Platform
from homeassistant.core import CALLBACK_TYPE, Context, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_track_point_in_time,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from . import traduccion as tr
from .configuracion import Casa, leer
from .requisitos import revisar_requisitos
from .const import DOMAIN, EVENTO_ACCION_AVISO, EVENTO_MATRICULA, SENAL_CAMBIO, TOPIC_CARAS
from .historial import Historial, visita_a_dict
from .llamadas import Llamada, llamadas
from .motor import Banner, Decision, EmpiezaVisita, Evento, Motor, TerminaVisita, Tick, Visita
from .sombra import Comparador, alcance, como_la_automatizacion

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.SWITCH]
DOMINIOS_COMPARADOS = ("notify", "script", "switch", "input_text")
ESPERA_LLAMADA = 30  # s; una llamada que no responde no frena las siguientes

type EntradaVideoportero = ConfigEntry[Sistema]


async def async_setup_entry(hass: HomeAssistant, entry: EntradaVideoportero) -> bool:
    sistema = Sistema(hass, entry)
    # El dispositivo principal, antes que las plataformas: los de cada móvil y
    # del hogar cuelgan de él por su id (switch.py).
    sistema.dispositivo_id = (
        dr.async_get(hass)
        .async_get_or_create(config_entry_id=entry.entry_id, **dispositivo_principal(entry))
        .id
    )
    await sistema.iniciar()
    entry.runtime_data = sistema
    # Añadir, cambiar o quitar un dispositivo (subentrada) o las opciones no
    # recarga la entrada: así no se pierde una visita en curso.
    entry.async_on_unload(entry.add_update_listener(_al_cambiar_configuracion))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


def dispositivo_principal(entry: ConfigEntry) -> dr.DeviceInfo:
    return dr.DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Videoportero",
        manufacturer="Videoportero",
        model="Visitas al videoportero",
        entry_type=dr.DeviceEntryType.SERVICE,
    )


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
        # Interruptores «Avisos» (switch.py): dispositivos apagados y las
        # entidades, para añadir o quitar las de dispositivos nuevos o borrados.
        self.apagados: set[str] = set()
        self.interruptores: dict[str, Any] = {}
        self.anadir_interruptores: Any = None
        self.dispositivo_id: str | None = None
        # Activa: la última llamada pendiente de cada destino (cada móvil,
        # cada script o ayudante). Ver _encolar.
        self._pendientes: dict[str, asyncio.Task] = {}
        self.hechas = 0
        self.fallidas = 0

    # ── Arranque y configuración ──

    async def iniciar(self) -> None:
        await self.historial.cargar()
        if self.historial.visitas:
            self.ultima = self.historial.visitas[-1]
        self._estado_inicial()
        await self._suscribir()
        if self.casa.activa:
            # Al arrancar, solo se apagan: en sombra no se toca lo que haya.
            await self._mandar(True)
        revisar_requisitos(self.hass, self.entry)

    def _leer(self, entidad: str) -> str | None:
        estado = self.hass.states.get(entidad) if entidad else None
        return estado.state if estado else None

    def _estado_inicial(self) -> None:
        e = self.casa.entradas
        self.motor.puerta_abierta = {"on": True, "off": False}.get(self._leer(e.puerta) or "")
        self.motor.apertura_automatica = self._leer(e.apertura_automatica) == "on"
        self.motor.hablando = self._leer(e.audio) == "on"
        # Desde cuándo están así, para la pausa de las caras (DECISIONES §12)
        self.motor.puerta_cambio = self._cambio(e.puerta)
        self.motor.audio_cambio = self._cambio(e.audio)
        # Activa: un banner que quedó escrito antes de reiniciar se borra a
        # los 3 min de escribirse, como si no hubiera habido reinicio.
        banner = self.hass.states.get(self.casa.salidas.banner) if self.casa.salidas.banner else None
        if self.casa.activa and banner is not None and banner.state not in ("", "unknown", "unavailable"):
            self.banner = banner.state
            self.motor.banner_hasta = dt_util.as_local(banner.last_changed) + self.casa.ajustes.banner
            self._programar_tick()

    def _cambio(self, entidad: str) -> datetime | None:
        estado = self.hass.states.get(entidad) if entidad else None
        return dt_util.as_local(estado.last_changed) if estado else None

    async def cambiar_configuracion(self) -> None:
        antes = self.casa.activa
        self.casa = leer(self.hass, self.entry)
        self._alcance = alcance(self.casa.salidas)
        self.motor.ajustes = self.casa.ajustes
        self.motor.cambiar_dispositivos(self.casa.dispositivos)
        self._desuscribir()
        await self._suscribir()
        if self.casa.activa != antes:
            await self._mandar(self.casa.activa)
        self._cambiar_interruptores()
        revisar_requisitos(self.hass, self.entry)
        self._avisar_cambio()

    async def _mandar(self, activa: bool) -> None:
        """Pasa a mandar (apaga las automatizaciones que sustituye) o a
        sombra (las vuelve a encender). No las borra nunca."""
        self.comparador.esperadas.clear()
        self.comparador.reales.clear()
        automatizaciones = [a for a in self.casa.comparar if self.hass.states.get(a) is not None]
        if not automatizaciones:
            return
        servicio, datos = ("turn_off", {"stop_actions": True}) if activa else ("turn_on", {})
        try:
            await self.hass.services.async_call(
                "automation", servicio, {"entity_id": automatizaciones, **datos}, blocking=True
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("No se pudieron %s las automatizaciones %s", "apagar" if activa else "encender", automatizaciones)
        else:
            _LOGGER.info("%s: %s", "La integración manda; apagadas" if activa else "Modo sombra; encendidas", automatizaciones)

    def _cambiar_interruptores(self) -> None:
        """Interruptor para cada dispositivo nuevo; fuera los de los borrados."""
        if self.anadir_interruptores is not None:
            self.anadir_interruptores(self.entry.subentries.values())
        for ident in [i for i in self.interruptores if i not in self.entry.subentries]:
            interruptor = self.interruptores.pop(ident)
            self.apagados.discard(ident)
            self.hass.async_create_task(interruptor.async_remove(force_remove=True))

    @callback
    def _al_revisar_requisitos(self, _ahora_o_evento: Any) -> None:
        revisar_requisitos(self.hass, self.entry)

    @callback
    def poner_avisos(self, ident: str, encendido: bool) -> None:
        if encendido:
            self.apagados.discard(ident)
        else:
            self.apagados.add(ident)

    async def _suscribir(self) -> None:
        e = self.casa.entradas
        entidades = [x for x in (e.timbre, e.puerta, e.apertura_automatica, e.audio, *e.app, *e.panel, *e.visible) if x]
        if entidades:
            self._quitar.append(async_track_state_change_event(self.hass, entidades, self._al_estado))
        self._quitar.append(self.hass.bus.async_listen(EVENTO_MATRICULA, self._al_matricula))
        self._quitar.append(self.hass.bus.async_listen(EVENTO_ACCION_AVISO, self._al_accion))
        if self.casa.comparar and not self.casa.activa:
            self._quitar.append(self.hass.bus.async_listen(EVENT_AUTOMATION_TRIGGERED, self._al_automatizacion))
            self._quitar.append(self.hass.bus.async_listen(EVENT_CALL_SERVICE, self._al_llamada))
        if self.casa.comparar and self.casa.activa:
            # Si alguien vuelve a encender una, avisarían las dos: Reparaciones.
            self._quitar.append(async_track_state_change_event(self.hass, list(self.casa.comparar), self._al_revisar_requisitos))
        self._quitar.append(async_track_time_interval(self.hass, self._al_revisar, timedelta(seconds=10)))
        self._quitar.append(async_track_time_interval(self.hass, self._al_revisar_requisitos, timedelta(minutes=30)))
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
        for tarea in self._pendientes.values():
            tarea.cancel()
        self._pendientes.clear()

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
        """Activa: se encolan las llamadas. Sombra: se apuntan para comparar."""
        if self.casa.activa:
            for d in decisiones:
                contexto = Context()
                for ll in llamadas(d, self.casa.salidas, self.apagados):
                    self._encolar(ll, contexto)
        elif self.casa.comparar:
            tag = next((d.tag for d in decisiones if getattr(d, "tag", "").startswith("visita-")), None)
            if tag is None:
                fin = next((d.visita for d in decisiones if isinstance(d, TerminaVisita)), visita)
                tag = fin.tag if fin else None
            for d in como_la_automatizacion(decisiones, self.motor.dispositivos):
                for ll in llamadas(d, self.casa.salidas, self.apagados):
                    self.comparador.esperada(hora.timestamp(), ll, tag)
        for d in decisiones:
            _LOGGER.debug("Decisión (%s): %s", "activa" if self.casa.activa else "sombra", d)
            if isinstance(d, TerminaVisita):
                self.ultima = visita_a_dict(d.visita, self.motor.dispositivos, d.visita.imagen)
                self.historial.visita(self.ultima)
            elif isinstance(d, Banner):
                self.banner = d.texto
            elif isinstance(d, EmpiezaVisita):
                # Empezar la visita borra el banner (lo vacía `llamadas`): si
                # esta termina sin respuesta, el sensor no vuelve al anterior.
                self.banner = ""

    def _encolar(self, ll: Llamada, contexto: Context) -> None:
        """En orden por destino y en paralelo entre destinos.

        Los avisos a un mismo móvil van en orden (el primero suena y los
        siguientes lo sustituyen), igual que las escrituras de un mismo
        ayudante. Pero un aviso que tarda (el 15/10 uno tardó 10 s en dar
        error) no frena el botón ABRIR ni los avisos a los demás móviles.
        """
        clave = f"notify.{ll.servicio}" if ll.dominio == "notify" else f"{ll.dominio}:{ll.datos.get('entity_id')}"
        previa = self._pendientes.get(clave)
        tarea = self.entry.async_create_background_task(
            self.hass, self._llamar(ll, contexto, previa), f"videoportero: {clave}"
        )
        self._pendientes[clave] = tarea

        def _hecha(t: asyncio.Task) -> None:
            if self._pendientes.get(clave) is t:
                del self._pendientes[clave]

        tarea.add_done_callback(_hecha)

    async def _llamar(self, ll: Llamada, contexto: Context, previa: asyncio.Task | None = None) -> None:
        if previa is not None:
            await asyncio.wait([previa])
        try:
            async with asyncio.timeout(ESPERA_LLAMADA):
                await self.hass.services.async_call(ll.dominio, ll.servicio, dict(ll.datos), blocking=True, context=contexto)
        except Exception as err:  # noqa: BLE001  una llamada que falla no frena las demás
            self.fallidas += 1
            _LOGGER.warning("Falló %s.%s %s: %s", ll.dominio, ll.servicio, ll.datos.get("entity_id", ""), err)
        else:
            self.hechas += 1
        self._avisar_cambio()

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
