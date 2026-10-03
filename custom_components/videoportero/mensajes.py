"""Textos de los avisos de una visita. No importa nada de Home Assistant.

Porte de la plantilla «Compone el mensaje y el boton de la notificacion» de
la automatización que sustituye, con un cambio deliberado (DECISIONES §4): al
atender o abrir se dice quién fue, en vez de «Alguien», cuando se sabe.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .motor import Dispositivo, Visita

BOTON_ABRIR = "ABRE LA PUERTA"
BOTON_ABRIR_CERRAR = "ABRIR / CERRAR"
TIMBRE = "\U0001f514"


def mensaje(v: Visita, hora: datetime, quien: Dispositivo | None) -> str:
    """El texto del aviso para el estado actual de la visita.

    `quien` es el dispositivo que atendió o abrió, si se sabe. Puede ser
    cadena vacía: la automatización también lo era cuando no había nada que
    contar, y el aviso solo se manda si el motor lo decide.
    """
    h = hora.strftime("%H:%M")
    if v.persona:
        visitante = f" a {v.persona}"
    elif v.coche:
        visitante = f" al coche de {v.coche}"
    else:
        visitante = ""

    if v.atendida:
        abierta = v.abierto_boton
        if quien is None:
            return f"Alguien {'ha abierto la puerta' if abierta else 'ha atendido'}{visitante} ({h})"
        if quien.personal:
            return f"{quien.nombre} {'ha abierto la puerta' if abierta else 'ha atendido'}{visitante} ({h})"
        # Un aparato sin dueño (tablet, iPad): no es él quien abre.
        return f"{'Han abierto la puerta' if abierta else 'Han atendido'}{visitante} desde {quien.nombre} ({h})"

    if v.abrimos:
        if v.persona:
            return f"He abierto la puerta a {v.persona} ({h})"
        if v.coche:
            return f"He abierto la puerta al coche de {v.coche} ({h})"
        return f"He abierto la puerta ({h})"

    if v.timbre_pulsado:
        if v.persona:
            return f"{TIMBRE} {v.persona} está llamando al timbre ({h})"
        if v.coche:
            return f"{TIMBRE} Coche de {v.coche} está llamando al timbre ({h})"
        if v.persona_desconocida:
            return f"{TIMBRE} Alguien desconocido está llamando al timbre ({h})"
        if v.coche_desconocido:
            return f"{TIMBRE} Coche desconocido está llamando al timbre ({h})"
        return f"{TIMBRE} Alguien está llamando al timbre ({h})"

    if v.persona:
        return f"{v.persona} está en la puerta ({h})"
    if v.coche:
        return f"Coche de {v.coche} en la puerta ({h})"
    if v.persona_desconocida:
        return f"Alguien desconocido en la puerta ({h})"
    if v.coche_desconocido:
        return f"Coche desconocido en la puerta ({h})"
    return ""


def boton(v: Visita) -> str:
    """Texto del botón ABRIR: tras abrir o atender, el portón puede estar abierto."""
    return BOTON_ABRIR_CERRAR if (v.abrimos or v.atendida) else BOTON_ABRIR
