"""Moonlight PIN pairing against Sunshine / Foundation Sunshine.

The wire protocol is the one implemented by Moonlight's ``NvPairingManager``
and by ``src/nvhttp/pairing.cpp`` in Sunshine.  Pairing is done over plain
HTTP because the encrypted challenge itself authenticates the PIN; all later
traffic uses mutual TLS with the certificate that is registered here.
"""

from __future__ import annotations

import asyncio
import os
import ssl
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import aiohttp

from .crypto import (
    aes_ecb_decrypt,
    aes_ecb_encrypt,
    certificate_signature,
    derive_pairing_key,
    rsa_sign_sha256,
    rsa_verify_sha256,
    sha256,
)
from .errors import PairingFailed
from .tls import create_mtls_context


@dataclass(slots=True)
class PairingResult:
    """Credentials and the pinned host certificate after a successful pairing."""

    client_cert_pem: str
    client_key_pem: str
    server_cert_pem: str
    client_unique_id: str
    pairing_name: str


def format_host(host: str) -> str:
    """Bracket IPv6 literals for URL construction."""

    host = host.strip()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if ":" in host:
        return f"[{host}]"
    return host


def _xml_root(text: str) -> ET.Element:
    try:
        return ET.fromstring(text)
    except ET.ParseError as err:
        raise PairingFailed(f"Sunshine 返回了无法解析的 XML：{text[:160]!r}") from err


def _status(root: ET.Element) -> int:
    try:
        return int(root.attrib.get("status_code", "200"))
    except ValueError:
        return 0


def _message(root: ET.Element) -> str:
    return root.attrib.get("status_message") or "Sunshine 拒绝了配对请求"


def _check_pair_response(root: ET.Element) -> None:
    status = _status(root)
    if status != 200:
        raise PairingFailed(_message(root), status_code=status)
    if root.findtext("paired") != "1":
        raise PairingFailed("Sunshine 未确认配对成功", status_code=status)


async def _pair_request(
    session: aiohttp.ClientSession,
    base_url: str,
    params: dict[str, str],
) -> ET.Element:
    async with session.get(f"{base_url}/pair", params=params) as response:
        text = await response.text()
        if response.status in (401, 403):
            raise PairingFailed("Sunshine 拒绝了配对请求（401/403）", status_code=response.status)
        if response.status == 429:
            retry_after = response.headers.get("Retry-After")
            raise PairingFailed(
                "Sunshine 的配对请求被限流，请稍后再试",
                status_code=429,
                retry_after=int(retry_after) if retry_after and retry_after.isdigit() else None,
            )
        if response.status >= 400:
            raise PairingFailed(f"Sunshine 返回 HTTP {response.status}：{text[:160]}", status_code=response.status)
    root = _xml_root(text)
    _check_pair_response(root)
    return root


def _hex_text(root: ET.Element, tag: str) -> bytes:
    value = root.findtext(tag)
    if not value:
        raise PairingFailed(f"Sunshine 的响应缺少 {tag}")
    try:
        return bytes.fromhex(value)
    except ValueError as err:
        raise PairingFailed(f"Sunshine 的 {tag} 不是合法 hex") from err


async def pair_with_pin(
    *,
    host: str,
    http_port: int,
    https_port: int,
    client_cert_pem: str,
    client_key_pem: str,
    pin: str,
    client_unique_id: str,
    pairing_name: str = "MoonScreen",
    request_timeout: float = 300.0,
) -> PairingResult:
    """Run the four pairing phases and verify mutual TLS.

    ``pin`` must be shown to the user before this coroutine is awaited: the
    first request blocks on the host until somebody enters the PIN in
    Sunshine's Web UI.
    """

    if len(pin) != 4 or not pin.isdigit():
        raise ValueError("PIN must be exactly four digits")

    host_part = format_host(host)
    http_base = f"http://{host_part}:{http_port}"
    https_base = f"https://{host_part}:{https_port}"

    timeout = aiohttp.ClientTimeout(
        total=request_timeout,
        sock_connect=10.0,
        sock_read=request_timeout,
    )

    salt = os.urandom(16)
    key = derive_pairing_key(salt, pin)
    client_challenge = os.urandom(16)
    client_secret = os.urandom(16)

    try:
        async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
            # Phase 1: hand over salt + client certificate, then wait for the
            # operator to enter the PIN.  The response only arrives afterwards.
            root = await _pair_request(
                session,
                http_base,
                {
                    "uniqueid": client_unique_id,
                    "phrase": "getservercert",
                    "salt": salt.hex(),
                    "clientcert": client_cert_pem.encode("ascii").hex(),
                    "clientname": pairing_name,
                    "devicename": pairing_name,
                    "updateState": "1",
                },
            )
            plaincert = _hex_text(root, "plaincert")
            try:
                server_cert_pem = plaincert.decode("ascii")
            except UnicodeDecodeError:
                server_cert_pem = plaincert.decode("utf-8", errors="replace")
            if "BEGIN CERTIFICATE" not in server_cert_pem:
                raise PairingFailed("Sunshine 返回的 plaincert 不是 PEM 证书")

            # Phase 2: client challenge, encrypted with the PIN-derived key.
            challenge_cipher = aes_ecb_encrypt(key, client_challenge)
            root = await _pair_request(
                session,
                http_base,
                {
                    "uniqueid": client_unique_id,
                    "clientchallenge": challenge_cipher.hex(),
                    "devicename": pairing_name,
                    "updateState": "1",
                },
            )
            challenge_response = aes_ecb_decrypt(key, _hex_text(root, "challengeresponse"))
            if len(challenge_response) < 48:
                raise PairingFailed(
                    "Sunshine 的 challengeresponse 长度不正确（PIN 可能错误）",
                    invalid_pin=True,
                )
            server_hash = challenge_response[:32]
            server_challenge = challenge_response[32:48]

            # Phase 3: prove knowledge of the client secret, then verify the
            # server's signature and the PIN-derived hash.
            client_hash = sha256(server_challenge + certificate_signature(client_cert_pem) + client_secret)
            response_cipher = aes_ecb_encrypt(key, client_hash)
            root = await _pair_request(
                session,
                http_base,
                {
                    "uniqueid": client_unique_id,
                    "serverchallengeresp": response_cipher.hex(),
                    "devicename": pairing_name,
                    "updateState": "1",
                },
            )
            pairing_secret = _hex_text(root, "pairingsecret")
            if len(pairing_secret) <= 16:
                raise PairingFailed("Sunshine 的 pairingsecret 长度不正确")
            server_secret = pairing_secret[:16]
            server_signature = pairing_secret[16:]
            if not rsa_verify_sha256(server_cert_pem, server_secret, server_signature):
                raise PairingFailed("服务端证书签名校验失败（可能被中间人篡改）")

            expected = sha256(client_challenge + certificate_signature(server_cert_pem) + server_secret)
            if expected != server_hash:
                raise PairingFailed("PIN 错误", invalid_pin=True)

            # Phase 4: send our secret and its signature.
            client_signature = rsa_sign_sha256(client_key_pem, client_secret)
            root = await _pair_request(
                session,
                http_base,
                {
                    "uniqueid": client_unique_id,
                    "clientpairingsecret": (client_secret + client_signature).hex(),
                    "devicename": pairing_name,
                    "updateState": "1",
                },
            )
            _check_pair_response(root)
    except aiohttp.ClientConnectorError as err:
        raise PairingFailed(f"无法连接 Sunshine：{err}") from err
    except TimeoutError as err:
        raise PairingFailed("配对请求超时；请确认已在 Sunshine 的 PIN 页面输入 PIN") from err

    # Phase 5: the client certificate must now be accepted by the HTTPS
    # server.  This also validates that the pinned certificate is the one the
    # HTTPS listener actually uses.
    context = create_mtls_context(server_cert_pem, client_cert_pem, client_key_pem)
    https_timeout = aiohttp.ClientTimeout(total=30.0, sock_connect=10.0)
    try:
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=context),
            timeout=https_timeout,
            trust_env=False,
        ) as session:
            async with session.get(
                f"{https_base}/pair",
                params={"uniqueid": client_unique_id, "phrase": "pairchallenge", "updateState": "1"},
            ) as response:
                text = await response.text()
                if response.status != 200:
                    raise PairingFailed(
                        f"配对后的 HTTPS 校验失败（HTTP {response.status}）",
                        status_code=response.status,
                    )
                root = _xml_root(text)
                _check_pair_response(root)
    except (ssl.SSLError, aiohttp.ClientSSLError) as err:
        raise PairingFailed(
            "配对后的 HTTPS 证书校验失败；Python 无法把 Sunshine 的自签证书当作信任锚，请把完整错误反馈给开发者",
        ) from err
    except aiohttp.ClientConnectorError as err:
        raise PairingFailed(f"配对成功但无法连接 HTTPS 端口：{err}") from err

    return PairingResult(
        client_cert_pem=client_cert_pem,
        client_key_pem=client_key_pem,
        server_cert_pem=server_cert_pem,
        client_unique_id=client_unique_id,
        pairing_name=pairing_name,
    )


async def sleep_until_request_started(delay: float = 1.0) -> None:
    """Give the blocking getservercert request a moment to reach Sunshine.

    The host does not answer phase 1 until the PIN is entered, so there is no
    response we can wait for.  A short delay is the pragmatic way to make sure
    the pending request is visible in the Web UI before the PIN is shown.
    """

    await asyncio.sleep(delay)
