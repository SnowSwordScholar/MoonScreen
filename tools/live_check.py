#!/usr/bin/env python3
"""Manual live check against a real Foundation Sunshine host.

This script changes the host state: it pairs a test client, starts Desktop
(which turns the physical screen off) and later quits it again.  It refuses to
run without ``--yes`` and is intentionally not part of the automated tests.

The first run saves the test client certificate to
``tools/.live-check/credentials.json`` (gitignored, contains a private key).
Later runs reuse it, so they do not ask for a PIN again.

Usage:
    python tools/live_check.py --host 192.168.1.50 --dry-run
    python tools/live_check.py --host 192.168.1.50 --yes
    python tools/live_check.py --host 192.168.1.50 --yes --no-prompt --pin 1357
    python tools/live_check.py --host 192.168.1.50 --yes --force-pair
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import secrets
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from custom_components.moonscreen.moonlight import (  # noqa: E402
    CannotConnect,
    PairingFailed,
    PairingRequired,
    PairingResult,
    SunshineClient,
    SunshineError,
)
from custom_components.moonscreen.moonlight.crypto import generate_client_credentials  # noqa: E402
from custom_components.moonscreen.moonlight.pairing import format_host, pair_with_pin  # noqa: E402

DEFAULT_STATE_FILE = PROJECT_ROOT / "tools" / ".live-check" / "credentials.json"
STATE_VERSION = 1


def _load_saved_state(path: Path) -> PairingResult | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version") != STATE_VERSION:
            return None
        result = PairingResult(
            client_cert_pem=payload["client_cert_pem"],
            client_key_pem=payload["client_key_pem"],
            server_cert_pem=payload["server_cert_pem"],
            client_unique_id=payload["client_unique_id"],
            pairing_name=payload.get("pairing_name", "MoonScreen Live Check"),
        )
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if "BEGIN CERTIFICATE" not in result.client_cert_pem or "PRIVATE KEY" not in result.client_key_pem:
        return None
    return result


def _save_state(path: Path, result: PairingResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": STATE_VERSION,
        "client_cert_pem": result.client_cert_pem,
        "client_key_pem": result.client_key_pem,
        "server_cert_pem": result.server_cert_pem,
        "client_unique_id": result.client_unique_id,
        "pairing_name": result.pairing_name,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)
    print(f"Saved test client to {path} (gitignored; contains a private key).", flush=True)


def _make_client(result: PairingResult, args: argparse.Namespace) -> SunshineClient:
    return SunshineClient(
        host=args.host,
        https_port=args.https_port,
        http_port=args.http_port,
        web_port=args.web_port,
        client_cert_pem=result.client_cert_pem,
        client_key_pem=result.client_key_pem,
        server_cert_pem=result.server_cert_pem,
        client_unique_id=result.client_unique_id,
        client_name=result.pairing_name,
    )


async def _http_serverinfo(host: str, port: int) -> None:
    import aiohttp

    url = f"http://{format_host(host)}:{port}/serverinfo"
    timeout = aiohttp.ClientTimeout(total=10.0, sock_connect=5.0)
    async with aiohttp.ClientSession(timeout=timeout, trust_env=False) as session:
        async with session.get(url, params={"uniqueid": "moonscreen-live-check"}) as response:
            text = await response.text()
            print(f"HTTP {response.status} {url}")
            print(text[:2000])


async def _pair(args: argparse.Namespace) -> PairingResult | None:
    pin = args.pin or f"{secrets.randbelow(10000):04d}"
    client_cert, client_key = await asyncio.to_thread(generate_client_credentials, "MoonScreen Live Check")
    unique_id = str(uuid.uuid4())

    print(f"Pairing as MoonScreen Live Check (PIN {pin}).", flush=True)
    print(
        f"Open https://{args.host}:{args.web_port}/pin and enter the PIN, then press Enter here.",
        flush=True,
    )
    pairing_task = asyncio.create_task(
        pair_with_pin(
            host=args.host,
            http_port=args.http_port,
            https_port=args.https_port,
            client_cert_pem=client_cert,
            client_key_pem=client_key,
            pin=pin,
            client_unique_id=unique_id,
            pairing_name="MoonScreen Live Check",
        )
    )
    await asyncio.sleep(1.5)
    if not args.no_prompt:
        await asyncio.to_thread(input, "Press Enter after entering the PIN in Sunshine... ")

    try:
        result = await pairing_task
    except (PairingFailed, CannotConnect) as err:
        print(f"Pairing failed: {err}", file=sys.stderr)
        return None
    _save_state(Path(args.state_file), result)
    return result


async def _main(args: argparse.Namespace) -> int:
    if args.dry_run:
        await _http_serverinfo(args.host, args.http_port)
        return 0

    if not args.yes:
        print("Refusing to change host state without --yes.", file=sys.stderr)
        print("This will pair a test client and turn the physical screen off for a while.", file=sys.stderr)
        return 2

    state_path = Path(args.state_file)
    result: PairingResult | None = None
    if not args.force_pair:
        result = _load_saved_state(state_path)
        if result is not None:
            print(f"Reusing saved test client from {state_path}.", flush=True)
            probe = _make_client(result, args)
            try:
                info = await probe.async_get_serverinfo()
                print(f"Saved client is accepted by {info.hostname!r}. No PIN needed.", flush=True)
            except PairingRequired:
                print("Saved client is no longer paired; pairing again.", flush=True)
                result = None
            except (CannotConnect, SunshineError) as err:
                print(f"Saved client check failed: {err}", file=sys.stderr)
                result = None
            finally:
                await probe.close()

    if result is None:
        result = await _pair(args)
        if result is None:
            return 1

    client = _make_client(result, args)
    try:
        server = await client.async_get_serverinfo()
        print(f"Paired with {server.hostname!r} ({server.version_label}), currentgame={server.current_app_id}")
        apps = await client.async_get_applist()
        print("Apps:", ", ".join(f"{app.app_id}={app.title}" for app in apps) or "(none)")
        desktop = next((app for app in apps if app.title.casefold() == args.app_name.casefold()), None)
        if desktop is None:
            print(f"Desktop app {args.app_name!r} not found", file=sys.stderr)
            return 1
        if server.current_app_id and server.current_app_id != desktop.app_id:
            print(
                f"Another app is already running (ID {server.current_app_id}). "
                "Exit that session first; the test refuses to cancel somebody else's stream.",
                file=sys.stderr,
            )
            return 1
        if server.current_app_id == desktop.app_id:
            print(
                "Desktop is already running (possibly a real Moonlight session). "
                "The test will not cancel it; please exit it and re-run.",
                file=sys.stderr,
            )
            return 1

        print(f"Launching {desktop.title} at {args.width}x{args.height}@{args.fps} ...")
        await client.async_launch(
            app_id=desktop.app_id,
            width=args.width,
            height=args.height,
            fps=args.fps,
        )
        print("Launch accepted. The physical screen should go off now.")
        print(f"Waiting {args.wait}s to verify the launch survives Sunshine's RTSP ticket timeout...")
        await asyncio.sleep(args.wait)
        state = await client.async_get_serverinfo()
        print(f"After {args.wait}s: currentgame={state.current_app_id}, state={state.state}")
        if state.current_app_id != desktop.app_id:
            print(
                "FAIL: Desktop is no longer running. The no-RTSP launch did not persist; "
                "see docs/protocol.md for the fallback options.",
                file=sys.stderr,
            )
            return 1
        print("PASS: Desktop is still running without an RTSP/video session.")

        if args.keep:
            print("--keep given; leaving the screen off. Use Sunshine WebUI to quit Desktop when done.")
            return 0

        print("Cancelling Desktop and restoring the display ...")
        await client.async_cancel()
        for _ in range(20):
            await asyncio.sleep(1)
            state = await client.async_get_serverinfo()
            if state.current_app_id == 0:
                break
        print(f"Final state: currentgame={state.current_app_id}, state={state.state}")
        if state.current_app_id != 0:
            print("FAIL: Desktop is still running after /cancel.", file=sys.stderr)
            return 1
        print("PASS: /cancel stopped Desktop and Sunshine restored the display.")
        return 0
    except (CannotConnect, SunshineError, PairingFailed) as err:
        print(f"Error: {err}", file=sys.stderr)
        return 1
    finally:
        await client.close()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MoonScreen live check")
    parser.add_argument("--host", required=True, help="Sunshine host (LAN IP or hostname)")
    parser.add_argument("--http-port", type=int, default=47989)
    parser.add_argument("--https-port", type=int, default=47984)
    parser.add_argument("--web-port", type=int, default=47990)
    parser.add_argument("--app-name", default="Desktop")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--wait", type=int, default=60, help="Seconds to wait past the RTSP ticket timeout")
    parser.add_argument("--pin", help="Use a specific 4-digit PIN instead of a random one")
    parser.add_argument(
        "--state-file",
        default=str(DEFAULT_STATE_FILE),
        help="Where to save/reuse the test client credentials (gitignored)",
    )
    parser.add_argument("--force-pair", action="store_true", help="Ignore saved credentials and pair again")
    parser.add_argument("--keep", action="store_true", help="Leave Desktop running / the screen off")
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="Print the PIN and wait for it to be entered in Sunshine without reading stdin",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Only read HTTP /serverinfo; no pairing or state changes"
    )
    parser.add_argument("--yes", action="store_true", help="Confirm the state-changing check")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(_parse_args())))
