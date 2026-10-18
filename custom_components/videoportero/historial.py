"""Historial de visitas, en `.storage`.

Se guardan 90 días (DECISIONES §7). Las fotos no se copian: solo la ruta que
ya usaba el aviso (la de Frigate o la de la cámara).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DIAS_HISTORIAL, DOMAIN
from .motor import Dispositivo, Visita

VERSION = 1


def visita_a_dict(v: Visita, dispositivos: dict[str, Dispositivo], imagen: str) -> dict[str, Any]:
    quien = dispositivos.get(v.dispositivo_atendio) if v.dispositivo_atendio else None
    return {
        "tag": v.tag,
        "inicio": v.inicio.isoformat(),
        "fin": v.fin.isoformat() if v.fin else None,
        "motivo": v.motivo,
        "estado": v.estado,
        "coche": v.coche,
        "persona": v.persona,
        "persona_desconocida": v.persona_desconocida,
        "coche_desconocido": v.coche_desconocido,
        "matriculas": list(v.matriculas),
        "caras": list(v.caras),
        "timbres": [t.isoformat() for t in v.timbres],
        "como": v.como,
        "atendida_por": quien.nombre if quien else None,
        "avisos": v.avisos,
        "imagen": imagen,
    }


class Historial:
    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict[str, Any]] = Store(hass, VERSION, f"{DOMAIN}.historial")
        self.visitas: list[dict[str, Any]] = []

    async def cargar(self) -> None:
        datos = await self._store.async_load() or {}
        # Hasta la v0.3.0 también guardaba las diferencias del modo sombra;
        # se ignoran y desaparecen al guardar.
        self.visitas = list(datos.get("visitas", []))
        self._podar(dt_util.now())

    def _podar(self, ahora: datetime) -> None:
        limite = (ahora - timedelta(days=DIAS_HISTORIAL)).isoformat()
        self.visitas = [v for v in self.visitas if v["inicio"] >= limite]

    def visita(self, datos: dict[str, Any]) -> None:
        self.visitas.append(datos)
        self._podar(dt_util.now())
        self.guardar()

    def guardar(self) -> None:
        self._store.async_delay_save(
            lambda: {"visitas": self.visitas},
            5,
        )
