"""Bounded per-request ownership registry for import cancellation signals.

Callers must verify callback/bridge/FD cleanup before unregister(); unregister
only drops registry ownership and does not set the event or prove worker quiescence.
"""

from __future__ import annotations

import threading
from typing import Dict, Tuple

_HOLD = "Import request registry held"
_MAX_ACTIVE = 32


class ImportRequestRegistry:
    """In-memory registry with at most 32 active import request records."""

    def __init__(self) -> None:
        try:
            try:
                self._lock = threading.Lock()
            except (KeyboardInterrupt, SystemExit):
                raise
            except Exception:
                raise RuntimeError(_HOLD) from None
            self._closed = False
            self._records: Dict[int, Tuple[object, threading.Event]] = {}
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            raise RuntimeError(_HOLD) from None

    def register(self) -> Tuple[object, threading.Event]:
        try:
            with self._lock:
                if self._closed or len(self._records) >= _MAX_ACTIVE:
                    raise RuntimeError(_HOLD) from None
                try:
                    event = threading.Event()
                except (KeyboardInterrupt, SystemExit):
                    raise
                except Exception:
                    raise RuntimeError(_HOLD) from None
                handle = object()
                self._records[id(handle)] = (handle, event)
                return handle, event
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            raise RuntimeError(_HOLD) from None

    def unregister(self, handle: object) -> None:
        try:
            if type(handle) is not object:
                raise RuntimeError(_HOLD) from None
            with self._lock:
                key = id(handle)
                entry = self._records.get(key)
                if entry is None or entry[0] is not handle:
                    raise RuntimeError(_HOLD) from None
                del self._records[key]
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            raise RuntimeError(_HOLD) from None

    def close_and_cancel(self) -> Tuple[Tuple[object, threading.Event], ...]:
        try:
            with self._lock:
                self._closed = True
                snapshot = tuple((h, e) for h, e in self._records.values())
            held: RuntimeError | None = None
            for _handle, event in snapshot:
                try:
                    event.set()
                except BaseException as exc:
                    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                        raise
                    held = RuntimeError(_HOLD)
            if held is not None:
                raise held from None
            return snapshot
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            raise RuntimeError(_HOLD) from None

    def active_count(self) -> int:
        try:
            with self._lock:
                return len(self._records)
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            raise RuntimeError(_HOLD) from None

    def is_closed(self) -> bool:
        try:
            with self._lock:
                return self._closed
        except (KeyboardInterrupt, SystemExit):
            raise
        except Exception:
            raise RuntimeError(_HOLD) from None
