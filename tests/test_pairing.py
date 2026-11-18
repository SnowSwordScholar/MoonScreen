"""Pairing and cryptographic primitive tests."""

from __future__ import annotations

import pytest
from custom_components.moonscreen.moonlight.crypto import (
    aes_ecb_decrypt,
    aes_ecb_encrypt,
    certificate_signature,
    derive_pairing_key,
    generate_client_credentials,
    load_certificate,
    sha256,
)
from custom_components.moonscreen.moonlight.errors import PairingFailed
from custom_components.moonscreen.moonlight.pairing import pair_with_pin

from fake_sunshine import FakeSunshine


def test_aes_ecb_known_vector() -> None:
    # NIST AES-128 ECB test vector (FIPS-197, Appendix C.1).
    key = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    plaintext = bytes.fromhex("00112233445566778899aabbccddeeff")
    ciphertext = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")
    assert aes_ecb_encrypt(key, plaintext) == ciphertext
    assert aes_ecb_decrypt(key, ciphertext) == plaintext


def test_aes_ecb_rejects_partial_blocks() -> None:
    with pytest.raises(ValueError):
        aes_ecb_encrypt(b"0" * 16, b"short block")


def test_pairing_key_is_sha256_prefix() -> None:
    salt = bytes(range(16))
    assert derive_pairing_key(salt, "1234") == sha256(salt + b"1234")[:16]


def test_generated_certificate_is_self_signed() -> None:
    cert_pem, key_pem = generate_client_credentials("MoonScreen Test")
    cert = load_certificate(cert_pem)
    assert cert.subject == cert.issuer
    assert cert.signature
    assert "BEGIN RSA PRIVATE KEY" in key_pem or "BEGIN PRIVATE KEY" in key_pem
    assert certificate_signature(cert_pem) == cert.signature


async def test_pair_with_correct_pin(fake_sunshine: FakeSunshine) -> None:
    client_cert, client_key = generate_client_credentials("MoonScreen Test")
    result = await pair_with_pin(
        host="127.0.0.1",
        http_port=fake_sunshine.http_port,
        https_port=fake_sunshine.https_port,
        client_cert_pem=client_cert,
        client_key_pem=client_key,
        pin=fake_sunshine.pin,
        client_unique_id="pair-success",
        pairing_name="MoonScreen Test",
    )

    assert fake_sunshine.paired
    assert fake_sunshine.client_cert_pem == client_cert
    assert result.server_cert_pem == fake_sunshine.server_cert_pem
    assert result.client_unique_id == "pair-success"


async def test_pair_with_wrong_pin(fake_sunshine: FakeSunshine) -> None:
    fake_sunshine.pin = "9999"
    client_cert, client_key = generate_client_credentials("MoonScreen Test")

    with pytest.raises(PairingFailed):
        await pair_with_pin(
            host="127.0.0.1",
            http_port=fake_sunshine.http_port,
            https_port=fake_sunshine.https_port,
            client_cert_pem=client_cert,
            client_key_pem=client_key,
            pin="1234",
            client_unique_id="pair-wrong-pin",
            pairing_name="MoonScreen Test",
        )

    assert not fake_sunshine.paired


async def test_pair_with_disabled_pairing(fake_sunshine: FakeSunshine) -> None:
    fake_sunshine.fail_pair = True
    client_cert, client_key = generate_client_credentials("MoonScreen Test")

    with pytest.raises(PairingFailed):
        await pair_with_pin(
            host="127.0.0.1",
            http_port=fake_sunshine.http_port,
            https_port=fake_sunshine.https_port,
            client_cert_pem=client_cert,
            client_key_pem=client_key,
            pin=fake_sunshine.pin,
            client_unique_id="pair-disabled",
            pairing_name="MoonScreen Test",
        )
