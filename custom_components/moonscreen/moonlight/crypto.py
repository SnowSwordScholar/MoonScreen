"""Cryptographic primitives used by Moonlight's PIN pairing.

Moonlight (and Sunshine) use:

* a 2048-bit RSA client certificate;
* an AES-128-ECB key derived from SHA-256(salt || pin), first 16 bytes;
* AES-ECB *without* padding (all pairing payloads are block aligned);
* SHA-256 hashes;
* RSA PKCS#1 v1.5 signatures with SHA-256.
"""

from __future__ import annotations

import hashlib
import ipaddress
import re
from datetime import UTC, datetime, timedelta

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.x509.oid import NameOID

AES_BLOCK_SIZE = 16
_DNS_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def _is_dns_name(value: str) -> bool:
    if not value or len(value) > 253:
        return False
    labels = value.rstrip(".").split(".")
    return all(_DNS_LABEL.match(label) for label in labels)


def _is_ip_address(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def generate_client_credentials(
    common_name: str,
    *,
    key_bits: int = 2048,
    valid_days: int = 7300,
) -> tuple[str, str]:
    """Create a self-signed RSA certificate and private key (PEM).

    Returns ``(certificate_pem, private_key_pem)``.
    """

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=key_bits)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.now(UTC)

    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=valid_days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=False)
    )
    # Sunshine adds a SAN for DNS names too; keep our certificate equally valid
    # if it is ever used with hostname checking.
    if _is_dns_name(common_name):
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(common_name)]),
            critical=False,
        )
    elif _is_ip_address(common_name):
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(common_name))]),
            critical=False,
        )

    certificate = builder.sign(private_key, hashes.SHA256())

    cert_pem = certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")
    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    return cert_pem, key_pem


def load_certificate(cert_pem: str | bytes) -> x509.Certificate:
    """Parse a PEM certificate."""

    data = cert_pem.encode("ascii") if isinstance(cert_pem, str) else cert_pem
    return x509.load_pem_x509_certificate(data)


def certificate_signature(cert_pem: str | bytes) -> bytes:
    """Return the raw X.509 signature bytes (what Moonlight hashes)."""

    return load_certificate(cert_pem).signature


def certificate_fingerprint(cert_pem: str | bytes) -> str:
    """SHA-256 fingerprint, lowercase hex, colon separated."""

    digest = load_certificate(cert_pem).fingerprint(hashes.SHA256())
    return ":".join(f"{byte:02x}" for byte in digest)


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def derive_pairing_key(salt: bytes, pin: str) -> bytes:
    """AES key = SHA-256(salt || pin)[:16]."""

    return hashlib.sha256(salt + pin.encode("utf-8")).digest()[:AES_BLOCK_SIZE]


def _aes_ecb(key: bytes, data: bytes, *, encrypt: bool) -> bytes:
    if len(key) != AES_BLOCK_SIZE:
        raise ValueError("AES-128 key must be 16 bytes")
    if len(data) == 0 or len(data) % AES_BLOCK_SIZE != 0:
        raise ValueError("AES-ECB payload must be a non-empty multiple of 16 bytes")
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    context = cipher.encryptor() if encrypt else cipher.decryptor()
    return context.update(data) + context.finalize()


def aes_ecb_encrypt(key: bytes, plaintext: bytes) -> bytes:
    return _aes_ecb(key, plaintext, encrypt=True)


def aes_ecb_decrypt(key: bytes, ciphertext: bytes) -> bytes:
    return _aes_ecb(key, ciphertext, encrypt=False)


def rsa_sign_sha256(private_key_pem: str | bytes, data: bytes) -> bytes:
    """RSA PKCS#1 v1.5 signature with SHA-256."""

    key_data = private_key_pem.encode("ascii") if isinstance(private_key_pem, str) else private_key_pem
    private_key = serialization.load_pem_private_key(key_data, password=None)
    if not isinstance(private_key, rsa.RSAPrivateKey):
        raise ValueError("Unsupported private key type")
    return private_key.sign(data, padding.PKCS1v15(), hashes.SHA256())


def rsa_verify_sha256(cert_pem: str | bytes, data: bytes, signature: bytes) -> bool:
    """Verify an RSA PKCS#1 v1.5 SHA-256 signature with a certificate."""

    public_key = load_certificate(cert_pem).public_key()
    if not isinstance(public_key, rsa.RSAPublicKey):
        return False
    try:
        public_key.verify(signature, data, padding.PKCS1v15(), hashes.SHA256())
    except (InvalidSignature, ValueError):
        return False
    return True
