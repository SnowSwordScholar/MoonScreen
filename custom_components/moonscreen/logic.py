"""Pure helpers shared by the integration and its tests (no Home Assistant imports)."""

from __future__ import annotations

from .const import MAX_DIMENSION, MAX_FPS, MAX_POLL_INTERVAL, MIN_DIMENSION, MIN_FPS, MIN_POLL_INTERVAL


class InvalidOption(ValueError):
    """A user supplied option is out of range."""


def build_mode(width: int, height: int, fps: int) -> str:
    """Moonlight's ``mode`` query value."""

    if not (MIN_DIMENSION <= width <= MAX_DIMENSION):
        raise InvalidOption(f"宽度必须在 {MIN_DIMENSION}–{MAX_DIMENSION} 之间")
    if not (MIN_DIMENSION <= height <= MAX_DIMENSION):
        raise InvalidOption(f"高度必须在 {MIN_DIMENSION}–{MAX_DIMENSION} 之间")
    if not (MIN_FPS <= fps <= MAX_FPS):
        raise InvalidOption(f"帧率必须在 {MIN_FPS}–{MAX_FPS} 之间")
    return f"{width}x{height}x{fps}"


def validate_poll_interval(seconds: int) -> int:
    if not (MIN_POLL_INTERVAL <= seconds <= MAX_POLL_INTERVAL):
        raise InvalidOption(f"轮询间隔必须在 {MIN_POLL_INTERVAL}–{MAX_POLL_INTERVAL} 秒之间")
    return seconds


def screen_is_on_from_app_id(app_id: int) -> bool:
    """MoonScreen's state model: any running host app means the screen is off."""

    return app_id <= 0


def app_label(app_id: int, names: dict[int, str]) -> str:
    if app_id <= 0:
        return ""
    return names.get(app_id) or f"应用 #{app_id}"


def should_block_cancel(*, protect_active_stream: bool, active_sessions: int) -> bool:
    return protect_active_stream and active_sessions > 0
