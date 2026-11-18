"""An aiohttp test double for the parts of Sunshine MoonScreen uses.

It implements the same four pairing phases as Sunshine's
``src/nvhttp/pairing.cpp`` and enough of ``/serverinfo``, ``/applist``,
``/launch``, ``/cancel`` and the Web UI session list to exercise the client
end to end.  It deliberately runs over plain HTTP for pairing and HTTPS for
the control plane, like the real host.
"""

from __future__ import annotations

import asyncio
import base64
import socket
import xml.etree.ElementTree as ET
from typing import Any

from aiohttp import web
from custom_components.moonscreen.moonlight.crypto import (
    aes_ecb_decrypt,
    aes_ecb_encrypt,
    certificate_signature,
    derive_pairing_key,
    generate_client_credentials,
    rsa_sign_sha256,
    rsa_verify_sha256,
    sha256,
)
from custom_components.moonscreen.moonlight.tls import create_server_ssl_context


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _xml_response(inner: str = "", *, status: int = 200, message: str = "") -> web.Response:
    attributes = f'status_code="{status}"'
    if message:
        attributes += f' status_message="{message}"'
    return web.Response(
        text=f'<?xml version="1.0" encoding="utf-8"?><root {attributes}>{inner}</root>',
        content_type="application/xml",
    )


def _error(status: int, message: str) -> web.Response:
    return _xml_response(status=status, message=message)


class FakeSunshine:
    """Stateful fake host."""

    def __init__(self, pin: str = "1234", *, web_password: str = "secret") -> None:
        self.pin = pin
        self.web_password = web_password
        self.server_cert_pem, self.server_key_pem = generate_client_credentials("Fake Sunshine")
        self.client_cert_pem = ""
        self.salt = b""
        self.key = b""
        self.server_secret = b""
        self.server_challenge = b""
        self.client_hash = b""
        self.paired = False
        self.app_state = 0
        self.mode = ""
        self.launch_params: dict[str, str] = {}
        self.vdd_error = False
        self.fail_pair = False

        self._runners: list[web.AppRunner] = []
        self.http_port = 0
        self.https_port = 0
        self.web_port = 0

    # ------------------------------------------------------------------ lifecycle

    async def start(self) -> None:
        self.http_port = _free_port()
        self.https_port = _free_port()
        self.web_port = _free_port()

        http_app = web.Application()
        http_app.router.add_get("/serverinfo", self._handle_serverinfo)
        http_app.router.add_get("/pair", self._handle_pair)
        http_app.router.add_get("/applist", self._handle_applist)

        https_app = web.Application()
        https_app.router.add_get("/serverinfo", self._handle_serverinfo)
        https_app.router.add_get("/pair", self._handle_pair)
        https_app.router.add_get("/applist", self._handle_applist)
        https_app.router.add_get("/launch", self._handle_launch)
        https_app.router.add_get("/cancel", self._handle_cancel)

        web_app = web.Application()
        web_app.router.add_get("/api/runtime/sessions", self._handle_web_sessions)

        await self._start_runner(http_app, self.http_port, ssl_context=None)
        await self._start_runner(
            https_app,
            self.https_port,
            ssl_context=create_server_ssl_context(self.server_cert_pem, self.server_key_pem),
        )
        await self._start_runner(
            web_app,
            self.web_port,
            ssl_context=create_server_ssl_context(self.server_cert_pem, self.server_key_pem),
        )

    async def _start_runner(
        self,
        app: web.Application,
        port: int,
        *,
        ssl_context: Any,
    ) -> None:
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", port, ssl_context=ssl_context)
        await site.start()
        self._runners.append(runner)

    async def stop(self) -> None:
        await asyncio.gather(*(runner.cleanup() for runner in self._runners), return_exceptions=True)
        self._runners.clear()

    async def __aenter__(self) -> FakeSunshine:
        await self.start()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.stop()

    # ------------------------------------------------------------------ handlers

    async def _handle_serverinfo(self, request: web.Request) -> web.Response:
        state = "SUNSHINE_SERVER_BUSY" if self.app_state else "SUNSHINE_SERVER_FREE"
        pair_status = 1 if self.paired else 0
        return _xml_response(
            inner=(
                "<hostname>Fake PC</hostname>"
                "<appversion>7.1.431.-1</appversion>"
                "<SunshineVersion>Foundation Sunshine test</SunshineVersion>"
                "<uniqueid>fake-server-uuid</uniqueid>"
                f"<PairStatus>{pair_status}</PairStatus>"
                f"<currentgame>{self.app_state}</currentgame>"
                f"<state>{state}</state>"
                "<VddCapabilityVersion>1</VddCapabilityVersion>"
                "<FsDisplayModes>1920x1080x60,2560x1440x60</FsDisplayModes>"
            )
        )

    async def _handle_applist(self, _request: web.Request) -> web.Response:
        return _xml_response(
            inner=(
                "<App><AppTitle>Desktop</AppTitle><ID>1</ID></App>"
                "<App><AppTitle>Steam Big Picture</AppTitle><ID>2</ID></App>"
            )
        )

    async def _handle_pair(self, request: web.Request) -> web.Response:
        if self.fail_pair:
            return _error(500, "Pairing disabled for this test")
        params = request.query
        phrase = params.get("phrase", "")
        if phrase == "getservercert":
            return self._pair_getservercert(params)
        if phrase == "pairchallenge":
            return _xml_response("<paired>1</paired>")
        if "clientchallenge" in params:
            return self._pair_clientchallenge(params)
        if "serverchallengeresp" in params:
            return self._pair_serverchallengeresp(params)
        if "clientpairingsecret" in params:
            return self._pair_clientpairingsecret(params)
        return _error(404, "Invalid pairing request")

    def _pair_getservercert(self, params: Any) -> web.Response:
        client_cert_hex = params.get("clientcert", "")
        try:
            self.client_cert_pem = bytes.fromhex(client_cert_hex).decode("ascii")
        except (ValueError, UnicodeDecodeError):
            return _error(400, "Invalid client certificate")
        self.salt = bytes.fromhex(params.get("salt", ""))
        if len(self.salt) < 16:
            return _error(400, "Salt too short")
        self.key = derive_pairing_key(self.salt, self.pin)
        return _xml_response(
            "<paired>1</paired>"
            "<pairname>MoonScreen</pairname>"
            f"<plaincert>{self.server_cert_pem.encode('ascii').hex()}</plaincert>"
        )

    def _pair_clientchallenge(self, params: Any) -> web.Response:
        if not self.key:
            return _error(400, "Cipher key not set")
        try:
            challenge = aes_ecb_decrypt(self.key, bytes.fromhex(params["clientchallenge"]))
        except (ValueError, KeyError):
            return _error(400, "Invalid client challenge")
        if len(challenge) != 16:
            return _error(400, "Invalid client challenge length")

        self.server_secret = _random(16)
        self.server_challenge = _random(16)
        digest = sha256(challenge + certificate_signature(self.server_cert_pem) + self.server_secret)
        payload = aes_ecb_encrypt(self.key, digest + self.server_challenge)
        return _xml_response(f"<paired>1</paired><challengeresponse>{payload.hex()}</challengeresponse>")

    def _pair_serverchallengeresp(self, params: Any) -> web.Response:
        if not self.key or not self.server_secret:
            return _error(400, "Cipher key or server secret not set")
        try:
            self.client_hash = aes_ecb_decrypt(self.key, bytes.fromhex(params["serverchallengeresp"]))
        except (ValueError, KeyError):
            return _error(400, "Invalid client hash")
        signature = rsa_sign_sha256(self.server_key_pem, self.server_secret)
        return _xml_response(
            f"<paired>1</paired><pairingsecret>{(self.server_secret + signature).hex()}</pairingsecret>"
        )

    def _pair_clientpairingsecret(self, params: Any) -> web.Response:
        if not self.server_challenge or not self.client_cert_pem:
            return _error(400, "Out of order pairing request")
        try:
            payload = bytes.fromhex(params["clientpairingsecret"])
        except (ValueError, KeyError):
            return _error(400, "Invalid client pairing secret")
        if len(payload) <= 16:
            return _error(400, "Client pairing secret too short")
        secret, signature = payload[:16], payload[16:]
        expected = sha256(self.server_challenge + certificate_signature(self.client_cert_pem) + secret)
        signature_ok = rsa_verify_sha256(self.client_cert_pem, secret, signature)
        if expected == self.client_hash and signature_ok:
            self.paired = True
            return _xml_response("<paired>1</paired>")
        return _xml_response("<paired>0</paired>")

    async def _handle_launch(self, request: web.Request) -> web.Response:
        params = request.query
        for required in ("appid", "rikey", "rikeyid", "localAudioPlayMode", "mode"):
            if required not in params:
                return _error(400, f"Missing required launch parameter: {required}")
        if self.vdd_error:
            return _xml_response(
                status=503,
                message="The virtual display driver is not installed.",
                inner=(
                    "<sunshine_error_code>VDD_DRIVER_MISSING</sunshine_error_code>"
                    "<sunshine_error_hint>Install ZakoVDD and retry.</sunshine_error_hint>"
                    "<sunshine_recoverable>1</sunshine_recoverable>"
                ),
            )
        if self.app_state:
            return _error(400, "An app is already running on this host")
        self.app_state = int(params["appid"])
        self.mode = params["mode"]
        self.launch_params = dict(params)
        return _xml_response("<gamesession>1</gamesession><sessionUrl0>rtsp://fake:48010</sessionUrl0>")

    async def _handle_cancel(self, _request: web.Request) -> web.Response:
        self.app_state = 0
        return _xml_response("<cancel>1</cancel>")

    async def _handle_web_sessions(self, request: web.Request) -> web.Response:
        expected = "Basic " + base64.b64encode(f"admin:{self.web_password}".encode()).decode()
        if request.headers.get("Authorization") != expected:
            return web.Response(status=401, text="unauthorized")
        sessions = []
        if self.app_state:
            sessions.append(
                {
                    "client_name": "Fake Moonlight",
                    "client_uuid": "fake-client",
                    "state": "RUNNING",
                    "app_name": "Desktop",
                    "app_id": self.app_state,
                    "width": 1920,
                    "height": 1080,
                    "fps": 60,
                }
            )
        return web.json_response(
            {
                "success": True,
                "total_sessions": len(sessions),
                "sessions": sessions,
            }
        )


def _random(length: int) -> bytes:
    import os

    return os.urandom(length)


def parse_root(text: str) -> ET.Element:
    return ET.fromstring(text)
