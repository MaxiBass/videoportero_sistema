"""Videoportero: la visita al videoportero (avisos, apertura, quién atiende).

Escucha el timbre, la puerta, las caras, las matrículas y quién atiende,
decide con el motor y hace las llamadas (DECISIONES §13). Desde la v0.3.0 no
hay modo sombra: las automatizaciones que sustituía se borraron el 19/10/2026.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import CALLBACK_TYPE, Context, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
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
from .mensajes import matricula_guardada, matricula_no_guardada
from .motor import (
    AvisoMatricula,
    Banner,
    Decision,
    EmpiezaVisita,
    Evento,
    GuardarMatricula,
    Motor,
    RetirarAviso,
    TerminaVisita,
    Tick,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SENSOR, Platform.SWITCH]
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


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """1.2 (v0.3.0): sin modo sombra. Fuera las opciones «comparar» y
    «activa» y el sensor de diferencias."""
    if entry.version == 1 and entry.minor_version < 2:
        opciones = {k: v for k, v in entry.options.items() if k not in ("comparar", "activa")}
        registro = er.async_get(hass)
        if entidad := registro.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_diferencias"):
            registro.async_remove(entidad)
        hass.config_entries.async_update_entry(entry, options=opciones, minor_version=2)
    return entry.version == 1


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
        self.historial = Historial(hass)
        self.banner = ""
        self.ultima: dict[str, Any] | None = None
        self._quitar: list[CALLBACK_TYPE] = []
        self._tick: CALLBACK_TYPE | None = None
        # Interruptores «Avisos» (switch.py): dispositivos apagados y las
        # entidades, para añadir o quitar las de dispositivos nuevos o borrados.
        self.apagados: set[str] = set()
        self.interruptores: dict[str, Any] = {}
        self.anadir_interruptores: Any = None
        self.dispositivo_id: str | None = None
        # La última llamada pendiente de cada destino (cada móvil, cada script
        # o ayudante). Ver _encolar.
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
        # Un banner que quedó escrito antes de reiniciar se borra a los 3 min
        # de escribirse, como si no hubiera habido reinicio.
        banner = self.hass.states.get(self.casa.salidas.banner) if self.casa.salidas.banner else None
        if banner is not None and banner.state not in ("", "unknown", "unavailable"):
            self.banner = banner.state
            self.motor.banner_hasta = dt_util.as_local(banner.last_changed) + self.casa.ajustes.banner
            self._programar_tick()

    def _cambio(self, entidad: str) -> datetime | None:
        estado = self.hass.states.get(entidad) if entidad else None
        return dt_util.as_local(estado.last_changed) if estado else None

    async def cambiar_configuracion(self) -> None:
        self.casa = leer(self.hass, self.entry)
        self.motor.ajustes = self.casa.ajustes
        self.motor.cambiar_dispositivos(self.casa.dispositivos)
        self._desuscribir()
        await self._suscribir()
        self._cambiar_interruptores()
        revisar_requisitos(self.hass, self.entry)
        self._avisar_cambio()

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
            decisiones = self.motor.procesar(ev)
            if decisiones:
                self._aplicar(decisiones)
        self._programar_tick()
        self._avisar_cambio()

    def _aplicar(self, decisiones: list[Decision]) -> None:
        """Encola las llamadas de cada decisión y apunta lo que cambia."""
        for d in decisiones:
            if isinstance(d, GuardarMatricula):
                self.entry.async_create_background_task(
                    self.hass, self._guardar_matricula(d), f"videoportero: guardar {d.matricula}"
                )
                continue
            contexto = Context()
            for ll in llamadas(d, self.casa.salidas, self.apagados):
                self._encolar(ll, contexto)
        for d in decisiones:
            _LOGGER.debug("Decisión: %s", d)
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

    async def _guardar_matricula(self, d: GuardarMatricula) -> None:
        """Guarda en Matrículas (con avisar y abrir, como la automatización que
        lo hacía). Bien: se quita la pregunta a los demás y se confirma a quien
        contestó. Mal: se le avisa y la pregunta sigue donde estaba."""
        try:
            async with asyncio.timeout(ESPERA_LLAMADA):
                await self.hass.services.async_call(
                    "matriculas",
                    "guardar",
                    {"matricula": d.matricula, "nombre": d.nombre, "avisar": True, "abrir": True},
                    blocking=True,
                    context=Context(),
                )
        except Exception as err:  # noqa: BLE001  se avisa en vez de callar
            self.fallidas += 1
            _LOGGER.warning("No se pudo guardar la matrícula %s: %s", d.matricula, err)
            titulo, texto = matricula_no_guardada(d.matricula, d.nombre, str(err) or type(err).__name__)
            # Con otra etiqueta: la pregunta se queda para volver a intentarlo.
            destino = (d.quien,) if d.quien else d.otros
            decisiones: list[Decision] = [AvisoMatricula(f"{d.tag}-error", destino, titulo, texto, "mdi:alert-circle", breve=False)]
        else:
            self.hechas += 1
            titulo, texto = matricula_guardada(d.matricula, d.nombre)
            decisiones = [RetirarAviso(d.tag, d.otros)] if d.otros else []
            if d.quien:
                decisiones.append(AvisoMatricula(d.tag, (d.quien,), titulo, texto, "mdi:check-circle"))
        self._aplicar(decisiones)
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

    # ── Para los sensores ──

    @property
    def estado_visita(self) -> str:
        if self.motor.visita is not None:
            return "en_curso"
        return {"Llamada ya atendida": "atendida", "Puerta abierta automáticamente": "abierta_automaticamente"}.get(
            self.banner, "sin_visita"
        )
