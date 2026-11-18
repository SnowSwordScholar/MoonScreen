"""Pure logic tests (no Home Assistant imports)."""

from __future__ import annotations

import pytest
from custom_components.moonscreen.logic import (
    InvalidOption,
    app_label,
    build_mode,
    screen_is_on_from_app_id,
    should_block_cancel,
    validate_poll_interval,
)


def test_screen_state_mapping() -> None:
    assert screen_is_on_from_app_id(0) is True
    assert screen_is_on_from_app_id(1) is False
    assert screen_is_on_from_app_id(42) is False


def test_app_label() -> None:
    assert app_label(0, {}) == ""
    assert app_label(1, {1: "Desktop"}) == "Desktop"
    assert app_label(9, {}) == "应用 #9"


def test_build_mode() -> None:
    assert build_mode(1920, 1080, 60) == "1920x1080x60"
    assert build_mode(2202, 1179, 120) == "2202x1179x120"


@pytest.mark.parametrize(
    ("width", "height", "fps"),
    [(1, 1080, 60), (1920, 99999, 60), (1920, 1080, 1), (1920, 1080, 500)],
)
def test_build_mode_rejects_out_of_range(width: int, height: int, fps: int) -> None:
    with pytest.raises(InvalidOption):
        build_mode(width, height, fps)


def test_poll_interval_range() -> None:
    assert validate_poll_interval(15) == 15
    with pytest.raises(InvalidOption):
        validate_poll_interval(1)
    with pytest.raises(InvalidOption):
        validate_poll_interval(999)


def test_cancel_protection() -> None:
    assert should_block_cancel(protect_active_stream=True, active_sessions=1)
    assert not should_block_cancel(protect_active_stream=False, active_sessions=1)
    assert not should_block_cancel(protect_active_stream=True, active_sessions=0)
