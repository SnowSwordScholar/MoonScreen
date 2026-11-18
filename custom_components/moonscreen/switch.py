"""The 电脑屏幕 switch."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_ENTITY_NAME
from .coordinator import MoonScreenCoordinator
from .entity import build_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add the screen switch for a config entry."""

    coordinator: MoonScreenCoordinator = entry.runtime_data.coordinator
    async_add_entities([MoonScreenSwitch(coordinator, entry)])


class MoonScreenSwitch(CoordinatorEntity[MoonScreenCoordinator], SwitchEntity):
    """Switch whose ON state means the physical screen is on."""

    _attr_name = DEFAULT_ENTITY_NAME
    _attr_has_entity_name = False

    def __init__(self, coordinator: MoonScreenCoordinator, entry: ConfigEntry) -> None:
        # CoordinatorEntity subscribes to coordinator updates and calls
        # async_write_ha_state() on every poll; without it the HA state machine
        # keeps the value from setup until the integration is reloaded.
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_screen"
        self._attr_device_info = build_device_info(entry)

    @property
    def available(self) -> bool:
        return self.coordinator.last_update_success and self.coordinator.data is not None

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        return None if data is None else data.screen_on

    @property
    def icon(self) -> str:
        return "mdi:monitor" if self.is_on else "mdi:monitor-off"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        if data is None:
            return {}
        server = data.server
        web = data.web
        return {
            "app_id": data.app_id,
            "app_name": data.app_name or None,
            "server_version": server.version_label or None,
            "vdd_capability_version": server.vdd_capability_version or None,
            "desktop_app_id": data.desktop_app_id,
            "resolution": data.resolution,
            "last_launch_at": data.last_launch_at.isoformat() if data.last_launch_at else None,
            "last_cancel_at": data.last_cancel_at.isoformat() if data.last_cancel_at else None,
            "active_sessions": web.total_sessions if web.available else None,
            "active_clients": web.active_clients if web.available else None,
            "web_api_ok": web.available,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the physical screen on by quitting the running app."""

        await self.coordinator.async_turn_on_screen()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the physical screen off by starting Desktop on the host."""

        await self.coordinator.async_turn_off_screen()
