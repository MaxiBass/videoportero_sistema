"""Lo que necesita cada dispositivo, y avisos en Reparaciones si falta algo.

Ver docs/REQUISITOS.md. Se revisa al arrancar, al cambiar la configuración y
cada media hora. Solo se avisa de lo que falta o está desactivado, no de lo
que está «no disponible» un rato: el BrowserMod de un móvil lo está siempre
que la app de HA no está delante.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er, issue_registry as ir

from .configuracion import AppHA, app_ha, visibilidad
from .const import CONF_APARATO, CONF_PANEL, CONF_SCRIPTS_INICIO, DOMAIN, SUB_MOVIL


@dataclass(frozen=True)
class Problema:
    subentrada: str
    clave: str  # translation_key del aviso en Reparaciones
    dispositivo: str
    detalle: str = ""


def _existe(hass: HomeAssistant, entidad: str) -> bool:
    """Existe y no está desactivada (registrada o, si no, con estado)."""
    reg = er.async_get(hass).async_get(entidad)
    if reg is not None:
        return reg.disabled_by is None
    return hass.states.get(entidad) is not None


def encontrado(hass: HomeAssistant, app: AppHA | None, panel: str | None) -> str:
    """Resumen legible de lo que la integración ha encontrado para un móvil."""
    if app is None:
        return "no se encuentra la app de HA en ese aparato"
    partes = [f"avisos por notify.{app.notify}"]
    if app.android:
        partes.append(f"última app: {app.last_used_app}" if app.last_used_app else "última app: NO (actívala en la app de HA)")
    else:
        partes.append("sin «última app» (app de Apple)")
    if panel:
        vis = visibilidad(hass, panel)
        partes.append(f"BrowserMod: {panel}" + (f" y {vis}" if vis and _existe(hass, vis) else ", sin sensor de visibilidad"))
    return "; ".join(partes)


def problemas(hass: HomeAssistant, entrada: ConfigEntry) -> list[Problema]:
    res: list[Problema] = []
    for sub in entrada.subentries.values():
        d = sub.data
        nombre = sub.title
        app = app_ha(hass, d.get(CONF_APARATO)) if d.get(CONF_APARATO) else None
        if d.get(CONF_APARATO) and app is None:
            res.append(Problema(sub.subentry_id, "sin_app", nombre))
        if sub.subentry_type == SUB_MOVIL and app is not None:
            if not hass.services.has_service("notify", app.notify):
                res.append(Problema(sub.subentry_id, "sin_servicio_avisos", nombre, f"notify.{app.notify}"))
            if app.android and (not app.last_used_app or not _existe(hass, app.last_used_app)):
                res.append(Problema(sub.subentry_id, "sin_ultima_app", nombre, app.last_used_app or "Last used app"))
        panel = d.get(CONF_PANEL)
        if panel:
            if not _existe(hass, panel):
                res.append(Problema(sub.subentry_id, "sin_browsermod", nombre, panel))
            elif sub.subentry_type == SUB_MOVIL:
                vis = visibilidad(hass, panel)
                if not vis or not _existe(hass, vis):
                    res.append(Problema(sub.subentry_id, "sin_visibilidad", nombre, vis or panel))
        for script in d.get(CONF_SCRIPTS_INICIO) or []:
            if hass.states.get(script) is None:
                res.append(Problema(sub.subentry_id, "sin_script", nombre, script))
    return res


@callback
def revisar_requisitos(hass: HomeAssistant, entrada: ConfigEntry) -> list[Problema]:
    """Crea un aviso por cada problema y quita los que ya no lo son."""
    actuales = problemas(hass, entrada)
    ids = set()
    for p in actuales:
        issue_id = f"{p.subentrada}_{p.clave}"
        ids.add(issue_id)
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=p.clave,
            translation_placeholders={"dispositivo": p.dispositivo, "detalle": p.detalle},
        )
    registro = ir.async_get(hass)
    for (dominio, issue_id) in list(registro.issues):
        if dominio == DOMAIN and issue_id not in ids:
            ir.async_delete_issue(hass, DOMAIN, issue_id)
    return actuales
