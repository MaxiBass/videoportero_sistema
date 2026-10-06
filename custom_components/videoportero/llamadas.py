"""Traduce las decisiones del motor a llamadas a servicios de Home Assistant.

No importa nada de HA: devuelve la lista de llamadas y otro módulo las hace
(o, en modo sombra, solo las anota). Las llamadas son las mismas que hace hoy
la automatización que se sustituye, campo a campo, para que en el cambio de
la fase 2 paneles, tablets y móviles no noten nada (DECISIONES §6).
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from typing import Any

from .motor import (
    AbrirPuerta,
    Avisar,
    Banner,
    Decision,
    EmpiezaVisita,
    GuardarFoto,
    PedirNombre,
    RetirarAviso,
    TerminaVisita,
)

TITULO = "Videoportero"
ACCION_ABRIR = "ABRIR_PUERTA"
ACCION_NOMBRE = "input_nombre_matricula"
ACCION_IGNORAR = "ignorar_matricula"


@dataclass(frozen=True)
class SalidaMovil:
    notify: str  # nombre del servicio, sin «notify.»
    vista: str  # la que abre al tocar el aviso
    boton_abrir: bool = True


@dataclass(frozen=True)
class SalidaHogar:
    # Scripts propios al empezar la visita; se lanzan con la variable
    # `origen: vto`, como hoy. Si no hay, se usarán las acciones integradas
    # (fase 3).
    scripts_inicio: tuple[str, ...] = ()


@dataclass(frozen=True)
class Salidas:
    moviles: Mapping[str, SalidaMovil] = field(default_factory=dict)
    hogar: Mapping[str, SalidaHogar] = field(default_factory=dict)
    al_empezar: tuple[str, ...] = ()  # scripts al empezar la visita (zoom, silenciar el altavoz)
    al_timbre: tuple[str, ...] = ()  # scripts con cada timbre (foto HD)
    abrir_boton: str = ""  # lo que abre con el botón ABRIR
    abrir_automatica: str = ""  # lo que abre en la apertura automática
    banner: str = ""  # input_text del banner
    # input_text donde los scripts de contestar apuntan quién contestó. Se
    # vacía al empezar cada visita. Desaparece en la fase 3.
    marca_audio: str = ""


@dataclass(frozen=True)
class Llamada:
    dominio: str
    servicio: str
    datos: dict[str, Any]


def _encender(entidad: str, **datos: Any) -> Llamada:
    return Llamada(entidad.split(".", 1)[0], "turn_on", {"entity_id": entidad, **datos})


def _texto(entidad: str, valor: str) -> Llamada:
    return Llamada("input_text", "set_value", {"entity_id": entidad, "value": valor})


def llamadas(decision: Decision, s: Salidas, apagados: Collection[str] = ()) -> list[Llamada]:
    """`apagados`: dispositivos con su interruptor de avisos apagado. Un móvil
    apagado no recibe nada; un dispositivo del hogar apagado no lanza sus
    scripts. Lo que decide el motor (quién atendió, el aviso de cierre) no
    cambia (DECISIONES §11)."""
    if isinstance(decision, EmpiezaVisita):
        res = []
        if s.banner:
            res.append(_texto(s.banner, ""))
        if s.marca_audio:
            res.append(_texto(s.marca_audio, ""))
        res += [_encender(script) for script in s.al_empezar]
        for ident, hogar in s.hogar.items():
            if ident in apagados:
                continue
            res += [_encender(script, variables={"origen": "vto"}) for script in hogar.scripts_inicio]
        return res

    if isinstance(decision, Avisar):
        res = []
        for ident in decision.destinatarios:
            movil = s.moviles.get(ident)
            if movil is None or ident in apagados:
                continue
            datos: dict[str, Any] = {"image": decision.imagen, "clickAction": movil.vista}
            if movil.boton_abrir:
                datos["actions"] = [{"action": ACCION_ABRIR, "title": decision.boton}]
            datos.update(
                tag=decision.tag,
                alert_once=not decision.suena,
                sticky=True,
                notification_icon="mdi:doorbell-video",
                group="doorbell",
                channel="Doorbell",
                priority="high",
                importance="high",
                visibility="public",
                ttl=0,
                car_ui=True,
            )
            res.append(Llamada("notify", movil.notify, {"title": TITULO, "message": decision.mensaje, "data": datos}))
        return res

    if isinstance(decision, PedirNombre):
        res = []
        for ident in decision.destinatarios:
            movil = s.moviles.get(ident)
            if movil is None or ident in apagados:
                continue
            res.append(
                Llamada(
                    "notify",
                    movil.notify,
                    {
                        "title": "\U0001f697 Nueva matrícula detectada",
                        "message": f"Matrícula: {decision.matricula} ¿Quién es el propietario?",
                        "data": {
                            "image": decision.imagen,
                            "clickAction": movil.vista,
                            "actions": [
                                {
                                    "action": ACCION_NOMBRE,
                                    "title": "✍️ Escribir nombre",
                                    "behavior": "textInput",
                                    "textInputButtonTitle": "Guardar",
                                    "textInputPlaceholder": "Nombre del propietario",
                                },
                                {"action": ACCION_IGNORAR, "title": "❌ Ignorar"},
                            ],
                            "tag": decision.tag,
                            "alert_once": True,
                            "group": "Matrícula",
                            "channel": "Matrícula",
                            "notification_icon": "mdi:car",
                            "sticky": True,
                            "priority": "high",
                            "importance": "high",
                            "ttl": 0,
                        },
                    },
                )
            )
        return res

    if isinstance(decision, RetirarAviso):
        return [
            Llamada("notify", s.moviles[i].notify, {"message": "clear_notification", "data": {"tag": decision.tag}})
            for i in decision.destinatarios
            if i in s.moviles and i not in apagados
        ]

    if isinstance(decision, AbrirPuerta):
        entidad = s.abrir_automatica if decision.automatica else s.abrir_boton
        return [_encender(entidad)] if entidad else []

    if isinstance(decision, GuardarFoto):
        return [_encender(script) for script in s.al_timbre]

    if isinstance(decision, Banner):
        return [_texto(s.banner, decision.texto)] if s.banner else []

    if isinstance(decision, TerminaVisita):
        return []

    raise TypeError(decision)
