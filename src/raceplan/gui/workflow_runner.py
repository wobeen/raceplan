"""Run ``raceplan.workflow`` for the explorer: same arguments, same outputs, one difference.

While a comparison runs, the explorer polls its workflow.json. On Windows a file that is open for reading cannot be
replaced, so workflow's atomic state update (os.replace) can fail for a moment and abort an otherwise good run. Here the
state save is retried briefly on PermissionError. workflow.py itself is left untouched (its source hash is recorded
by earlier experiments).
"""
from __future__ import annotations

import time

from raceplan import workflow

ATTEMPTS = 50
PAUSE_S = 0.02

_save_state = workflow._save_state


def _patient_save_state(path, state):
    for attempt in range(ATTEMPTS):
        try:
            return _save_state(path, state)
        except PermissionError:
            if attempt == ATTEMPTS - 1:
                raise
            time.sleep(PAUSE_S)


def main(argv=None):
    workflow._save_state = _patient_save_state
    return workflow.main(argv)


if __name__ == '__main__':
    raise SystemExit(main())
