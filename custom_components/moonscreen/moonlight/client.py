"""HTTPS control-plane client for Foundation Sunshine.

Only the endpoints needed by the switch are implemented.  Requests use the
paired client certificate and the pinned host certificate; no video, audio,
RTSP or control channel is ever opened.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import xml.etree.ElementTree as ET
from typing import Any

import aiohttp

from .errors import CannotConnect, PairingRequired, SunshineError
from .models import AppInfo, LaunchResult, ServerInfo, SessionInfo, WebSessions
from .pairing import format_host
from .tls import create_mtls_context, create_server_context

_LOGGER = logging.getLogger(__name__)

_DEFAULT_TIMEOUT = 30.0
_LAUNCH_TIMEOUT = 90.0
_SERVERINFO_TIMEOUT = 15.0


def _parse_root(text: str) -> ET.Element:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as err:
        raise SunshineError(0, f"Sunshine 返回了无法解析的响应：{text[:160]!r}") from err

    try:
        status_code = int(root.attrib.get("status_code", "200"))
    except ValueError:
        status_code = 0

    if status_code != 200:
        raise SunshineError(
            status_code,
            root.attrib.get("status_message") or f"Sunshine 返回状态 {status_code}",
            error_code=root.findtext("sunshine_error_code") or "",
            hint=root.findtext("sunshine_error_hint") or "",
            recoverable=root.findtext("sunshine_recoverable") == "1",
        )
    return root


def _text_int(root: ET.Element, tag: str) -> int:
    value = root.findtext(tag)
    if not value:
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


class SunshineClient:
    """Small async client for one Sunshine host."""

    def __init__(
        self,
        *,
        host: str,
        https_port: int,
        http_port: int,
        web_port: int,
        client_cert_pem: str,
        client_key_pem: str,
        server_cert_pem: str,
        client_unique_id: str,
        client_name: str = "MoonScreen",
        web_username: str = "",
        web_password: str = "",
    ) -> None:
        self.host = host
        self.https_port = https_port
        self.http_port = http_port
        self.web_port = web_port
        self.client_unique_id = client_unique_id
        self.client_name = client_name
        self.web_username = web_username
        self.web_password = web_password

        host_part = format_host(host)
        self._https_base = f"https://{host_part}:{https_port}"
        self._web_base = f"https://{host_part}:{web_port}"

        self._mtls_context = create_mtls_context(server_cert_pem, client_cert_pem, client_key_pem)
        self._web_context = create_server_context(server_cert_pem)
        self._session: aiohttp.ClientSession | None = None
        self._web_session: aiohttp.ClientSession | None = None
        self._closed = False

    @classmethod
    async def async_create(cls, **kwargs: Any) -> SunshineClient:
        """Create the client off the event loop.

        ``ssl.SSLContext.load_cert_chain`` writes/reads temporary PEM files and
        is a blocking call; HA's event-loop protector flags it when it runs on
        the main thread.  The whole constructor is therefore executed in a
        worker thread.
        """

        return await asyncio.to_thread(cls, **kwargs)

    # ------------------------------------------------------------------ sessions

    def _get_session(self) -> aiohttp.ClientSession:
        if self._closed:
            raise CannotConnect("MoonScreen 客户端已关闭")
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=self._mtls_context),
                timeout=aiohttp.ClientTimeout(total=_DEFAULT_TIMEOUT, sock_connect=10.0),
                trust_env=False,
            )
        return self._session

    def _get_web_session(self) -> aiohttp.ClientSession:
        if self._closed:
            raise CannotConnect("MoonScreen 客户端已关闭")
        if self._web_session is None or self._web_session.closed:
            self._web_session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=self._web_context),
                timeout=aiohttp.ClientTimeout(total=_DEFAULT_TIMEOUT, sock_connect=10.0),
                auth=aiohttp.BasicAuth(self.web_username, self.web_password),
                trust_env=False,
            )
        return self._web_session

    async def close(self) -> None:
        self._closed = True
        sessions = [session for session in (self._session, self._web_session) if session is not None]
        self._session = None
        self._web_session = None
        if sessions:
            await asyncio.gather(*(session.close() for session in sessions), return_exceptions=True)

    # ------------------------------------------------------------------ requests

    async def _get(
        self,
        path: str,
        *,
        params: dict[str, str] | None = None,
        timeout_total: float = _DEFAULT_TIMEOUT,
    ) -> ET.Element:
        session = self._get_session()
        try:
            async with session.get(
                f"{self._https_base}{path}",
                params=params,
                timeout=aiohttp.ClientTimeout(total=timeout_total, sock_connect=10.0),
            ) as response:
                text = await response.text()
                if response.status in (401, 403):
                    raise PairingRequired("Sunshine 不再接受 MoonScreen 的客户端证书")
                if response.status >= 500 and not text.lstrip().startswith("<"):
                    raise SunshineError(response.status, f"Sunshine 返回 HTTP {response.status}")
                if response.status >= 400 and not text.lstrip().startswith("<"):
                    raise SunshineError(response.status, f"Sunshine 返回 HTTP {response.status}")
                root = _parse_root(text)
                if response.status != 200:
                    raise SunshineError(
                        response.status,
                        root.attrib.get("status_message") or f"HTTP {response.status}",
                    )
                return root
        except aiohttp.ClientSSLError as err:
            raise PairingRequired(f"与 Sunshine 的 TLS 连接失败：{err}") from err
        except aiohttp.ClientConnectorError as err:
            raise CannotConnect(f"无法连接 {self.host}:{self.https_port}：{err}") from err
        except aiohttp.ClientConnectionError as err:
            raise CannotConnect(f"与 Sunshine 的连接中断：{err}") from err
        except TimeoutError as err:
            raise CannotConnect(f"连接 {self.host}:{self.https_port} 超时") from err

    # ------------------------------------------------------------------ endpoints

    async def async_get_serverinfo(self) -> ServerInfo:
        root = await self._get(
            "/serverinfo",
            params={"uniqueid": self.client_unique_id},
            timeout_total=_SERVERINFO_TIMEOUT,
        )
        return ServerInfo(
            unique_id=root.findtext("uniqueid") or "",
            hostname=root.findtext("hostname") or "",
            app_version=root.findtext("appversion") or "",
            sunshine_version=root.findtext("SunshineVersion") or "",
            current_app_id=_text_int(root, "currentgame"),
            state=root.findtext("state") or "",
            pair_status=_text_int(root, "PairStatus"),
            vdd_capability_version=_text_int(root, "VddCapabilityVersion"),
            display_modes=root.findtext("FsDisplayModes") or "",
        )

    async def async_get_applist(self) -> list[AppInfo]:
        root = await self._get("/applist")
        apps: list[AppInfo] = []
        for app in root.findall("App"):
            try:
                app_id = int(app.findtext("ID") or 0)
            except ValueError:
                continue
            title = app.findtext("AppTitle") or ""
            if app_id > 0 and title:
                apps.append(AppInfo(app_id=app_id, title=title))
        return apps

    async def async_launch(
        self,
        *,
        app_id: int,
        width: int,
        height: int,
        fps: int,
    ) -> LaunchResult:
        params = {
            "appid": str(app_id),
            "rikey": secrets.token_hex(16),
            "rikeyid": str(secrets.randbelow(2**32)),
            "localAudioPlayMode": "0",
            "mode": f"{width}x{height}x{fps}",
            "uniqueid": self.client_unique_id,
            "clientname": self.client_name,
            "corever": "1",
            "useVdd": "1",
            "hdrMode": "0",
            "sops": "0",
            "gcmap": "0",
            "surroundAudioInfo": "196610",
            "continuousAudio": "0",
            "customScreenMode": "-1",
        }
        root = await self._get("/launch", params=params, timeout_total=_LAUNCH_TIMEOUT)
        gamesession = _text_int(root, "gamesession")
        result = LaunchResult(
            status_code=200,
            gamesession=gamesession,
            session_url=root.findtext("sessionUrl0") or "",
        )
        if gamesession != 1:
            raise SunshineError(200, "Sunshine 没有返回 gamesession=1，应用可能未启动")
        return result

    async def async_cancel(self) -> None:
        await self._get("/cancel", timeout_total=_DEFAULT_TIMEOUT)

    async def async_get_web_sessions(self) -> WebSessions:
        """Read the optional Web UI runtime session list.

        This is deliberately separate from the mTLS control plane: failures
        here only disable the optional "active stream" attributes and guard.
        """

        if not self.web_username or not self.web_password:
            return WebSessions(available=False)

        session = self._get_web_session()
        try:
            async with session.get(
                f"{self._web_base}/api/runtime/sessions",
                timeout=aiohttp.ClientTimeout(total=_DEFAULT_TIMEOUT, sock_connect=10.0),
            ) as response:
                if response.status in (401, 403):
                    raise CannotConnect("Sunshine WebUI 用户名或密码错误")
                if response.status != 200:
                    raise CannotConnect(f"Sunshine WebUI 返回 HTTP {response.status}")
                payload = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, json.JSONDecodeError) as err:
            raise CannotConnect(f"无法读取 Sunshine 会话列表：{err}") from err

        sessions: list[SessionInfo] = []
        for item in payload.get("sessions", []):
            if not isinstance(item, dict):
                continue
            sessions.append(
                SessionInfo(
                    client_name=str(item.get("client_name") or ""),
                    client_uuid=str(item.get("client_uuid") or ""),
                    state=str(item.get("state") or ""),
                    app_name=str(item.get("app_name") or ""),
                    app_id=int(item.get("app_id") or 0),
                    width=int(item.get("width") or 0),
                    height=int(item.get("height") or 0),
                    fps=int(item.get("fps") or 0),
                )
            )

        return WebSessions(
            available=True,
            total_sessions=int(payload.get("total_sessions") or len(sessions)),
            sessions=sessions,
        )
