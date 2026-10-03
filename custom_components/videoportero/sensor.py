"""Sensores: la visita (en curso o la última) y las diferencias del modo sombra."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import EntradaVideoportero, Sistema
from .const import DOMAIN, SENAL_CAMBIO

ESTADOS_VISITA = ["sin_visita", "en_curso", "atendida", "abierta_automaticamente"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EntradaVideoportero,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    sistema = entry.runtime_data
    async_add_entities([SensorVisita(entry, sistema), SensorDiferencias(entry, sistema)])


class EntidadVideoportero(SensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: EntradaVideoportero, sistema: Sistema, clave: str) -> None:
        # entity_id fijo: el que HA genera a partir del nombre traducido
        # depende del idioma de la instalación (como en Matrículas, §8).
        self.entity_id = f"sensor.{DOMAIN}_{clave}"
        self._attr_unique_id = f"{entry.entry_id}_{clave}"
        self._attr_translation_key = clave
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Videoportero",
            manufacturer="Videoportero",
            model="Visitas al videoportero",
            entry_type=DeviceEntryType.SERVICE,
        )
        self._sistema = sistema

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(async_dispatcher_connect(self.hass, SENAL_CAMBIO, self._al_cambiar))

    @callback
    def _al_cambiar(self) -> None:
        self.async_write_ha_state()


class SensorVisita(EntidadVideoportero):
    """En curso, atendida o abierta (mientras dura el banner) o sin visita.

    En la fase 1 refleja lo que ve la integración en sombra; la casa sigue
    mandando con la automatización.
    """

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ESTADOS_VISITA

    def __init__(self, entry: EntradaVideoportero, sistema: Sistema) -> None:
        super().__init__(entry, sistema, "visita")

    @property
    def native_value(self) -> str:
        return self._sistema.estado_visita

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        v = self._sistema.motor.visita
        if v is not None:
            return {
                "tag": v.tag,
                "inicio": v.inicio.isoformat(),
                "motivo": v.motivo,
                "coche": v.coche or None,
                "persona": v.persona or None,
                "timbres": len(v.timbres),
            }
        ultima = self._sistema.ultima
        if not ultima:
            return {}
        return {f"ultima_{k}": ultima.get(k) for k in ("inicio", "motivo", "estado", "coche", "persona", "atendida_por", "como")}


class SensorDiferencias(EntidadVideoportero):
    """Cuántas llamadas no coincidieron con la automatización (últimos 90 días)."""

    _attr_native_unit_of_measurement = "diferencias"

    def __init__(self, entry: EntradaVideoportero, sistema: Sistema) -> None:
        super().__init__(entry, sistema, "diferencias")

    @property
    def native_value(self) -> int:
        return len(self._sistema.historial.diferencias)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        h = self._sistema.historial
        return {
            "coincidencias": h.comparadas,
            "visitas": len(h.visitas),
            "ultimas": [f"{d['hora'][:19]} {d['lado']}: {d['resumen']}" for d in h.diferencias[-5:]],
        }
