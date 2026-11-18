#!/usr/bin/env python3
"""Build dist/moonscreen.zip for HACS or a manual copy."""

from __future__ import annotations

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "custom_components" / "moonscreen"
TARGET = ROOT / "dist" / "moonscreen.zip"


def main() -> int:
    if not SOURCE.is_dir():
        raise SystemExit(f"missing source directory: {SOURCE}")
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(TARGET, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(SOURCE.rglob("*")):
            if path.is_dir() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            archive.write(path, arcname=str(path.relative_to(ROOT)))
    print(f"wrote {TARGET} ({TARGET.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
