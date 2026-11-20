"""Run ``raceplan.workflow`` for the explorer: same arguments, same outputs, two differences.

While a comparison runs, the explorer polls its workflow.json. On Windows a file that is open for reading cannot be
replaced, so workflow's atomic state update (os.replace) can fail for a moment and abort an otherwise good run. Here the
state save is retried briefly on PermissionError. workflow.py itself is left untouched (its source hash is recorded
by earlier experiments).

With ``--after-start-signal`` (always used by the explorer) nothing is loaded until the parent writes ``start`` on
stdin: on Windows the parent first puts this process in its job object, so a user planner never starts a process
outside it. If the parent goes away first, stdin closes and the run ends without loading any planner.
"""
from __future__ import annotations

import sys
import time

from raceplan import workflow

ATTEMPTS = 50
PAUSE_S = 0.02
START_SIGNAL = '--after-start-signal'
NOT_STARTED = 3

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
    argv = list(sys.argv[1:] if argv is None else argv)
    if START_SIGNAL in argv:
        argv.remove(START_SIGNAL)
        if sys.stdin is None or sys.stdin.buffer.readline().strip() != b'start':
            print('not started: the explorer that launched this run did not signal it to start', file=sys.stderr)
            return NOT_STARTED
    workflow._save_state = _patient_save_state
    return workflow.main(argv)


if __name__ == '__main__':
    raise SystemExit(main())
