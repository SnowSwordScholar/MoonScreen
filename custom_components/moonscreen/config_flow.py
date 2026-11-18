"""Config flow for MoonScreen."""

from __future__ import annotations

import asyncio
import logging
import secrets
import uuid
import xml.etree.ElementTree as ET
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_CLIENT_CERT,
    CONF_CLIENT_KEY,
    CONF_CLIENT_UNIQUE_ID,
    CONF_DESKTOP_APP_NAME,
    CONF_FPS,
    CONF_HEIGHT,
    CONF_HOST,
    CONF_HTTP_PORT,
    CONF_HTTPS_PORT,
    CONF_PAIRING_NAME,
    CONF_POLL_INTERVAL,
    CONF_PROTECT_ACTIVE_STREAM,
    CONF_SERVER_CERT,
    CONF_SERVER_HOSTNAME,
    CONF_SERVER_UNIQUE_ID,
    CONF_SERVER_VERSION,
    CONF_WEB_PASSWORD,
    CONF_WEB_PORT,
    CONF_WEB_USERNAME,
    CONF_WIDTH,
    DEFAULT_DESKTOP_APP_NAME,
    DEFAULT_FPS,
    DEFAULT_HEIGHT,
    DEFAULT_HTTP_PORT,
    DEFAULT_HTTPS_PORT,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_WEB_PORT,
    DEFAULT_WIDTH,
    DOMAIN,
    MAX_DIMENSION,
    MAX_FPS,
    MAX_POLL_INTERVAL,
    MIN_DIMENSION,
    MIN_FPS,
    MIN_POLL_INTERVAL,
)
from .logic import InvalidOption, build_mode, validate_poll_interval
from .moonlight import CannotConnect, PairingFailed, PairingRequired, SunshineClient, SunshineError
from .moonlight.crypto import generate_client_credentials
from .moonlight.pairing import PairingResult, format_host, pair_with_pin

_LOGGER = logging.getLogger(__name__)

_PAIR_TIMEOUT = 45.0


def _normalize_host(value: str) -> str:
    host = value.strip()
    for prefix in ("https://", "http://"):
        if host.startswith(prefix):
            host = host[len(prefix) :]
    host = host.rstrip("/")
    if "/" in host:
        host = host.split("/", 1)[0]
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return host


def _port(value: Any, default: int) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return default
    return port if 1 <= port <= 65535 else default


class MoonScreenConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Pair with Sunshine and create one screen switch."""

    VERSION = 1

    def __init__(self) -> None:
        self._user_input: dict[str, Any] = {}
        self._pair_task: asyncio.Task[PairingResult] | None = None
        self._pair_result: PairingResult | None = None
        self._pin = ""
        self._client_cert = ""
        self._client_key = ""
        self._client_unique_id = ""
        self._vdd_note = ""
        self._reauth_entry: config_entries.ConfigEntry | None = None

    # ------------------------------------------------------------------ user

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = dict(user_input)
            user_input[CONF_HOST] = _normalize_host(str(user_input.get(CONF_HOST, "")))
            user_input[CONF_HTTPS_PORT] = _port(user_input.get(CONF_HTTPS_PORT), DEFAULT_HTTPS_PORT)
            user_input[CONF_HTTP_PORT] = _port(user_input.get(CONF_HTTP_PORT), DEFAULT_HTTP_PORT)
            user_input[CONF_WEB_PORT] = _port(user_input.get(CONF_WEB_PORT), DEFAULT_WEB_PORT)
            try:
                build_mode(
                    int(user_input[CONF_WIDTH]),
                    int(user_input[CONF_HEIGHT]),
                    int(user_input[CONF_FPS]),
                )
                validate_poll_interval(int(user_input[CONF_POLL_INTERVAL]))
            except (InvalidOption, KeyError, TypeError, ValueError) as err:
                errors["base"] = "invalid_option"
                _LOGGER.debug("MoonScreen: invalid options: %s", err)
            else:
                try:
                    preflight = await self._preflight(user_input)
                except CannotConnect as err:
                    errors["base"] = "cannot_connect"
                    _LOGGER.warning("MoonScreen: preflight failed: %s", err)
                else:
                    self._user_input = user_input
                    self._vdd_note = (
                        "Sunshine 明确报告不支持虚拟屏（VddCapabilityVersion=0），关闭屏幕可能不会生效。"
                        if preflight.get("vdd") == "0"
                        else ""
                    )
                    try:
                        await self._start_pairing()
                    except Exception:
                        _LOGGER.exception("MoonScreen: unable to start pairing")
                        errors["base"] = "pairing_failed"
                    else:
                        return await self.async_step_pair_pin()

        return self.async_show_form(step_id="user", data_schema=self._user_schema(), errors=errors)

    def _user_schema(self) -> vol.Schema:
        defaults = self._user_input
        return vol.Schema(
            {
                vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
                vol.Optional(
                    CONF_HTTPS_PORT,
                    default=defaults.get(CONF_HTTPS_PORT, DEFAULT_HTTPS_PORT),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
                vol.Optional(
                    CONF_HTTP_PORT,
                    default=defaults.get(CONF_HTTP_PORT, DEFAULT_HTTP_PORT),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
                vol.Optional(
                    CONF_WEB_PORT,
                    default=defaults.get(CONF_WEB_PORT, DEFAULT_WEB_PORT),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
                vol.Optional(
                    CONF_DESKTOP_APP_NAME,
                    default=defaults.get(CONF_DESKTOP_APP_NAME, DEFAULT_DESKTOP_APP_NAME),
                ): str,
                vol.Optional(
                    CONF_WIDTH,
                    default=defaults.get(CONF_WIDTH, DEFAULT_WIDTH),
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_DIMENSION, max=MAX_DIMENSION)),
                vol.Optional(
                    CONF_HEIGHT,
                    default=defaults.get(CONF_HEIGHT, DEFAULT_HEIGHT),
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_DIMENSION, max=MAX_DIMENSION)),
                vol.Optional(
                    CONF_FPS,
                    default=defaults.get(CONF_FPS, DEFAULT_FPS),
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_FPS, max=MAX_FPS)),
                vol.Optional(
                    CONF_POLL_INTERVAL,
                    default=defaults.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_POLL_INTERVAL, max=MAX_POLL_INTERVAL)),
                vol.Optional(
                    CONF_WEB_USERNAME,
                    default=defaults.get(CONF_WEB_USERNAME, ""),
                ): str,
                vol.Optional(
                    CONF_WEB_PASSWORD,
                    default=defaults.get(CONF_WEB_PASSWORD, ""),
                ): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
                vol.Optional(
                    CONF_PROTECT_ACTIVE_STREAM,
                    default=defaults.get(CONF_PROTECT_ACTIVE_STREAM, False),
                ): bool,
            }
        )

    async def _preflight(self, user_input: dict[str, Any]) -> dict[str, str | None]:
        host = str(user_input[CONF_HOST])
        port = int(user_input[CONF_HTTP_PORT])
        url = f"http://{format_host(host)}:{port}/serverinfo"
        timeout = aiohttp.ClientTimeout(total=10.0, sock_connect=5.0)
        try:
            async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
                async with session.get(url, params={"uniqueid": "moonscreen-preflight"}) as response:
                    text = await response.text()
                    if response.status != 200:
                        raise CannotConnect(f"HTTP {response.status}: {text[:160]}")
        except aiohttp.ClientError as err:
            raise CannotConnect(f"无法连接 {host}:{port}：{err}") from err
        except TimeoutError as err:
            raise CannotConnect(f"连接 {host}:{port} 超时") from err

        try:
            root = ET.fromstring(text)
        except ET.ParseError as err:
            raise CannotConnect("Sunshine 的 /serverinfo 返回了无法解析的 XML") from err
        if root.findtext("hostname") is None:
            raise CannotConnect("这个地址不像 Sunshine 的 GameStream 端口")
        return {
            "hostname": root.findtext("hostname") or "",
            "uniqueid": root.findtext("uniqueid") or "",
            # Foundation versions differ here: some return this field, older
            # builds (including v2026.705 on the author's host) do not.
            "vdd": root.findtext("VddCapabilityVersion"),
        }

    # ------------------------------------------------------------------ pairing

    @staticmethod
    def _consume_task_exception(task: asyncio.Task[PairingResult]) -> None:
        if not task.cancelled():
            task.exception()

    async def _start_pairing(self) -> None:
        self._pair_result = None
        self._client_cert, self._client_key = await self.hass.async_add_executor_job(
            generate_client_credentials,
            "MoonScreen",
        )
        self._client_unique_id = str(uuid.uuid4())
        self._pin = f"{secrets.randbelow(10000):04d}"
        self._pair_task = self.hass.async_create_task(
            pair_with_pin(
                host=str(self._user_input[CONF_HOST]),
                http_port=int(self._user_input[CONF_HTTP_PORT]),
                https_port=int(self._user_input[CONF_HTTPS_PORT]),
                client_cert_pem=self._client_cert,
                client_key_pem=self._client_key,
                pin=self._pin,
                client_unique_id=self._client_unique_id,
                pairing_name=str(self._user_input.get(CONF_PAIRING_NAME, "MoonScreen")),
            )
        )
        self._pair_task.add_done_callback(self._consume_task_exception)
        # The first pairing request blocks on the host until the PIN is entered,
        # so there is no response to wait for.  Give it a moment to register the
        # pending request in the Web UI before showing the PIN.
        await asyncio.sleep(1.0)

    async def async_step_pair_pin(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if self._pair_task is None:
            return self.async_abort(reason="pairing_failed")

        errors: dict[str, str] = {}
        if user_input is not None and user_input.get("confirm"):
            try:
                if self._pair_result is None:
                    self._pair_result = await asyncio.wait_for(
                        asyncio.shield(self._pair_task),
                        timeout=_PAIR_TIMEOUT,
                    )
            except TimeoutError:
                errors["base"] = "pin_not_confirmed"
            except PairingFailed as err:
                _LOGGER.warning("MoonScreen: pairing failed: %s", err)
                await self._start_pairing()
                errors["base"] = "invalid_pin" if err.invalid_pin else "pairing_failed"
            except CannotConnect as err:
                errors["base"] = "cannot_connect"
                _LOGGER.warning("MoonScreen: pairing connection failed: %s", err)
                try:
                    await self._start_pairing()
                except Exception:
                    _LOGGER.exception("MoonScreen: unable to restart pairing after a connection error")
            except Exception:
                _LOGGER.exception("MoonScreen: pairing failed")
                await self._start_pairing()
                errors["base"] = "pairing_failed"
            else:
                try:
                    return await self._finish_pairing(self._pair_result)
                except (CannotConnect, PairingRequired) as err:
                    errors["base"] = "cannot_connect"
                    _LOGGER.warning("MoonScreen: post-pairing check failed: %s", err)
                except SunshineError as err:
                    errors["base"] = "pairing_failed"
                    _LOGGER.warning("MoonScreen: post-pairing check failed: %s", err)
        elif user_input is not None:
            errors["base"] = "confirm_required"

        return self.async_show_form(
            step_id="pair_pin",
            data_schema=vol.Schema({vol.Required("confirm", default=False): bool}),
            errors=errors,
            description_placeholders={
                "pin": self._pin,
                "host": str(self._user_input.get(CONF_HOST, "")),
                "web_url": self._web_url(),
                "vdd_note": self._vdd_note,
            },
        )

    def _web_url(self) -> str:
        host = format_host(str(self._user_input.get(CONF_HOST, "")))
        port = int(self._user_input.get(CONF_WEB_PORT, DEFAULT_WEB_PORT))
        return f"https://{host}:{port}/pin"

    async def _finish_pairing(self, result: PairingResult) -> FlowResult:
        client = await SunshineClient.async_create(
            host=str(self._user_input[CONF_HOST]),
            https_port=int(self._user_input[CONF_HTTPS_PORT]),
            http_port=int(self._user_input[CONF_HTTP_PORT]),
            web_port=int(self._user_input[CONF_WEB_PORT]),
            client_cert_pem=result.client_cert_pem,
            client_key_pem=result.client_key_pem,
            server_cert_pem=result.server_cert_pem,
            client_unique_id=result.client_unique_id,
            client_name=result.pairing_name,
            web_username=str(self._user_input.get(CONF_WEB_USERNAME, "")),
            web_password=str(self._user_input.get(CONF_WEB_PASSWORD, "")),
        )
        try:
            server = await client.async_get_serverinfo()
            apps = await client.async_get_applist()
        finally:
            await client.close()

        desktop_app = next(
            (app for app in apps if app.title.casefold() == str(self._user_input[CONF_DESKTOP_APP_NAME]).casefold()),
            None,
        )
        if desktop_app is None:
            _LOGGER.warning(
                "MoonScreen: Desktop app %r not found on the host; the switch will stay unavailable until the option is fixed",
                self._user_input[CONF_DESKTOP_APP_NAME],
            )

        unique_id = server.unique_id or f"{self._user_input[CONF_HOST]}:{self._user_input[CONF_HTTPS_PORT]}"
        data: dict[str, Any] = {
            CONF_HOST: str(self._user_input[CONF_HOST]),
            CONF_HTTPS_PORT: int(self._user_input[CONF_HTTPS_PORT]),
            CONF_HTTP_PORT: int(self._user_input[CONF_HTTP_PORT]),
            CONF_WEB_PORT: int(self._user_input[CONF_WEB_PORT]),
            CONF_CLIENT_CERT: result.client_cert_pem,
            CONF_CLIENT_KEY: result.client_key_pem,
            CONF_SERVER_CERT: result.server_cert_pem,
            CONF_CLIENT_UNIQUE_ID: result.client_unique_id,
            CONF_PAIRING_NAME: result.pairing_name,
            CONF_DESKTOP_APP_NAME: str(self._user_input[CONF_DESKTOP_APP_NAME]),
            CONF_WIDTH: int(self._user_input[CONF_WIDTH]),
            CONF_HEIGHT: int(self._user_input[CONF_HEIGHT]),
            CONF_FPS: int(self._user_input[CONF_FPS]),
            CONF_POLL_INTERVAL: int(self._user_input[CONF_POLL_INTERVAL]),
            CONF_WEB_USERNAME: str(self._user_input.get(CONF_WEB_USERNAME, "")),
            CONF_WEB_PASSWORD: str(self._user_input.get(CONF_WEB_PASSWORD, "")),
            CONF_PROTECT_ACTIVE_STREAM: bool(self._user_input.get(CONF_PROTECT_ACTIVE_STREAM, False)),
            CONF_SERVER_UNIQUE_ID: server.unique_id,
            CONF_SERVER_HOSTNAME: server.hostname,
            CONF_SERVER_VERSION: server.version_label,
        }

        if self._reauth_entry is not None:
            return self.async_update_reload_and_abort(self._reauth_entry, data=data, reason="reauth_successful")

        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=server.hostname or str(self._user_input[CONF_HOST]), data=data)

    # ------------------------------------------------------------------ reauth

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="reauth_failed")
        self._reauth_entry = entry
        self._user_input = {**entry.data, **entry.options}
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None and user_input.get("confirm"):
            try:
                await self._start_pairing()
            except Exception:
                _LOGGER.exception("MoonScreen: unable to restart pairing")
                errors["base"] = "pairing_failed"
            else:
                return await self.async_step_pair_pin()
        elif user_input is not None:
            errors["base"] = "confirm_required"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required("confirm", default=False): bool}),
            errors=errors,
            description_placeholders={"host": str(self._user_input.get(CONF_HOST, ""))},
        )

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> MoonScreenOptionsFlow:
        return MoonScreenOptionsFlow()


class MoonScreenOptionsFlow(config_entries.OptionsFlow):
    """Edit the resolution, app name and optional WebUI credentials."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            try:
                build_mode(
                    int(user_input[CONF_WIDTH]),
                    int(user_input[CONF_HEIGHT]),
                    int(user_input[CONF_FPS]),
                )
                validate_poll_interval(int(user_input[CONF_POLL_INTERVAL]))
            except (InvalidOption, KeyError, TypeError, ValueError):
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._schema(),
                    errors={"base": "invalid_option"},
                )
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(step_id="init", data_schema=self._schema())

    def _schema(self) -> vol.Schema:
        current = {**self.config_entry.data, **self.config_entry.options}
        return vol.Schema(
            {
                vol.Optional(
                    CONF_DESKTOP_APP_NAME,
                    default=str(current.get(CONF_DESKTOP_APP_NAME, DEFAULT_DESKTOP_APP_NAME)),
                ): str,
                vol.Optional(
                    CONF_WIDTH,
                    default=int(current.get(CONF_WIDTH, DEFAULT_WIDTH)),
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_DIMENSION, max=MAX_DIMENSION)),
                vol.Optional(
                    CONF_HEIGHT,
                    default=int(current.get(CONF_HEIGHT, DEFAULT_HEIGHT)),
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_DIMENSION, max=MAX_DIMENSION)),
                vol.Optional(
                    CONF_FPS,
                    default=int(current.get(CONF_FPS, DEFAULT_FPS)),
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_FPS, max=MAX_FPS)),
                vol.Optional(
                    CONF_POLL_INTERVAL,
                    default=int(current.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)),
                ): vol.All(vol.Coerce(int), vol.Range(min=MIN_POLL_INTERVAL, max=MAX_POLL_INTERVAL)),
                vol.Optional(
                    CONF_WEB_USERNAME,
                    default=str(current.get(CONF_WEB_USERNAME, "")),
                ): str,
                vol.Optional(
                    CONF_WEB_PASSWORD,
                    default=str(current.get(CONF_WEB_PASSWORD, "")),
                ): selector.TextSelector(selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)),
                vol.Optional(
                    CONF_PROTECT_ACTIVE_STREAM,
                    default=bool(current.get(CONF_PROTECT_ACTIVE_STREAM, False)),
                ): bool,
            }
        )
