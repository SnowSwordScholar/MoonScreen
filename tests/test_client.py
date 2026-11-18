"""Control-plane client tests against the fake Sunshine server."""

from __future__ import annotations

import pytest
from custom_components.moonscreen.moonlight.client import SunshineClient
from custom_components.moonscreen.moonlight.errors import CannotConnect, SunshineError

from fake_sunshine import FakeSunshine


async def test_serverinfo_and_applist(paired_client: SunshineClient, fake_sunshine: FakeSunshine) -> None:
    info = await paired_client.async_get_serverinfo()
    assert info.hostname == "Fake PC"
    assert info.unique_id == "fake-server-uuid"
    assert info.current_app_id == 0
    assert info.vdd_capability_version == 1

    apps = await paired_client.async_get_applist()
    assert {app.app_id: app.title for app in apps} == {1: "Desktop", 2: "Steam Big Picture"}


async def test_launch_and_cancel(paired_client: SunshineClient, fake_sunshine: FakeSunshine) -> None:
    apps = await paired_client.async_get_applist()
    desktop = next(app for app in apps if app.title == "Desktop")

    result = await paired_client.async_launch(
        app_id=desktop.app_id,
        width=2560,
        height=1440,
        fps=60,
    )
    assert result.accepted
    assert fake_sunshine.app_state == desktop.app_id
    assert fake_sunshine.mode == "2560x1440x60"
    assert fake_sunshine.launch_params["useVdd"] == "1"
    assert fake_sunshine.launch_params["appid"] == str(desktop.app_id)

    info = await paired_client.async_get_serverinfo()
    assert info.current_app_id == desktop.app_id
    assert info.state == "SUNSHINE_SERVER_BUSY"

    await paired_client.async_cancel()
    assert fake_sunshine.app_state == 0
    info = await paired_client.async_get_serverinfo()
    assert info.current_app_id == 0


async def test_launch_reports_vdd_error(paired_client: SunshineClient, fake_sunshine: FakeSunshine) -> None:
    fake_sunshine.vdd_error = True
    with pytest.raises(SunshineError) as exc_info:
        await paired_client.async_launch(app_id=1, width=1920, height=1080, fps=60)

    assert exc_info.value.status_code == 503
    assert exc_info.value.error_code == "VDD_DRIVER_MISSING"
    assert "ZakoVDD" in exc_info.value.hint


async def test_launch_while_another_app_runs(paired_client: SunshineClient, fake_sunshine: FakeSunshine) -> None:
    fake_sunshine.app_state = 2
    with pytest.raises(SunshineError) as exc_info:
        await paired_client.async_launch(app_id=1, width=1920, height=1080, fps=60)

    assert exc_info.value.status_code == 400
    assert "already running" in str(exc_info.value)


async def test_web_sessions(paired_client: SunshineClient, fake_sunshine: FakeSunshine) -> None:
    fake_sunshine.app_state = 1
    sessions = await paired_client.async_get_web_sessions()
    assert sessions.available
    assert sessions.total_sessions == 1
    assert sessions.sessions[0].client_name == "Fake Moonlight"


async def test_web_sessions_wrong_password(paired_client: SunshineClient, fake_sunshine: FakeSunshine) -> None:
    paired_client.web_password = "wrong"
    if paired_client._web_session is not None:
        await paired_client._web_session.close()
    paired_client._web_session = None
    with pytest.raises(CannotConnect):
        await paired_client.async_get_web_sessions()
