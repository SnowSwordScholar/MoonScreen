"""Tests for the live-check credential persistence (no host changes)."""

from __future__ import annotations

from custom_components.moonscreen.moonlight.crypto import generate_client_credentials
from custom_components.moonscreen.moonlight.pairing import PairingResult
from tools.live_check import _load_saved_state, _save_state


def test_saved_credentials_round_trip(tmp_path) -> None:
    client_cert, client_key = generate_client_credentials("MoonScreen Live Check Test")
    result = PairingResult(
        client_cert_pem=client_cert,
        client_key_pem=client_key,
        server_cert_pem="-----BEGIN CERTIFICATE-----\nserver\n-----END CERTIFICATE-----\n",
        client_unique_id="test-uuid",
        pairing_name="MoonScreen Live Check Test",
    )
    path = tmp_path / "credentials.json"

    _save_state(path, result)
    loaded = _load_saved_state(path)

    assert loaded == result
    assert "PRIVATE KEY" in path.read_text(encoding="utf-8")


def test_saved_credentials_rejects_garbage(tmp_path) -> None:
    path = tmp_path / "credentials.json"
    path.write_text("{not json", encoding="utf-8")
    assert _load_saved_state(path) is None
