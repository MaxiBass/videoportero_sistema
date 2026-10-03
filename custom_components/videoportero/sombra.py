"""Modo sombra: compara lo que habría hecho la integración con lo que hace la
automatización de verdad. No importa nada de Home Assistant.

La integración no ejecuta nada: apunta las llamadas que habría hecho, y de la
casa apunta las que hacen las automatizaciones que sustituye. Cada llamada se
empareja con una igual del otro lado hecha a menos de TOLERANCIA segundos; la
que se queda sin pareja más de PLAZO segundos es una diferencia.

Antes de comparar se deshacen los dos cambios aprobados (DECISIONES §4), que
la automatización no tiene: decir quién y no avisar a quien pulsó ABRIR.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from .llamadas import Llamada
from .motor import POR_PUERTA, Avisar, Decision, Dispositivo, TerminaVisita

TOLERANCIA = 5.0
PLAZO = 20.0
HORA = re.compile(r"\(\d\d:\d\d\)")

SOLO_INTEGRACION = "solo_integracion"
SOLO_AUTOMATIZACION = "solo_automatizacion"


def claves(dominio: str, servicio: str, datos: Mapping[str, Any]) -> list[tuple[str, str, str, str]]:
    """Una llamada como tuplas comparables, una por entidad.

    Se ignora lo que cambia sin que importe: la hora en el texto del aviso y
    el tag de la visita, que lleva su hora de inicio.
    """
    datos = dict(datos)
    if dominio in ("script", "switch", "input_text"):
        ents = datos.pop("entity_id", [])
        ents = [ents] if isinstance(ents, str) else list(ents)
        resto = json.dumps(datos, sort_keys=True, ensure_ascii=False)
        return [(dominio, servicio, e, resto) for e in ents]
    if dominio == "notify":
        if isinstance(datos.get("message"), str):
            datos["message"] = HORA.sub("(hh:mm)", datos["message"])
        interno = datos.get("data")
        if isinstance(interno, dict) and str(interno.get("tag", "")).startswith("visita-"):
            datos["data"] = {**interno, "tag": "visita-*"}
        return [(dominio, servicio, "", json.dumps(datos, sort_keys=True, ensure_ascii=False))]
    return [(dominio, servicio, "", json.dumps(datos, sort_keys=True, ensure_ascii=False))]


def como_la_automatizacion(decisiones: Iterable[Decision], dispositivos: Mapping[str, Dispositivo]) -> list[Decision]:
    """Las decisiones sin los dos cambios aprobados, para compararlas."""
    decisiones = list(decisiones)
    fin = next((d.visita for d in decisiones if isinstance(d, TerminaVisita)), None)
    nombres = {d.nombre for d in dispositivos.values()}
    moviles = [d.id for d in dispositivos.values() if d.recibe_avisos]
    res: list[Decision] = []
    for d in decisiones:
        if isinstance(d, Avisar) and d.cierre and fin is not None:
            m = d.mensaje
            for n in sorted(nombres, key=len, reverse=True):
                m = m.replace(f"{n} ha atendido", "Alguien ha atendido")
                m = m.replace(f"{n} ha abierto la puerta", "Alguien ha abierto la puerta")
                m = re.sub(
                    rf"^Han (atendido|abierto la puerta)(.*) desde {re.escape(n)} (\(\d\d:\d\d\))$",
                    lambda x: f"Alguien ha {x.group(1)}{x.group(2)} {x.group(3)}",
                    m,
                )
            dest = d.destinatarios
            quien = fin.dispositivo_atendio
            if fin.como == POR_PUERTA and quien in moviles and quien not in dest:
                dest = tuple(i for i in moviles if i in dest or i == quien)
            d = replace(d, mensaje=m, destinatarios=dest)
        res.append(d)
    return res


@dataclass
class Apunte:
    hora: float
    clave: tuple[str, str, str, str]
    visita: str | None = None


@dataclass(frozen=True)
class Diferencia:
    hora: float
    lado: str
    clave: tuple[str, str, str, str]
    visita: str | None

    def resumen(self) -> str:
        dominio, servicio, entidad, datos = self.clave
        if dominio == "notify":
            try:
                d = json.loads(datos)
            except ValueError:
                d = {}
            return f"{servicio}: {d.get('message', '')}"
        return f"{dominio}.{servicio} {entidad} {datos if datos != '{}' else ''}".strip()


@dataclass
class Comparador:
    tolerancia: float = TOLERANCIA
    plazo: float = PLAZO
    esperadas: list[Apunte] = field(default_factory=list)
    reales: list[Apunte] = field(default_factory=list)
    emparejadas: int = 0

    def esperada(self, hora: float, llamada: Llamada, visita: str | None) -> None:
        for c in claves(llamada.dominio, llamada.servicio, llamada.datos):
            self._apuntar(Apunte(hora, c, visita), self.esperadas, self.reales)

    def real(self, hora: float, dominio: str, servicio: str, datos: Mapping[str, Any]) -> None:
        for c in claves(dominio, servicio, datos):
            self._apuntar(Apunte(hora, c), self.reales, self.esperadas)

    def _apuntar(self, a: Apunte, propia: list[Apunte], otra: list[Apunte]) -> None:
        for i, b in enumerate(otra):
            if b.clave == a.clave and abs(b.hora - a.hora) <= self.tolerancia:
                otra.pop(i)
                self.emparejadas += 1
                return
        propia.append(a)

    def revisar(self, ahora: float) -> list[Diferencia]:
        """Lo que lleva más de PLAZO s sin pareja."""
        dif = []
        for lista, lado in ((self.esperadas, SOLO_INTEGRACION), (self.reales, SOLO_AUTOMATIZACION)):
            quedan = []
            for a in lista:
                if ahora - a.hora > self.plazo:
                    dif.append(Diferencia(a.hora, lado, a.clave, a.visita))
                else:
                    quedan.append(a)
            lista[:] = quedan
        return sorted(dif, key=lambda d: d.hora)
