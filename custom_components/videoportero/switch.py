"""Un interruptor «Avisos» por dispositivo (DECISIONES §11).

Apagado, un móvil no recibe ningún aviso y un dispositivo del hogar no lanza
sus scripts. Lo que decide la visita no cambia: si alguien abre HA en un
móvil apagado, sigue contando como que atiende. Se recuerda tras reiniciar.

El entity_id se fija al crearlo (`switch.videoportero_avisos_<título>`)
porque la automatización lo consulta mientras siga mandando.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import slugify

from . import EntradaVideoportero, Sistema
from .const import DOMAIN, SUB_MOVIL


def entity_id_avisos(sub: ConfigSubentry) -> str:
    return f"switch.{DOMAIN}_avisos_{slugify(sub.title)}"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: EntradaVideoportero,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    sistema = entry.runtime_data

    def anadir(subentradas: Iterable[ConfigSubentry]) -> None:
        for sub in subentradas:
            if sub.subentry_id in sistema.interruptores:
                continue
            interruptor = Avisos(entry, sistema, sub)
            sistema.interruptores[sub.subentry_id] = interruptor
            async_add_entities([interruptor], config_subentry_id=sub.subentry_id)

    # Los dispositivos que se añadan después llegan por cambiar_configuracion.
    sistema.anadir_interruptores = anadir
    anadir(entry.subentries.values())


class Avisos(SwitchEntity, RestoreEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "avisos"

    def __init__(self, entry: EntradaVideoportero, sistema: Sistema, sub: ConfigSubentry) -> None:
        self.entity_id = entity_id_avisos(sub)
        self._attr_unique_id = f"{entry.entry_id}_{sub.subentry_id}_avisos"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, sub.subentry_id)},
            name=sub.title,
            manufacturer="Videoportero",
            model="Móvil" if sub.subentry_type == SUB_MOVIL else "Dispositivo del hogar",
            via_device=(DOMAIN, entry.entry_id),
            entry_type=DeviceEntryType.SERVICE,
        )
        self._attr_is_on = True
        self._sistema = sistema
        self._id = sub.subentry_id

    async def async_added_to_hass(self) -> None:
        ultimo = await self.async_get_last_state()
        if ultimo is not None:
            self._attr_is_on = ultimo.state != "off"
        self._sistema.poner_avisos(self._id, self._attr_is_on)

    async def async_will_remove_from_hass(self) -> None:
        self._sistema.interruptores.pop(self._id, None)
        self._sistema.poner_avisos(self._id, True)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._cambiar(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._cambiar(False)

    def _cambiar(self, encendido: bool) -> None:
        self._attr_is_on = encendido
        self._sistema.poner_avisos(self._id, encendido)
        self.async_write_ha_state()
