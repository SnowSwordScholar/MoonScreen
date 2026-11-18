"""Home Assistant wiring for the MoonScreen config entry."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_CLIENT_CERT,
    CONF_CLIENT_KEY,
    CONF_CLIENT_UNIQUE_ID,
    CONF_HOST,
    CONF_HTTP_PORT,
    CONF_HTTPS_PORT,
    CONF_PAIRING_NAME,
    CONF_SERVER_CERT,
    CONF_WEB_PASSWORD,
    CONF_WEB_PORT,
    CONF_WEB_USERNAME,
    PLATFORMS,
)
from .coordinator import MoonScreenCoordinator
from .moonlight import SunshineClient


@dataclass(slots=True)
class MoonScreenRuntime:
    """Objects shared by the platforms of one config entry."""

    client: SunshineClient
    coordinator: MoonScreenCoordinator


MoonScreenConfigEntry = ConfigEntry[MoonScreenRuntime]


async def async_setup_entry(hass: HomeAssistant, entry: MoonScreenConfigEntry) -> bool:
    """Set up MoonScreen from a config entry."""

    data = entry.data
    options = entry.options
    client = SunshineClient(
        host=data[CONF_HOST],
        https_port=int(data.get(CONF_HTTPS_PORT, 47984)),
        http_port=int(data.get(CONF_HTTP_PORT, 47989)),
        web_port=int(data.get(CONF_WEB_PORT, 47990)),
        client_cert_pem=data[CONF_CLIENT_CERT],
        client_key_pem=data[CONF_CLIENT_KEY],
        server_cert_pem=data[CONF_SERVER_CERT],
        client_unique_id=data[CONF_CLIENT_UNIQUE_ID],
        client_name=data.get(CONF_PAIRING_NAME, "MoonScreen"),
        web_username=str(options.get(CONF_WEB_USERNAME, data.get(CONF_WEB_USERNAME, ""))),
        web_password=str(options.get(CONF_WEB_PASSWORD, data.get(CONF_WEB_PASSWORD, ""))),
    )

    coordinator = MoonScreenCoordinator(hass, entry, client)
    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await client.close()
        raise

    entry.runtime_data = MoonScreenRuntime(client=client, coordinator=coordinator)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: MoonScreenConfigEntry) -> None:
    """Reload when the user changes options."""

    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: MoonScreenConfigEntry) -> bool:
    """Unload a config entry."""

    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.client.close()
    return unloaded
