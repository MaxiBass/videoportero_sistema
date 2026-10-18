"""Sensor de la visita: la que está en curso o la última."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EntradaVideoportero, Sistema, dispositivo_principal
from .const import DOMAIN, SENAL_CAMBIO

ESTADOS_VISITA = ["sin_visita", "en_curso", "atendida", "abierta_automaticamente"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EntradaVideoportero,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    sistema = entry.runtime_data
    async_add_entities([SensorVisita(entry, sistema)])


class EntidadVideoportero(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: EntradaVideoportero, sistema: Sistema, clave: str) -> None:
        # entity_id fijo: el que HA genera a partir del nombre traducido
        # depende del idioma de la instalación (como en Matrículas, §8).
        self.entity_id = f"sensor.{DOMAIN}_{clave}"
        self._attr_unique_id = f"{entry.entry_id}_{clave}"
        self._attr_translation_key = clave
        self._attr_device_info = dispositivo_principal(entry)
        self._sistema = sistema

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, SENAL_CAMBIO, self._al_cambiar))

    @callback
    def _al_cambiar(self) -> None:
        self.async_write_ha_state()


class SensorVisita(EntidadVideoportero):
    """En curso, atendida o abierta (mientras dura el banner) o sin visita."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ESTADOS_VISITA

    def __init__(self, entry: EntradaVideoportero, sistema: Sistema) -> None:
        super().__init__(entry, sistema, "visita")

    @property
    def native_value(self) -> str:
        return self._sistema.estado_visita

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self._sistema
        # Cómo van sus llamadas desde que arrancó
        llamadas: dict[str, Any] = {"llamadas_hechas": s.hechas, "llamadas_fallidas": s.fallidas}
        v = s.motor.visita
        if v is not None:
            return llamadas | {
                "tag": v.tag,
                "inicio": v.inicio.isoformat(),
                "motivo": v.motivo,
                "coche": v.coche or None,
                "persona": v.persona or None,
                "timbres": len(v.timbres),
            }
        ultima = s.ultima
        if not ultima:
            return llamadas
        return llamadas | {
            f"ultima_{k}": ultima.get(k) for k in ("inicio", "motivo", "estado", "coche", "persona", "atendida_por", "como")
        }
