"""Home Assistant config/options flow tests.

These tests need ``pytest-homeassistant-custom-component`` and are skipped in
the lightweight protocol-test environment.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("homeassistant")
pytest.importorskip("pytest_homeassistant_custom_component")

from custom_components.moonscreen.config_flow import MoonScreenConfigFlow
from custom_components.moonscreen.const import DOMAIN
from custom_components.moonscreen.moonlight.errors import CannotConnect
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

_USER_INPUT = {
    "host": "10.0.0.2",
    "https_port": 47984,
    "http_port": 47989,
    "web_port": 47990,
    "desktop_app_name": "Desktop",
    "width": 1920,
    "height": 1080,
    "fps": 60,
    "poll_interval": 15,
    "web_username": "",
    "web_password": "",
    "protect_active_stream": False,
}


async def _start_user_flow(hass):
    return await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )


async def test_user_form(hass, enable_custom_integrations) -> None:
    result = await _start_user_flow(hass)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_user_cannot_connect(hass, enable_custom_integrations, monkeypatch) -> None:
    async def fake_preflight(self, user_input):
        raise CannotConnect("unreachable")

    monkeypatch.setattr(MoonScreenConfigFlow, "_preflight", fake_preflight)
    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input=_USER_INPUT)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_user_moves_to_pin_step(hass, enable_custom_integrations, monkeypatch) -> None:
    async def fake_preflight(self, user_input):
        return {"hostname": "Test PC", "uniqueid": "server-id", "vdd": "1"}

    async def fake_start_pairing(self) -> None:
        self._pin = "1234"
        self._pair_task = asyncio.create_task(asyncio.sleep(0))

    monkeypatch.setattr(MoonScreenConfigFlow, "_preflight", fake_preflight)
    monkeypatch.setattr(MoonScreenConfigFlow, "_start_pairing", fake_start_pairing)

    result = await _start_user_flow(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input=_USER_INPUT)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "pair_pin"


async def test_options_form(hass, enable_custom_integrations) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Test PC",
        data={
            "host": "10.0.0.2",
            "https_port": 47984,
            "http_port": 47989,
            "web_port": 47990,
            "client_cert_pem": "cert",
            "client_key_pem": "key",
            "server_cert_pem": "server-cert",
            "client_unique_id": "client-id",
            "pairing_name": "MoonScreen",
            "desktop_app_name": "Desktop",
            "width": 1920,
            "height": 1080,
            "fps": 60,
            "poll_interval": 15,
            "web_username": "",
            "web_password": "",
            "protect_active_stream": False,
            "server_uniqueid": "server-id",
            "server_hostname": "Test PC",
            "server_version": "test",
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"
