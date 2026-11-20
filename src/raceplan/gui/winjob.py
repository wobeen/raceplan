"""Windows Job Objects: one per comparison, so its whole process tree can be stopped and nothing outlives it.

A process put in a job before it starts any child keeps every descendant in that job (breakaway is not allowed).
Terminating the job stops all of them, even ones whose parent has already exited, and with KILL_ON_JOB_CLOSE closing
the last handle does the same: when the explorer ends, however it ends, the operating system stops what it started.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import threading

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_ulonglong) for name in ('ReadOperationCount', 'WriteOperationCount', 'OtherOperationCount',
                                                        'ReadTransferCount', 'WriteTransferCount', 'OtherTransferCount')]


class _BasicLimits(ctypes.Structure):
    _fields_ = [('PerProcessUserTimeLimit', ctypes.c_int64), ('PerJobUserTimeLimit', ctypes.c_int64),
                ('LimitFlags', wintypes.DWORD), ('MinimumWorkingSetSize', ctypes.c_size_t),
                ('MaximumWorkingSetSize', ctypes.c_size_t), ('ActiveProcessLimit', wintypes.DWORD),
                ('Affinity', ctypes.c_size_t), ('PriorityClass', wintypes.DWORD), ('SchedulingClass', wintypes.DWORD)]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [('BasicLimitInformation', _BasicLimits), ('IoInfo', _IoCounters),
                ('ProcessMemoryLimit', ctypes.c_size_t), ('JobMemoryLimit', ctypes.c_size_t),
                ('PeakProcessMemoryUsed', ctypes.c_size_t), ('PeakJobMemoryUsed', ctypes.c_size_t)]


def _kernel32():
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32


def _fail(what, code=None):
    raise ctypes.WinError(ctypes.get_last_error() if code is None else code, f'{what} failed')


class KillOnCloseJob:
    """A job that kills its processes when terminated or when its handle closes. terminate() and close() may be
    called from different threads and more than once; the handle is never used after it is closed."""

    def __init__(self):
        self._kernel32 = _kernel32()
        self._lock = threading.Lock()
        self._handle = self._kernel32.CreateJobObjectW(None, None)
        if not self._handle:
            _fail('CreateJobObject')
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self._kernel32.SetInformationJobObject(self._handle, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                                                      ctypes.byref(limits), ctypes.sizeof(limits)):
            code = ctypes.get_last_error()  # Kept before close() can overwrite it.
            self.close()
            _fail('SetInformationJobObject', code)

    def assign(self, process):
        """Put a subprocess.Popen in the job; do this before it is allowed to start children."""
        with self._lock:
            if not self._handle or not self._kernel32.AssignProcessToJobObject(self._handle, int(process._handle)):
                _fail('AssignProcessToJobObject')

    def terminate(self):
        """Kill every process in the job; False if that could not be done (already closed, or Windows refused)."""
        with self._lock:
            return bool(self._handle) and bool(self._kernel32.TerminateJobObject(self._handle, 1))

    def close(self):
        """Release the job; any process still in it is killed (KILL_ON_JOB_CLOSE)."""
        with self._lock:
            handle, self._handle = self._handle, None
            if handle:
                self._kernel32.CloseHandle(handle)
