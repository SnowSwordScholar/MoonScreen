"""Small, HA-independent data models."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ServerInfo:
    """Subset of Sunshine's /serverinfo response we care about."""

    unique_id: str = ""
    hostname: str = ""
    app_version: str = ""
    sunshine_version: str = ""
    current_app_id: int = 0
    state: str = ""
    pair_status: int = 0
    vdd_capability_version: int = 0
    display_modes: str = ""

    @property
    def app_running(self) -> bool:
        return self.current_app_id > 0

    @property
    def version_label(self) -> str:
        return self.sunshine_version or self.app_version


@dataclass(slots=True)
class AppInfo:
    """One application from /applist."""

    app_id: int
    title: str


@dataclass(slots=True)
class LaunchResult:
    """Result of GET /launch."""

    status_code: int
    gamesession: int = 0
    message: str = ""
    error_code: str = ""
    hint: str = ""
    session_url: str = ""

    @property
    def accepted(self) -> bool:
        return self.status_code == 200 and self.gamesession == 1


@dataclass(slots=True)
class SessionInfo:
    """One active streaming session from the optional Web UI API."""

    client_name: str = ""
    client_uuid: str = ""
    state: str = ""
    app_name: str = ""
    app_id: int = 0
    width: int = 0
    height: int = 0
    fps: int = 0


@dataclass(slots=True)
class WebSessions:
    """Result of GET /api/runtime/sessions."""

    available: bool = False
    total_sessions: int = 0
    sessions: list[SessionInfo] = field(default_factory=list)

    @property
    def active_clients(self) -> str:
        names = [session.client_name for session in self.sessions if session.client_name]
        return ", ".join(names)
