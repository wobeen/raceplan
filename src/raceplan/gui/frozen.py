"""What differs when RacePlan runs as the packaged Windows RacePlan.exe (PyInstaller) instead of a Python install.

Only defaults and the worker command change; paths given explicitly mean the same in both.
- Scenarios: the scenarios folder shipped next to RacePlan.exe (installed: ./scenarios).
- Results: %LOCALAPPDATA%\\RacePlan\\results\\raw, the same wherever the exe is started from and outside folders that
  may be read-only (Program Files) or synced (OneDrive Documents/Desktop, whose locks collide with state saves).
  Installed: ./results/raw.
- Comparison worker: the same exe with the internal ``--workflow-worker`` command (installed: python -P -m
  raceplan.gui.workflow_runner), started in the bundle folder so the caller's folder is never on its import path.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys

WORKER_COMMAND = '--workflow-worker'


def is_frozen():
    return bool(getattr(sys, 'frozen', False))


def app_folder():
    """The folder holding RacePlan.exe and the files shipped with it."""
    return Path(sys.executable).resolve().parent


def default_scenarios():
    return app_folder() / 'scenarios' if is_frozen() else Path('scenarios')


def default_results():
    if not is_frozen():
        return Path('results/raw')
    local = os.environ.get('LOCALAPPDATA') or str(Path.home() / 'AppData' / 'Local')
    return Path(local) / 'RacePlan' / 'results' / 'raw'


def workflow_command(args):
    """The command that runs one comparison in its own process; args are workflow_runner arguments."""
    if is_frozen():
        return [sys.executable, WORKER_COMMAND, *args]
    # -P keeps the caller's folder off sys.path, so a stray yaml.py or numpy.py there is never imported.
    return [sys.executable, '-P', '-m', 'raceplan.gui.workflow_runner', *args]


def worker_folder(default):
    """Working folder of the comparison worker: inside the bundle when frozen (user paths are already absolute)."""
    return Path(getattr(sys, '_MEIPASS', app_folder())) if is_frozen() else default
