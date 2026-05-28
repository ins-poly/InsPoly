from __future__ import annotations

import ctypes
from ctypes import c_char_p, c_uint32, c_void_p
from ctypes.util import find_library
import sys


class MacSleepAssertion:
    def __init__(self, *, enabled: bool | None = None) -> None:
        self.enabled = sys.platform == "darwin" if enabled is None else enabled
        self._assertion_id: int | None = None
        self._iokit: ctypes.CDLL | None = None
        self._corefoundation: ctypes.CDLL | None = None
        self.last_error: str | None = None

    @property
    def active(self) -> bool:
        return self._assertion_id is not None

    @property
    def supported(self) -> bool:
        return self.enabled and sys.platform == "darwin"

    def acquire(self) -> bool:
        if self.active:
            return True
        if not self.supported:
            self.last_error = "macOS power assertions are unavailable on this platform."
            return False
        if not self._load_libraries():
            return False

        assertion_type = self._cf_string("PreventUserIdleSystemSleep")
        assertion_name = self._cf_string("InsPoly analysis running")
        assertion_id = c_uint32(0)
        try:
            result = self._iokit.IOPMAssertionCreateWithName(
                assertion_type,
                c_uint32(255),
                assertion_name,
                ctypes.byref(assertion_id),
            )
        finally:
            self._release_cf(assertion_type)
            self._release_cf(assertion_name)
        if int(result) != 0:
            self.last_error = f"IOPMAssertionCreateWithName failed: {int(result)}"
            return False
        self._assertion_id = int(assertion_id.value)
        self.last_error = None
        return True

    def release(self) -> None:
        if self._assertion_id is None:
            return
        if self._iokit is not None:
            self._iokit.IOPMAssertionRelease(c_uint32(self._assertion_id))
        self._assertion_id = None
        self.last_error = None

    def status(self) -> dict[str, object]:
        return {
            "supported": self.supported,
            "active": self.active,
            "lastError": self.last_error,
        }

    def _load_libraries(self) -> bool:
        if self._iokit is not None and self._corefoundation is not None:
            return True
        iokit_path = find_library("IOKit")
        core_foundation_path = find_library("CoreFoundation")
        if not iokit_path or not core_foundation_path:
            self.last_error = "IOKit/CoreFoundation libraries were not found."
            return False
        try:
            self._iokit = ctypes.cdll.LoadLibrary(iokit_path)
            self._corefoundation = ctypes.cdll.LoadLibrary(core_foundation_path)
        except OSError as exc:
            self.last_error = str(exc)
            return False

        self._corefoundation.CFStringCreateWithCString.argtypes = [c_void_p, c_char_p, c_uint32]
        self._corefoundation.CFStringCreateWithCString.restype = c_void_p
        self._corefoundation.CFRelease.argtypes = [c_void_p]
        self._corefoundation.CFRelease.restype = None
        self._iokit.IOPMAssertionCreateWithName.argtypes = [
            c_void_p,
            c_uint32,
            c_void_p,
            ctypes.POINTER(c_uint32),
        ]
        self._iokit.IOPMAssertionCreateWithName.restype = ctypes.c_int
        self._iokit.IOPMAssertionRelease.argtypes = [c_uint32]
        self._iokit.IOPMAssertionRelease.restype = ctypes.c_int
        return True

    def _cf_string(self, value: str) -> c_void_p:
        assert self._corefoundation is not None
        return self._corefoundation.CFStringCreateWithCString(
            None,
            value.encode("utf-8"),
            c_uint32(0x08000100),
        )

    def _release_cf(self, value: c_void_p) -> None:
        if value and self._corefoundation is not None:
            self._corefoundation.CFRelease(value)
