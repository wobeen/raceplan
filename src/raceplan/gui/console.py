"""Clean up when the console window is closed (Windows).

Python turns Ctrl+C and Ctrl+Break into exceptions, but not closing the window: without a handler Windows ends the
process within about five seconds and comparisons it started would stay recorded as running. The handler runs the
cleanup before returning (Windows ends the process right after). Ctrl+C and Ctrl+Break still go to Python as before.
Closing the window (CTRL_CLOSE_EVENT) is the guaranteed case; logoff and shutdown are handled when Windows delivers
them, which it does not promise for interactive console programs.
"""
from __future__ import annotations

import ctypes
import os
import sys

CLOSE_EVENTS = {2, 5, 6}  # CTRL_CLOSE_EVENT, CTRL_LOGOFF_EVENT, CTRL_SHUTDOWN_EVENT
CLOSE_DEADLINE_S = 4.0  # Windows allows about five seconds after a console window is closed.


def on_console_close(cleanup):
    """Register cleanup() for console close; returns a function that removes it again (a no-op elsewhere)."""
    if os.name != 'nt':
        return lambda: None
    routine_type = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)

    def handler(event):
        if event not in CLOSE_EVENTS:
            return 0  # Not ours: Ctrl+C / Ctrl+Break continue to Python's own handler.
        try:
            cleanup()
        except Exception:
            pass
        return 1

    routine = routine_type(handler)  # Referenced by remove() below, so it lives as long as it is registered.
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.SetConsoleCtrlHandler.argtypes = [routine_type, ctypes.c_int]
    if not kernel32.SetConsoleCtrlHandler(routine, 1):
        print(f'raceplan: closing this window will not stop started comparisons cleanly '
              f'(console handler not registered, error {ctypes.get_last_error()}); use Ctrl+C to quit', file=sys.stderr)
        return lambda: None

    def remove():
        kernel32.SetConsoleCtrlHandler(routine, 0)
    return remove
