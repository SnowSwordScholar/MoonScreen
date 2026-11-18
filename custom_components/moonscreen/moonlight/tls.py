"""TLS context helpers.

Sunshine uses a self-signed certificate for both its GameStream HTTPS server
and its Web UI.  We pin that certificate as the only trust anchor.  Hostname
checking is disabled because the certificate is commonly issued for a name
that does not match the LAN IP, but the exact certificate still has to match.
"""

from __future__ import annotations

import os
import ssl
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def _pem_files(*items: tuple[str, str]) -> Iterator[list[str]]:
    """Materialise PEM strings as 0600 temporary files for ssl APIs."""

    with tempfile.TemporaryDirectory(prefix="moonscreen-") as directory:
        paths: list[str] = []
        for index, (content, suffix) in enumerate(items):
            path = os.path.join(directory, f"item-{index}.{suffix}")
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, "w", encoding="ascii") as handle:
                handle.write(content)
            paths.append(path)
        yield paths


def create_server_context(server_cert_pem: str) -> ssl.SSLContext:
    """Context that trusts exactly the pinned Sunshine certificate."""

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_verify_locations(cadata=server_cert_pem)
    return context


def create_mtls_context(
    server_cert_pem: str,
    client_cert_pem: str,
    client_key_pem: str,
) -> ssl.SSLContext:
    """Context with the pinned server certificate and a client certificate."""

    context = create_server_context(server_cert_pem)
    with _pem_files((client_cert_pem, "crt"), (client_key_pem, "key")) as paths:
        context.load_cert_chain(paths[0], paths[1])
    return context


def create_server_ssl_context(cert_pem: str, key_pem: str) -> ssl.SSLContext:
    """Server-side context used by the test double."""

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    with _pem_files((cert_pem, "crt"), (key_pem, "key")) as paths:
        context.load_cert_chain(paths[0], paths[1])
    context.verify_mode = ssl.CERT_NONE
    return context
