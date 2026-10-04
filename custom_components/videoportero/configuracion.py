"""Monta la configuración del motor a partir de la entrada y sus subentradas.

De cada aparato de la app de HA se saca solo lo que hace falta: el servicio
de aviso (`notify.mobile_app_<nombre del aparato>`), su sensor
`last_used_app` (Android), el `device_id` que trae el botón ABRIR y el
usuario de HA con el que está registrada la app.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import slugify

from .const import (
    CONF_ABRIR_AUTOMATICA,
    CONF_ABRIR_BOTON,
    CONF_AL_EMPEZAR,
    CONF_AL_TIMBRE,
    CONF_APARATO,
    CONF_APERTURA_AUTOMATICA,
    CONF_AUDIO,
    CONF_AVISO_CIERRE,
    CONF_BANNER,
    CONF_BOTON_ABRIR,
    CONF_CAMARA,
    CONF_CAMARA_FRIGATE,
    CONF_COMPARAR,
    CONF_CON_DUENO,
    CONF_MARCA,
    CONF_MARCA_AUDIO,
    CONF_NOMBRE,
    CONF_PANEL,
    CONF_PERSONAS,
    CONF_PIDE_NOMBRE,
    CONF_PUERTA,
    CONF_SCRIPTS_INICIO,
    CONF_TIMBRE,
    CONF_UMBRAL_CARA,
    CONF_VISTA,
    CONF_VISTA_LLAMADA,
    DEFECTO_UMBRAL_CARA,
    DEFECTO_VISTA_LLAMADA,
    SUB_HOGAR,
    SUB_MOVIL,
)
from .llamadas import SalidaHogar, SalidaMovil, Salidas
from .motor import HOGAR, MOVIL, Ajustes, Dispositivo
from .traduccion import Entradas


@dataclass(frozen=True)
class AppHA:
    """Lo que interesa de un aparato con la app de Home Assistant."""

    notify: str  # servicio, sin «notify.»
    app_id: str  # el `device_id` que manda la app (botón ABRIR)
    usuario: str | None
    last_used_app: str | None
    android: bool


@dataclass(frozen=True)
class Casa:
    dispositivos: tuple[Dispositivo, ...]
    entradas: Entradas
    salidas: Salidas
    ajustes: Ajustes
    comparar: tuple[str, ...] = ()
    avisos: dict[str, str] = field(default_factory=dict)  # notify → dispositivo


def app_ha(hass: HomeAssistant, device_id: str | None) -> AppHA | None:
    if not device_id:
        return None
    aparato = dr.async_get(hass).async_get(device_id)
    if aparato is None:
        return None
    ident = next((i for d, i in aparato.identifiers if d == "mobile_app"), None)
    if ident is None:
        return None
    entrada = next(
        (e for e in hass.config_entries.async_entries("mobile_app") if e.data.get("device_id") == ident),
        None,
    )
    if entrada is None:
        return None
    sensor = next(
        (
            e.entity_id
            for e in er.async_entries_for_device(er.async_get(hass), device_id)
            if e.domain == "sensor" and e.unique_id.endswith("_last_used_app")
        ),
        None,
    )
    return AppHA(
        notify=f"mobile_app_{slugify(entrada.data.get('device_name') or '')}",
        app_id=ident,
        usuario=entrada.data.get("user_id"),
        last_used_app=sensor,
        android=str(entrada.data.get("os_name", "")).lower() == "android",
    )


def _lista(valor: Any) -> tuple[str, ...]:
    if not valor:
        return ()
    if isinstance(valor, str):
        return (valor,)
    return tuple(v for v in valor if v)


def leer(hass: HomeAssistant, entrada: ConfigEntry) -> Casa:
    o = entrada.options
    dispositivos: list[Dispositivo] = []
    moviles: dict[str, SalidaMovil] = {}
    hogar: dict[str, SalidaHogar] = {}
    app: dict[str, str] = {}
    panel: dict[str, str] = {}
    aparatos: dict[str, str] = {}
    usuarios: dict[str, list[str]] = {}
    marcas: dict[str, str] = {}
    avisos: dict[str, str] = {}

    for sub in entrada.subentries.values():
        d = sub.data
        ident = sub.subentry_id
        datos_app = app_ha(hass, d.get(CONF_APARATO))
        if d.get(CONF_PANEL):
            panel[d[CONF_PANEL]] = ident
        if datos_app is not None:
            aparatos[datos_app.app_id] = ident
            if datos_app.usuario:
                usuarios.setdefault(datos_app.usuario, []).append(ident)
        if sub.subentry_type == SUB_MOVIL:
            dispositivos.append(
                Dispositivo(
                    ident,
                    d.get(CONF_NOMBRE) or sub.title,
                    MOVIL,
                    personal=bool(d.get(CONF_CON_DUENO, True)),
                    aviso_cierre=bool(d.get(CONF_AVISO_CIERRE, True)),
                    pide_nombre_matricula=bool(d.get(CONF_PIDE_NOMBRE, False)),
                )
            )
            if datos_app is not None:
                moviles[ident] = SalidaMovil(datos_app.notify, d.get(CONF_VISTA) or "", bool(d.get(CONF_BOTON_ABRIR, True)))
                avisos[datos_app.notify] = ident
                if datos_app.last_used_app:
                    app[datos_app.last_used_app] = ident
            if d.get(CONF_MARCA):
                marcas[str(d[CONF_MARCA]).strip()] = ident
        elif sub.subentry_type == SUB_HOGAR:
            dispositivos.append(Dispositivo(ident, d.get(CONF_NOMBRE) or sub.title, HOGAR, personal=False))
            hogar[ident] = SalidaHogar(_lista(d.get(CONF_SCRIPTS_INICIO)))

    camara = o.get(CONF_CAMARA) or ""
    ajustes = Ajustes(
        umbral_cara=float(o.get(CONF_UMBRAL_CARA, DEFECTO_UMBRAL_CARA)),
        imagen_camara=f"/api/camera_proxy/{camara}" if camara else "",
        ventana_abrir=timedelta(seconds=60),
    )
    entradas = Entradas(
        timbre=o.get(CONF_TIMBRE) or "",
        puerta=o.get(CONF_PUERTA) or "",
        camara_caras=o.get(CONF_CAMARA_FRIGATE) or "",
        personas=o.get(CONF_PERSONAS) or "",
        apertura_automatica=o.get(CONF_APERTURA_AUTOMATICA) or "",
        audio=o.get(CONF_AUDIO) or "",
        marca_audio=o.get(CONF_MARCA_AUDIO) or "",
        marcas=marcas,
        app=app,
        panel=panel,
        aparatos=aparatos,
        # Un usuario con varios aparatos no dice cuál: solo cuenta si es único.
        usuarios={u: ids[0] for u, ids in usuarios.items() if len(ids) == 1},
        vista_llamada=o.get(CONF_VISTA_LLAMADA) or DEFECTO_VISTA_LLAMADA,
    )
    salidas = Salidas(
        moviles=moviles,
        hogar=hogar,
        al_empezar=_lista(o.get(CONF_AL_EMPEZAR)),
        al_timbre=_lista(o.get(CONF_AL_TIMBRE)),
        abrir_boton=o.get(CONF_ABRIR_BOTON) or "",
        abrir_automatica=o.get(CONF_ABRIR_AUTOMATICA) or "",
        banner=o.get(CONF_BANNER) or "",
        marca_audio=o.get(CONF_MARCA_AUDIO) or "",
    )
    return Casa(tuple(dispositivos), entradas, salidas, ajustes, _lista(o.get(CONF_COMPARAR)), avisos)
