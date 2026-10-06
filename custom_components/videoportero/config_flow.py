"""Alta, opciones y dispositivos (subentradas «móvil» y «del hogar»).

DECISIONES §5: los dispositivos se añaden, cambian o quitan en cualquier
momento desde la página de la integración, sin YAML ni reinicio.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr, selector

from .configuracion import app_ha
from .requisitos import encontrado
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
    DOMAIN,
    SUB_HOGAR,
    SUB_MOVIL,
)


def _entidad(dominio: str | list[str], multiple: bool = False) -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=dominio, multiple=multiple))


def _opcional(clave: str, actual: Mapping[str, Any]) -> vol.Optional:
    """Opcional con el valor actual sugerido (y que se pueda dejar vacío)."""
    valor = actual.get(clave)
    return vol.Optional(clave, description={"suggested_value": valor} if valor not in (None, "", []) else None)


def esquema_videoportero(a: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_TIMBRE, default=a.get(CONF_TIMBRE, vol.UNDEFINED)): _entidad("binary_sensor"),
            vol.Required(CONF_PUERTA, default=a.get(CONF_PUERTA, vol.UNDEFINED)): _entidad("binary_sensor"),
            _opcional(CONF_CAMARA, a): _entidad("camera"),
            _opcional(CONF_CAMARA_FRIGATE, a): selector.TextSelector(),
            _opcional(CONF_PERSONAS, a): _entidad("sensor"),
            vol.Required(CONF_UMBRAL_CARA, default=a.get(CONF_UMBRAL_CARA, DEFECTO_UMBRAL_CARA)): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0.5, max=1, step=0.01, mode=selector.NumberSelectorMode.BOX)
            ),
            vol.Required(
                CONF_VISTA_LLAMADA, default=a.get(CONF_VISTA_LLAMADA, DEFECTO_VISTA_LLAMADA)
            ): selector.TextSelector(),
        }
    )


def esquema_acciones(a: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            _opcional(CONF_ABRIR_BOTON, a): _entidad(["script", "switch"]),
            _opcional(CONF_ABRIR_AUTOMATICA, a): _entidad(["script", "switch"]),
            _opcional(CONF_APERTURA_AUTOMATICA, a): _entidad("input_boolean"),
            _opcional(CONF_AUDIO, a): _entidad("input_boolean"),
            _opcional(CONF_MARCA_AUDIO, a): _entidad("input_text"),
            _opcional(CONF_BANNER, a): _entidad("input_text"),
            _opcional(CONF_AL_EMPEZAR, a): _entidad("script", multiple=True),
            _opcional(CONF_AL_TIMBRE, a): _entidad("script", multiple=True),
            _opcional(CONF_COMPARAR, a): _entidad("automation", multiple=True),
        }
    )


class VideoporteroConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._datos: dict[str, Any] = {}

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUB_MOVIL: MovilFlow, SUB_HOGAR: HogarFlow}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return VideoporteroOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            self._datos.update(user_input)
            return await self.async_step_acciones()
        return self.async_show_form(step_id="user", data_schema=esquema_videoportero({}))

    async def async_step_acciones(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._datos.update(user_input)
            return self.async_create_entry(title="Videoportero", data={}, options=self._datos)
        return self.async_show_form(step_id="acciones", data_schema=esquema_acciones({}))


class VideoporteroOptionsFlow(OptionsFlow):
    def __init__(self) -> None:
        self._datos: dict[str, Any] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._datos.update(user_input)
            return await self.async_step_acciones()
        return self.async_show_form(step_id="init", data_schema=esquema_videoportero(self.config_entry.options))

    async def async_step_acciones(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            # Las dos pantallas traen todos los campos: lo que se deja vacío
            # no viene y desaparece de las opciones.
            return self.async_create_entry(data={**self._datos, **user_input})
        return self.async_show_form(step_id="acciones", data_schema=esquema_acciones(self.config_entry.options))


# ── Dispositivos ─────────────────────────────────────────────────────


def _aparato() -> selector.DeviceSelector:
    return selector.DeviceSelector(selector.DeviceSelectorConfig(integration="mobile_app"))


def esquema_movil(a: Mapping[str, Any], con_aparato: bool) -> vol.Schema:
    campos: dict[Any, Any] = {}
    if con_aparato:
        campos[vol.Required(CONF_APARATO, default=a.get(CONF_APARATO, vol.UNDEFINED))] = _aparato()
    campos.update(
        {
            vol.Required(CONF_NOMBRE, default=a.get(CONF_NOMBRE, vol.UNDEFINED)): selector.TextSelector(),
            vol.Required(CONF_CON_DUENO, default=a.get(CONF_CON_DUENO, True)): selector.BooleanSelector(),
            _opcional(CONF_VISTA, a): selector.TextSelector(),
            _opcional(CONF_PANEL, a): _entidad("sensor"),
            vol.Required(CONF_AVISO_CIERRE, default=a.get(CONF_AVISO_CIERRE, True)): selector.BooleanSelector(),
            vol.Required(CONF_PIDE_NOMBRE, default=a.get(CONF_PIDE_NOMBRE, False)): selector.BooleanSelector(),
            vol.Required(CONF_BOTON_ABRIR, default=a.get(CONF_BOTON_ABRIR, True)): selector.BooleanSelector(),
            _opcional(CONF_MARCA, a): selector.TextSelector(),
        }
    )
    return vol.Schema(campos)


def esquema_hogar(a: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_NOMBRE, default=a.get(CONF_NOMBRE, vol.UNDEFINED)): selector.TextSelector(),
            _opcional(CONF_APARATO, a): _aparato(),
            _opcional(CONF_PANEL, a): _entidad("sensor"),
            _opcional(CONF_SCRIPTS_INICIO, a): _entidad("script", multiple=True),
        }
    )


class _FlujoDispositivo(ConfigSubentryFlow):
    def _nombre_aparato(self, device_id: str | None) -> str | None:
        aparato = dr.async_get(self.hass).async_get(device_id) if device_id else None
        return (aparato.name_by_user or aparato.name) if aparato else None

    def _ya_esta(self, device_id: str | None, salvo: str | None = None) -> bool:
        if not device_id:
            return False
        return any(
            s.data.get(CONF_APARATO) == device_id and s.subentry_id != salvo
            for s in self._get_entry().subentries.values()
        )

    def _titulo(self, datos: Mapping[str, Any]) -> str:
        aparato = self._nombre_aparato(datos.get(CONF_APARATO))
        nombre = datos[CONF_NOMBRE]
        return f"{nombre} ({aparato})" if aparato and aparato.strip() != nombre else nombre


class MovilFlow(_FlujoDispositivo):
    """Un móvil: recibe los avisos de la visita."""

    def __init__(self) -> None:
        self._aparato: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        errores: dict[str, str] = {}
        if user_input is not None:
            aparato = user_input[CONF_APARATO]
            if self._ya_esta(aparato):
                return self.async_abort(reason="ya_esta")
            if app_ha(self.hass, aparato) is None:
                errores[CONF_APARATO] = "sin_app"
            else:
                self._aparato = aparato
                return await self.async_step_detalles()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_APARATO): _aparato()}),
            errors=errores,
        )

    async def async_step_detalles(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is not None:
            datos = {CONF_APARATO: self._aparato, **user_input}
            return self.async_create_entry(title=self._titulo(datos), data=datos)
        sugerido: dict[str, Any] = {}
        app = app_ha(self.hass, self._aparato)
        if app is not None and app.usuario:
            usuario = await self.hass.auth.async_get_user(app.usuario)
            if usuario is not None:
                sugerido[CONF_NOMBRE] = usuario.name
        return self.async_show_form(
            step_id="detalles",
            data_schema=self.add_suggested_values_to_schema(esquema_movil({}, con_aparato=False), sugerido),
            description_placeholders={
                "aparato": self._nombre_aparato(self._aparato) or "",
                "encontrado": encontrado(self.hass, app, None),
            },
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        sub = self._get_reconfigure_subentry()
        errores: dict[str, str] = {}
        if user_input is not None:
            if self._ya_esta(user_input[CONF_APARATO], salvo=sub.subentry_id):
                return self.async_abort(reason="ya_esta")
            if app_ha(self.hass, user_input[CONF_APARATO]) is None:
                errores[CONF_APARATO] = "sin_app"
            else:
                return self.async_update_and_abort(
                    self._get_entry(), sub, title=self._titulo(user_input), data=user_input
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=esquema_movil(sub.data, con_aparato=True),
            errors=errores,
            description_placeholders={
                "encontrado": encontrado(self.hass, app_ha(self.hass, sub.data.get(CONF_APARATO)), sub.data.get(CONF_PANEL))
            },
        )


class HogarFlow(_FlujoDispositivo):
    """Un dispositivo del hogar: suena y muestra la cámara; no recibe avisos."""

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is not None:
            if self._ya_esta(user_input.get(CONF_APARATO)):
                return self.async_abort(reason="ya_esta")
            return self.async_create_entry(title=self._titulo(user_input), data=user_input)
        return self.async_show_form(step_id="user", data_schema=esquema_hogar({}))

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        sub = self._get_reconfigure_subentry()
        if user_input is not None:
            if self._ya_esta(user_input.get(CONF_APARATO), salvo=sub.subentry_id):
                return self.async_abort(reason="ya_esta")
            return self.async_update_and_abort(self._get_entry(), sub, title=self._titulo(user_input), data=user_input)
        return self.async_show_form(step_id="reconfigure", data_schema=esquema_hogar(sub.data))
