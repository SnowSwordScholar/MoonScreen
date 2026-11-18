"""Diagnostics support for MoonScreen."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_CLIENT_CERT,
    CONF_CLIENT_KEY,
    CONF_SERVER_CERT,
    CONF_WEB_PASSWORD,
)
from .moonlight.crypto import certificate_fingerprint

_REDACT = {
    CONF_CLIENT_CERT,
    CONF_CLIENT_KEY,
    CONF_SERVER_CERT,
    CONF_WEB_PASSWORD,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostic information without credential material."""

    runtime = getattr(entry, "runtime_data", None)
    coordinator = getattr(runtime, "coordinator", None)
    data = getattr(coordinator, "data", None)

    entry_data = {key: ("**REDACTED**" if key in _REDACT else value) for key, value in entry.data.items()}
    entry_data["server_cert_sha256"] = certificate_fingerprint(entry.data[CONF_SERVER_CERT])

    diagnostics: dict[str, Any] = {
        "entry": entry_data,
        "options": dict(entry.options),
        "last_update_success": bool(getattr(coordinator, "last_update_success", False)),
    }
    if data is not None:
        diagnostics["state"] = {
            "screen_on": data.screen_on,
            "app_id": data.app_id,
            "app_name": data.app_name,
            "resolution": data.resolution,
            "server": asdict(data.server),
            "web": {
                "available": data.web.available,
                "total_sessions": data.web.total_sessions,
                "clients": data.web.active_clients,
            },
        }
    return diagnostics
