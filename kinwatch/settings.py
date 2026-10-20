"""Routine settings shared by the poller, the rules CLI and the dashboard.

Stored in kinwatch_settings.json next to the database (git-ignored), so the
family can change the parent's routine from the dashboard.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, fields
from pathlib import Path

from .rules import RoutineConfig

SETTINGS_FILE = Path("kinwatch_settings.json")
EDITABLE = ("parent_name", "activity_deadline", "package_minutes", "night_start", "night_end",
            "camera_name")
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def load_config(path: Path | str = SETTINGS_FILE) -> RoutineConfig:
    cfg = RoutineConfig()
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return cfg
    for key in EDITABLE:
        if key in data:
            setattr(cfg, key, data[key])
    return cfg


def validate(data: dict) -> dict:
    """Return the cleaned editable settings, raising ValueError on bad input."""
    out = {}
    for key in EDITABLE:
        if key not in data:
            continue
        val = data[key]
        if key == "parent_name":
            val = str(val).strip()[:40]
            if not val:
                raise ValueError("Enter a name for the person you're looking after.")
        elif key == "camera_name":
            val = str(val).strip()[:40] or "front door"
        elif key == "package_minutes":
            try:
                val = int(val)
            except (TypeError, ValueError):
                raise ValueError("Package wait must be a whole number of minutes.")
            if not 5 <= val <= 720:
                raise ValueError("Package wait must be between 5 and 720 minutes.")
        else:
            val = str(val).strip()
            if not _HHMM.match(val):
                raise ValueError(f"{key.replace('_', ' ').capitalize()} must look like 09:30.")
        out[key] = val
    return out


def save_config(data: dict, path: Path | str = SETTINGS_FILE) -> RoutineConfig:
    clean = validate(data)
    current = {k: v for k, v in asdict(load_config(path)).items() if k in EDITABLE}
    current.update(clean)
    Path(path).write_text(json.dumps(current, indent=2))
    return load_config(path)


def config_dict(cfg: RoutineConfig) -> dict:
    return {f.name: getattr(cfg, f.name) for f in fields(cfg) if f.name in EDITABLE}
