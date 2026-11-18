"""MoonScreen - a Home Assistant switch for Foundation Sunshine's virtual screen.

The Home Assistant imports are deliberately kept out of this module's import
time so the protocol layer can be tested without a Home Assistant install.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up MoonScreen from a config entry."""

    from .integration import async_setup_entry as _async_setup_entry

    return await _async_setup_entry(hass, entry)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    from .integration import async_unload_entry as _async_unload_entry

    return await _async_unload_entry(hass, entry)
