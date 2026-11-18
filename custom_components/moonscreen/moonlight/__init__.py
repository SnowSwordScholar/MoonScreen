"""Minimal Moonlight GameStream control-plane client.

No video, audio, RTSP or ENET data plane is implemented.  The only purpose of
this package is to perform Moonlight pairing, launch an application on
Foundation Sunshine and ask the host to quit it again.
"""

from __future__ import annotations

from .client import SunshineClient
from .errors import (
    CannotConnect,
    MoonScreenError,
    PairingFailed,
    PairingRequired,
    SunshineError,
)
from .models import AppInfo, LaunchResult, ServerInfo, SessionInfo, WebSessions
from .pairing import PairingResult, pair_with_pin

__all__ = [
    "AppInfo",
    "CannotConnect",
    "LaunchResult",
    "MoonScreenError",
    "PairingFailed",
    "PairingRequired",
    "PairingResult",
    "ServerInfo",
    "SessionInfo",
    "SunshineClient",
    "SunshineError",
    "WebSessions",
    "pair_with_pin",
]
