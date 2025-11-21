#!/usr/bin/env python
"""
Utility to flip the `.env` quality-scenario knobs without hand-editing.

Usage:
    python scripts/apply_env_preset.py availability
    python scripts/apply_env_preset.py availability-failure
    python scripts/apply_env_preset.py performance
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List

PRESETS: Dict[str, Dict[str, str]] = {
    "availability": {
        "PAYMENT_REFUND_FAILURE_PROBABILITY": "0",
        "THROTTLING_MAX_RPS": "200",
        "THROTTLING_WINDOW_SECONDS": "1",
        "GUNICORN_WORKERS": "8",
        "GUNICORN_THREADS": "4",
        "GUNICORN_TIMEOUT": "90",
    },
    "availability-failure": {
        "PAYMENT_REFUND_FAILURE_PROBABILITY": "1.0",
        "THROTTLING_MAX_RPS": "200",
        "THROTTLING_WINDOW_SECONDS": "1",
        "GUNICORN_WORKERS": "8",
        "GUNICORN_THREADS": "4",
        "GUNICORN_TIMEOUT": "90",
    },
    "performance": {
        "PAYMENT_REFUND_FAILURE_PROBABILITY": "0",
        "THROTTLING_MAX_RPS": "2",
        "THROTTLING_WINDOW_SECONDS": "1",
        "GUNICORN_WORKERS": "8",
        "GUNICORN_THREADS": "4",
        "GUNICORN_TIMEOUT": "90",
    },
}


def _load_env_lines(env_path: Path) -> List[str]:
    if env_path.exists():
        return env_path.read_text(encoding="utf-8").splitlines()
    return []


def _write_env(env_path: Path, lines: List[str]) -> None:
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _apply_preset(lines: List[str], preset: Dict[str, str]) -> List[str]:
    line_index = {}
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key:
            line_index[key] = idx

    for key, value in preset.items():
        new_line = f"{key}={value}"
        if key in line_index:
            lines[line_index[key]] = new_line
        else:
            lines.append(new_line)

    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply a quality-scenario env preset.")
    parser.add_argument("preset", choices=PRESETS.keys(), help="Preset name to apply.")
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to the env file (default: %(default)s).",
    )
    args = parser.parse_args()

    env_path = Path(args.env_file).resolve()
    lines = _load_env_lines(env_path)
    lines = _apply_preset(lines, PRESETS[args.preset])
    _write_env(env_path, lines)

    print(f"Updated {env_path} with preset '{args.preset}'.")
    print("Restart `docker compose ... up` for changes to take effect.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

