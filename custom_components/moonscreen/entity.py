"""Shared entity helpers."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceInfo

from .const import (
    CONF_HOST,
    CONF_SERVER_HOSTNAME,
    CONF_SERVER_UNIQUE_ID,
    CONF_SERVER_VERSION,
    CONF_WEB_PORT,
    DOMAIN,
)


def build_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Device registry entry shared by all platforms of this integration."""

    data = entry.data
    unique_id = str(data.get(CONF_SERVER_UNIQUE_ID) or entry.entry_id)
    host = data.get(CONF_HOST, "")
    web_port = int(data.get(CONF_WEB_PORT, 47990))
    info = DeviceInfo(
        identifiers={(DOMAIN, unique_id)},
        name=entry.title,
        manufacturer="AlkaidLab / LizardByte",
        model="Foundation Sunshine",
        sw_version=str(data.get(CONF_SERVER_VERSION) or ""),
    )
    if host:
        info["configuration_url"] = f"https://{host}:{web_port}"
    if data.get(CONF_SERVER_HOSTNAME):
        info["name"] = str(data[CONF_SERVER_HOSTNAME])
    return info
