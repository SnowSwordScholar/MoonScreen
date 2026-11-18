"""State coordinator and screen actions."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_DESKTOP_APP_NAME,
    CONF_FPS,
    CONF_HEIGHT,
    CONF_POLL_INTERVAL,
    CONF_PROTECT_ACTIVE_STREAM,
    CONF_WIDTH,
    DEFAULT_DESKTOP_APP_NAME,
    DEFAULT_FPS,
    DEFAULT_HEIGHT,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_WIDTH,
    DOMAIN,
)
from .logic import app_label, should_block_cancel
from .moonlight import CannotConnect, PairingRequired, SunshineClient, SunshineError
from .moonlight.models import ServerInfo, WebSessions

_LOGGER = logging.getLogger(__name__)

_APP_CACHE_SECONDS = 300


@dataclass(slots=True)
class ScreenState:
    """Everything the switch needs for one poll."""

    screen_on: bool
    app_id: int
    app_name: str
    server: ServerInfo
    web: WebSessions
    desktop_app_id: int
    width: int
    height: int
    fps: int
    last_launch_at: datetime | None = None
    last_cancel_at: datetime | None = None

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}@{self.fps}"


class MoonScreenCoordinator(DataUpdateCoordinator[ScreenState]):
    """Poll the host and serialize screen actions."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        client: SunshineClient,
    ) -> None:
        self.client = client
        self.entry = entry
        self._apps: dict[int, str] = {}
        self._apps_loaded_at = 0.0
        self._desktop_app_id: int | None = None
        self._desktop_app_name = ""
        self._last_launch_at: datetime | None = None
        self._last_cancel_at: datetime | None = None
        self._web_warned = False
        self._action_lock = asyncio.Lock()

        interval = int(
            entry.options.get(
                CONF_POLL_INTERVAL,
                entry.data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
            )
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
            config_entry=entry,
        )

    # ------------------------------------------------------------------ options

    def _option(self, key: str, default: int) -> int:
        return int(self.entry.options.get(key, self.entry.data.get(key, default)))

    @property
    def width(self) -> int:
        return self._option(CONF_WIDTH, DEFAULT_WIDTH)

    @property
    def height(self) -> int:
        return self._option(CONF_HEIGHT, DEFAULT_HEIGHT)

    @property
    def fps(self) -> int:
        return self._option(CONF_FPS, DEFAULT_FPS)

    @property
    def desktop_app_name(self) -> str:
        return str(
            self.entry.options.get(
                CONF_DESKTOP_APP_NAME,
                self.entry.data.get(CONF_DESKTOP_APP_NAME, DEFAULT_DESKTOP_APP_NAME),
            )
        )

    @property
    def protect_active_stream(self) -> bool:
        return bool(
            self.entry.options.get(
                CONF_PROTECT_ACTIVE_STREAM,
                self.entry.data.get(CONF_PROTECT_ACTIVE_STREAM, False),
            )
        )

    # ------------------------------------------------------------------ polling

    async def _async_update_data(self) -> ScreenState:
        try:
            server = await self.client.async_get_serverinfo()
        except PairingRequired as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (CannotConnect, SunshineError) as err:
            raise UpdateFailed(str(err)) from err

        if server.current_app_id and server.current_app_id not in self._apps:
            await self._refresh_apps()

        desktop_app_id = await self._ensure_desktop_app()
        web = await self._refresh_web_sessions()

        return ScreenState(
            screen_on=server.current_app_id <= 0,
            app_id=server.current_app_id,
            app_name=app_label(server.current_app_id, self._apps),
            server=server,
            web=web,
            desktop_app_id=desktop_app_id,
            width=self.width,
            height=self.height,
            fps=self.fps,
            last_launch_at=self._last_launch_at,
            last_cancel_at=self._last_cancel_at,
        )

    async def _refresh_apps(self) -> None:
        try:
            apps = await self.client.async_get_applist()
        except (CannotConnect, PairingRequired, SunshineError) as err:
            _LOGGER.debug("MoonScreen: unable to refresh app list: %s", err)
            return
        self._apps = {app.app_id: app.title for app in apps}
        self._apps_loaded_at = time.monotonic()

    async def _ensure_desktop_app(self) -> int:
        name = self.desktop_app_name
        cache_fresh = (time.monotonic() - self._apps_loaded_at) <= _APP_CACHE_SECONDS
        if self._desktop_app_id is not None and self._desktop_app_name == name and cache_fresh:
            return self._desktop_app_id

        if (
            not cache_fresh
            or not self._apps
            or name.casefold() not in {title.casefold() for title in self._apps.values()}
        ):
            await self._refresh_apps()

        match = next(
            (app_id for app_id, title in self._apps.items() if title.casefold() == name.casefold()),
            None,
        )
        if match is None:
            raise UpdateFailed(f"Sunshine 的应用列表中找不到“{name}”")
        self._desktop_app_id = match
        self._desktop_app_name = name
        return match

    async def _refresh_web_sessions(self) -> WebSessions:
        try:
            return await self.client.async_get_web_sessions()
        except (CannotConnect, PairingRequired, SunshineError) as err:
            if not self._web_warned:
                _LOGGER.warning(
                    "MoonScreen: WebUI session API is unavailable (%s); "
                    "active-stream attributes and the optional cancel guard are disabled",
                    err,
                )
                self._web_warned = True
            return WebSessions(available=False)

    # ------------------------------------------------------------------ actions

    async def _action_serverinfo(self) -> ServerInfo:
        try:
            return await self.client.async_get_serverinfo()
        except PairingRequired as err:
            self.entry.async_start_reauth(self.hass)
            raise HomeAssistantError("MoonScreen 的配对已失效，请在集成页重新配对") from err
        except (CannotConnect, SunshineError) as err:
            raise HomeAssistantError(f"无法连接 Sunshine：{err}") from err

    async def async_turn_off_screen(self) -> None:
        """Start Desktop, which makes Sunshine create the VDD and turn off the panel."""

        async with self._action_lock:
            state = await self._action_serverinfo()
            if state.current_app_id == self._desktop_app_id and self._desktop_app_id:
                return
            if state.current_app_id > 0:
                raise HomeAssistantError(
                    f"Sunshine 上已有其他应用在运行：{app_label(state.current_app_id, self._apps)}"
                )

            try:
                await self.client.async_launch(
                    app_id=self._desktop_app_id or 0,
                    width=self.width,
                    height=self.height,
                    fps=self.fps,
                )
            except SunshineError as err:
                if err.status_code == 400 and "already running" in err.message.lower():
                    # A client started Desktop between our check and the launch.
                    await self.async_request_refresh()
                    if self.data is not None and self.data.app_id == self._desktop_app_id:
                        return
                raise HomeAssistantError(str(err)) from err
            except PairingRequired as err:
                self.entry.async_start_reauth(self.hass)
                raise HomeAssistantError("MoonScreen 的配对已失效，请在集成页重新配对") from err
            except CannotConnect as err:
                raise HomeAssistantError(f"无法连接 Sunshine：{err}") from err

            self._last_launch_at = dt_util.utcnow()
            await self.async_request_refresh()

    async def async_turn_on_screen(self) -> None:
        """Ask Sunshine to quit the running app and restore the physical display."""

        async with self._action_lock:
            state = await self._action_serverinfo()
            if state.current_app_id <= 0:
                return

            if self.protect_active_stream:
                web = await self._refresh_web_sessions()
                if web.available and should_block_cancel(
                    protect_active_stream=True,
                    active_sessions=web.total_sessions,
                ):
                    client_names = web.active_clients or "未知客户端"
                    raise HomeAssistantError(
                        f"Moonlight 正在串流（客户端：{client_names}），已阻止开屏；"
                        "如需强制开屏，请在选项里关闭“保护正在串流的会话”"
                    )

            try:
                await self.client.async_cancel()
            except PairingRequired as err:
                self.entry.async_start_reauth(self.hass)
                raise HomeAssistantError("MoonScreen 的配对已失效，请在集成页重新配对") from err
            except (CannotConnect, SunshineError) as err:
                raise HomeAssistantError(f"无法结束 Desktop：{err}") from err

            self._last_cancel_at = dt_util.utcnow()
            for _ in range(20):
                await asyncio.sleep(1)
                try:
                    current = await self.client.async_get_serverinfo()
                except (CannotConnect, PairingRequired, SunshineError) as err:
                    _LOGGER.debug("MoonScreen: polling after cancel failed: %s", err)
                    break
                if current.current_app_id <= 0:
                    break
            else:
                raise HomeAssistantError("已发送退出请求，但 Desktop 仍在运行；请检查 Sunshine 日志")

            await self.async_request_refresh()

    async def async_shutdown(self) -> None:
        await super().async_shutdown()
        await self.client.close()
