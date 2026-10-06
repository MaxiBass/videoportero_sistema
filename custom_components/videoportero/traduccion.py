"""Traduce lo que pasa en Home Assistant a eventos del motor. Sin imports de HA.

Cada función recibe lo mismo que verían los disparadores de la automatización
que se sustituye (un cambio de estado, un mensaje MQTT, un evento) y devuelve
los eventos del motor, o nada. La parte que se suscribe en HA solo tiene que
llamar aquí, y la misma traducción sirve para reproducir el historial.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .motor import (
    POR_APP,
    POR_AUDIO,
    POR_PANEL,
    Abrir,
    AperturaAutomatica,
    Atendido,
    Cara,
    Evento,
    Matricula,
    Puerta,
    Timbre,
)

APP_HA = "io.homeassistant.companion.android"
ACCION_ABRIR = "ABRIR_PUERTA"


@dataclass(frozen=True)
class Entradas:
    timbre: str  # binary_sensor del pulsador
    puerta: str  # binary_sensor de la puerta
    camara_caras: str = ""  # cámara de Frigate cuyas caras cuentan
    personas: str = ""  # sensor de Frigate con las personas que cuenta en esa cámara
    apertura_automatica: str = ""  # input_boolean (hasta la fase 3)
    audio: str = ""  # input_boolean del audio (hasta la fase 3)
    marca_audio: str = ""  # input_text con quién contestó (hasta la fase 3)
    marcas: Mapping[str, str] = field(default_factory=dict)  # valor de la marca → dispositivo
    app: Mapping[str, str] = field(default_factory=dict)  # sensor last_used_app → dispositivo
    panel: Mapping[str, str] = field(default_factory=dict)  # sensor de BrowserMod → dispositivo
    # Visibilidad de BrowserMod de los móviles → dispositivo (página de HA en pantalla)
    visible: Mapping[str, str] = field(default_factory=dict)
    aparatos: Mapping[str, str] = field(default_factory=dict)  # device_id de la app de HA → dispositivo
    usuarios: Mapping[str, str] = field(default_factory=dict)  # usuario de HA → dispositivo
    vista_llamada: str = "videoportero"  # parte de la ruta de la vista de llamada


def en_llamada(ruta: str | None, e: Entradas) -> bool:
    """La vista de llamada, no la de solo ver (la que abren las tablets solas)."""
    ruta = ruta or ""
    return e.vista_llamada in ruta and "-ver" not in ruta


def estado(
    e: Entradas,
    hora: datetime,
    entidad: str,
    viejo: str | None,
    nuevo: str | None,
    leer: Callable[[str], str | None],
) -> list[Evento]:
    """Un cambio de estado. `leer` da el estado actual de otra entidad."""
    if viejo == nuevo:
        return []  # solo cambian atributos: ningún disparador lo ve
    if entidad == e.timbre:
        return [Timbre(hora)] if (viejo, nuevo) == ("off", "on") else []
    if entidad == e.puerta:
        return [Puerta(hora, {"on": True, "off": False}.get(nuevo or ""))]
    if entidad == e.apertura_automatica:
        return [AperturaAutomatica(hora, nuevo == "on")]
    if entidad == e.audio:
        if nuevo != "on":
            return []
        marca = (leer(e.marca_audio) or "").strip() if e.marca_audio else ""
        return [Atendido(hora, e.marcas.get(marca), POR_AUDIO)]
    if entidad in e.app:
        return [Atendido(hora, e.app[entidad], POR_APP)] if nuevo == APP_HA else []
    if entidad in e.panel:
        # Como el disparador de plantilla: solo al pasar a la vista de llamada.
        if en_llamada(nuevo, e) and not en_llamada(viejo, e):
            return [Atendido(hora, e.panel[entidad], POR_PANEL)]
        return []
    if entidad in e.visible:
        # La página de HA pasa a verse en el móvil. Cubre que HA ya fuera la
        # última app (last_used_app no cambia); con la pantalla de bloqueo
        # delante sigue en hidden (DECISIONES §4).
        return [Atendido(hora, e.visible[entidad], POR_APP)] if nuevo == "visible" else []
    return []


def _entero(valor: str | None) -> int:
    """Como el filtro `int(0)` de las plantillas de HA."""
    try:
        return int(float(valor or 0))
    except (TypeError, ValueError):
        return 0


def cara(
    e: Entradas,
    hora: datetime,
    mensaje: Mapping[str, Any],
    leer: Callable[[str], str | None] | None = None,
) -> list[Evento]:
    """Un mensaje de `frigate/tracked_object_update`.

    Sin sensor de personas configurado, toda cara cuenta como confirmada.
    """
    if mensaje.get("type") != "face" or mensaje.get("camera") != e.camara_caras:
        return []
    try:
        score = float(mensaje.get("score") or 0)
    except (TypeError, ValueError):
        score = 0.0
    confirmada = not e.personas or (leer is not None and _entero(leer(e.personas)) >= 1)
    return [Cara(hora, str(mensaje.get("name") or ""), score, str(mensaje.get("id") or ""), confirmada)]


def matricula(e: Entradas, hora: datetime, datos: Mapping[str, Any]) -> list[Evento]:
    """Un evento `matriculas_detectada`. El filtro de inicio lo hace el motor."""
    return [Matricula(hora, dict(datos))]


def accion_aviso(e: Entradas, hora: datetime, datos: Mapping[str, Any], usuario: str | None) -> list[Evento]:
    """Un evento `mobile_app_notification_action`. Solo interesa el botón ABRIR.

    Quién lo pulsó sale del aparato que lo manda o, si no viene, del usuario.
    """
    if datos.get("action") != ACCION_ABRIR:
        return []
    quien = e.aparatos.get(str(datos.get("device_id") or "")) or (e.usuarios.get(usuario) if usuario else None)
    return [Abrir(hora, quien, ejecutar=True, tag=str(datos.get("tag") or ""))]
