"""Exceptions raised by the MoonScreen protocol layer."""

from __future__ import annotations


class MoonScreenError(Exception):
    """Base class for all MoonScreen errors."""


class CannotConnect(MoonScreenError):
    """The host could not be reached at all."""


class PairingRequired(MoonScreenError):
    """The client certificate is not (or no longer) accepted by the host."""


class PairingFailed(MoonScreenError):
    """The PIN pairing handshake failed."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 0,
        invalid_pin: bool = False,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.invalid_pin = invalid_pin
        self.retry_after = retry_after


class SunshineError(MoonScreenError):
    """Sunshine answered with a non-200 GameStream status."""

    def __init__(
        self,
        status_code: int,
        message: str,
        *,
        error_code: str = "",
        hint: str = "",
        recoverable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.error_code = error_code
        self.hint = hint
        self.recoverable = recoverable

    def __str__(self) -> str:
        text = f"[{self.status_code}] {self.message}" if self.status_code else self.message
        if self.error_code:
            text += f" ({self.error_code})"
        if self.hint:
            text += f"；{self.hint}"
        return text
