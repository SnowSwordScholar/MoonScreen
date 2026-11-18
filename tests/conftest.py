"""Fixtures for the MoonScreen protocol tests."""

from __future__ import annotations

import pytest_asyncio
from custom_components.moonscreen.moonlight.client import SunshineClient
from custom_components.moonscreen.moonlight.crypto import generate_client_credentials
from custom_components.moonscreen.moonlight.pairing import pair_with_pin

from fake_sunshine import FakeSunshine


@pytest_asyncio.fixture
async def fake_sunshine():
    server = FakeSunshine()
    await server.start()
    try:
        yield server
    finally:
        await server.stop()


@pytest_asyncio.fixture
async def paired_client(fake_sunshine: FakeSunshine):
    client_cert, client_key = generate_client_credentials("MoonScreen Test Client")
    result = await pair_with_pin(
        host="127.0.0.1",
        http_port=fake_sunshine.http_port,
        https_port=fake_sunshine.https_port,
        client_cert_pem=client_cert,
        client_key_pem=client_key,
        pin=fake_sunshine.pin,
        client_unique_id="test-client-uuid",
        pairing_name="MoonScreen Test",
    )
    client = SunshineClient(
        host="127.0.0.1",
        https_port=fake_sunshine.https_port,
        http_port=fake_sunshine.http_port,
        web_port=fake_sunshine.web_port,
        client_cert_pem=result.client_cert_pem,
        client_key_pem=result.client_key_pem,
        server_cert_pem=result.server_cert_pem,
        client_unique_id=result.client_unique_id,
        client_name=result.pairing_name,
        web_username="admin",
        web_password=fake_sunshine.web_password,
    )
    try:
        yield client
    finally:
        await client.close()
