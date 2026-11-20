"""Commands of the packaged RacePlan.exe (Windows). A Python install has raceplan-gui and raceplan-watch instead.

    RacePlan.exe [gui] [options]              open the results explorer (what a double click does)
    RacePlan.exe watch FILE.py:CLASS ...      re-run a comparison whenever your planner file changes

The explorer also starts this exe with an internal command to run each comparison in its own process; that command
is not part of the interface.
"""
from __future__ import annotations

import sys

from raceplan.gui.frozen import WORKER_COMMAND

USAGE = """usage: RacePlan.exe [gui] [options]
       RacePlan.exe watch FILE.py:CLASS [FILE.py:CLASS ...] --scenario SCENARIO.yaml [options]

  gui     open the saved-results explorer in your browser (the default; a double click does this)
  watch   re-run a comparison every time your planner file changes

RacePlan.exe gui --help and RacePlan.exe watch --help list the options."""


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == [WORKER_COMMAND]:  # Decided before anything else loads: a worker never starts a server or browser.
        from raceplan.gui import workflow_runner
        return workflow_runner.main(argv[1:])
    if argv[:1] in (['-h'], ['--help'], ['help']):
        print(USAGE)
        return 0
    if argv[:1] == ['watch']:
        from raceplan.gui import watch
        return watch.main(argv[1:])
    if argv[:1] == ['gui']:
        argv = argv[1:]
    from raceplan.gui import server
    return server.main(argv)


if __name__ == '__main__':
    raise SystemExit(main())
