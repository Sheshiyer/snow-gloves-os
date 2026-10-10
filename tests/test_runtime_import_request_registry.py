"""Tests for ImportRequestRegistry."""

from __future__ import annotations

import threading
from typing import List, Tuple

import pytest

from scripts.lib.runtime_import_request_registry import ImportRequestRegistry, _HOLD


def test_register_returns_independent_events_and_unique_handles() -> None:
    reg = ImportRequestRegistry()
    h1, e1 = reg.register()
    h2, e2 = reg.register()
    assert type(h1) is object and type(h2) is object
    assert h1 is not h2
    assert type(e1) is threading.Event and type(e2) is threading.Event
    assert e1 is not e2
    assert reg.active_count() == 2


def test_capacity_32_third_register_held_unregister_reopens_slot() -> None:
    reg = ImportRequestRegistry()
    handles: List[object] = []
    for _ in range(32):
        h, _ = reg.register()
        handles.append(h)
    assert reg.active_count() == 32
    with pytest.raises(RuntimeError) as exc:
        reg.register()
    assert exc.value.args == (_HOLD,)
    assert exc.value.__cause__ is None
    reg.unregister(handles[0])
    assert reg.active_count() == 31
    h_new, _ = reg.register()
    assert type(h_new) is object
    assert reg.active_count() == 32


def test_register_after_close_held() -> None:
    reg = ImportRequestRegistry()
    reg.close_and_cancel()
    with pytest.raises(RuntimeError) as exc:
        reg.register()
    assert exc.value.args == (_HOLD,)


def test_close_sets_events_and_retains_records() -> None:
    reg = ImportRequestRegistry()
    h, ev = reg.register()
    snap = reg.close_and_cancel()
    assert snap == ((h, ev),)
    assert ev.is_set()
    assert reg.active_count() == 1
    assert reg.is_closed() is True


def test_repeat_close_returns_snapshot_and_signals_again() -> None:
    reg = ImportRequestRegistry()
    h, ev = reg.register()
    reg.close_and_cancel()
    ev.clear()
    snap2 = reg.close_and_cancel()
    assert snap2 == ((h, ev),)
    assert ev.is_set()
    assert reg.is_closed() is True


def test_foreign_duplicate_and_trap_handles_no_magic() -> None:
    reg = ImportRequestRegistry()
    h, _ = reg.register()
    foreign = object()
    with pytest.raises(RuntimeError):
        reg.unregister(foreign)
    reg.unregister(h)
    with pytest.raises(RuntimeError):
        reg.unregister(h)

    class SubObject(object):
        pass

    with pytest.raises(RuntimeError):
        reg.unregister(SubObject())

    class EvilHandle:
        def __init__(self, target: object) -> None:
            self._target = target

        def __eq__(self, other: object) -> bool:
            return other is self._target

        def __hash__(self) -> int:
            return id(self._target)

    reg2 = ImportRequestRegistry()
    owned, _ = reg2.register()
    trap = EvilHandle(owned)
    with pytest.raises(RuntimeError):
        reg2.unregister(trap)  # type: ignore[arg-type]


def test_unregister_after_close_decreases_count_not_quiescence() -> None:
    reg = ImportRequestRegistry()
    h, ev = reg.register()
    reg.close_and_cancel()
    assert ev.is_set()
    ev.clear()
    reg.unregister(h)
    assert reg.active_count() == 0
    assert ev.is_set() is False


def test_close_continues_signalling_on_event_set_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    real_event = threading.Event
    calls = {"n": 0}

    def factory() -> threading.Event:
        calls["n"] += 1
        if calls["n"] == 1:
            ev = real_event()

            def bad_set() -> None:
                raise OSError("injected")

            ev.set = bad_set  # type: ignore[method-assign]
            return ev
        return real_event()

    monkeypatch.setattr(threading, "Event", factory)
    reg = ImportRequestRegistry()
    _h1, e1 = reg.register()
    _h2, e2 = reg.register()
    with pytest.raises(RuntimeError) as exc:
        reg.close_and_cancel()
    assert exc.value.args == (_HOLD,)
    assert e2.is_set()
    assert reg.active_count() == 2


def test_concurrent_register_close_no_uncancelled_accepted_record() -> None:
    reg = ImportRequestRegistry()
    barrier = threading.Barrier(3)
    outcomes: List[Tuple[object, threading.Event] | BaseException] = []
    lock = threading.Lock()

    def worker() -> None:
        barrier.wait(timeout=2)
        try:
            pair = reg.register()
        except BaseException as exc:
            with lock:
                outcomes.append(exc)
            return
        with lock:
            outcomes.append(pair)

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    t2.start()
    barrier.wait(timeout=2)
    snap = reg.close_and_cancel()
    t1.join(timeout=3)
    assert not t1.is_alive()
    t2.join(timeout=3)
    assert not t2.is_alive()

    accepted: List[Tuple[object, threading.Event]] = []
    for item in outcomes:
        if isinstance(item, tuple):
            accepted.append(item)
        else:
            assert isinstance(item, RuntimeError)
            assert item.args == (_HOLD,)

    for _h, ev in accepted:
        assert ev.is_set()
    for pair in snap:
        assert pair[1].is_set()
    assert reg.is_closed()


@pytest.mark.parametrize("target",["Lock","Event"])
@pytest.mark.parametrize("excclass",[KeyboardInterrupt,SystemExit])
def test_factory_original_controlflow(target,excclass,monkeypatch):
    registry=ImportRequestRegistry() if target == "Event" else None
    original=excclass("original")
    def boom():raise original
    monkeypatch.setattr(threading,target,boom)
    with pytest.raises(excclass) as caught:
        registry.register() if registry is not None else ImportRequestRegistry()
    assert caught.value is original

def test_snapshot_is_tuple_not_live_registry_view() -> None:
    reg = ImportRequestRegistry()
    h, ev = reg.register()
    snap = reg.close_and_cancel()
    reg.unregister(h)
    assert snap == ((h, ev),)
    assert reg.active_count() == 0

@pytest.mark.parametrize("method",["register","unregister","close_and_cancel","active_count","is_closed"])
def test_lock_fault_rendered_redaction(method):
    import traceback
    reg=ImportRequestRegistry()
    handle,event=reg.register()
    class FaultLock:
        def __enter__(self):raise OSError("SECRET-LOCK-DETAIL")
        def __exit__(self,*args):return False
    reg._lock=FaultLock()
    with pytest.raises(RuntimeError,match="^Import request registry held$") as caught:
        getattr(reg,method)(handle) if method=="unregister" else getattr(reg,method)()
    assert caught.value.__suppress_context__ is True
    assert "SECRET-LOCK-DETAIL" not in "".join(traceback.format_exception(caught.type,caught.value,caught.tb))

@pytest.mark.parametrize("factory",["Lock","Event"])
def test_factory_ordinary_fault_rendered_redaction(factory,monkeypatch):
    import traceback
    reg=ImportRequestRegistry() if factory=="Event" else None
    def boom():raise OSError("SECRET-FACTORY")
    monkeypatch.setattr(threading,factory,boom)
    with pytest.raises(RuntimeError,match="^Import request registry held$") as caught:
        reg.register() if reg is not None else ImportRequestRegistry()
    assert "SECRET-FACTORY" not in "".join(traceback.format_exception(caught.type,caught.value,caught.tb))

def test_event_signalling_occurs_outside_lock():
    reg=ImportRequestRegistry();handle,event=reg.register();real=event.set
    observed=[]
    def check_set():
        assert reg._lock.acquire(blocking=False)
        reg._lock.release()
        observed.append(reg.is_closed())
        real()
    event.set=check_set
    assert reg.close_and_cancel()==((handle,event),)
    assert observed==[True]
    assert reg.active_count()==1

def test_trap_handle_magic_never_invoked():
    reg=ImportRequestRegistry();handle,event=reg.register();calls=[]
    class Trap:
        def __hash__(self):calls.append("hash");return 0
        def __eq__(self,other):calls.append("eq");return True
    with pytest.raises(RuntimeError,match="^Import request registry held$"):
        reg.unregister(Trap())
    assert calls==[]
    assert reg.active_count()==1
