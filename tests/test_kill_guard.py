"""Reglas de seguridad al terminar procesos."""
from __future__ import annotations

from contextlib import nullcontext

import pytest

from app.metrics import processes as processes_module
from app.metrics.processes import KillError, kill_process


class FakeProcess:
    """Proceso simulado: evita tocar procesos reales de la maquina de tests."""

    def __init__(self, name="victima", user="otro", uid=1000):
        self._name, self._user, self._uid = name, user, uid
        self.signalled = None

    def oneshot(self):
        return nullcontext()

    def name(self):
        return self._name

    def username(self):
        return self._user

    def uids(self):
        return type("Uids", (), {"real": self._uid})()

    def send_signal(self, sig):
        self.signalled = sig

    def wait(self, timeout=None):
        return 0


@pytest.fixture
def fake_process(monkeypatch):
    def install(**kwargs):
        proc = FakeProcess(**kwargs)
        monkeypatch.setattr(processes_module.psutil, "Process", lambda pid: proc)
        return proc
    return install


def as_uid(monkeypatch, uid):
    monkeypatch.setattr(processes_module.os, "getuid", lambda: uid, raising=False)


def test_root_still_cannot_kill_foreign_processes(monkeypatch, fake_process):
    """Regresion: la comprobacion se saltaba justo cuando corria como root.

    Como root el kernel no pone ninguna barrera, asi que si
    SM_ALLOW_KILL_FOREIGN esta desactivado la aplicacion tiene que imponerla.
    """
    fake_process(uid=1000, user="pi")
    as_uid(monkeypatch, 0)
    monkeypatch.setattr(processes_module.settings, "allow_kill_foreign", False)

    with pytest.raises(KillError) as excinfo:
        kill_process(4242)
    assert excinfo.value.status == 403
    assert "otro usuario" in str(excinfo.value)


def test_foreign_kill_works_when_explicitly_enabled(monkeypatch, fake_process):
    proc = fake_process(uid=1000, user="pi")
    as_uid(monkeypatch, 0)
    monkeypatch.setattr(processes_module.settings, "allow_kill_foreign", True)

    result = kill_process(4242)
    assert result["terminated"] is True
    assert proc.signalled is not None


def test_own_processes_are_always_killable(monkeypatch, fake_process):
    fake_process(uid=1000, user="monitor")
    as_uid(monkeypatch, 1000)
    monkeypatch.setattr(processes_module.settings, "allow_kill_foreign", False)
    assert kill_process(4242)["signal"] == "SIGTERM"


def test_protected_names_are_refused(monkeypatch, fake_process):
    fake_process(name="sshd", uid=1000)
    as_uid(monkeypatch, 1000)
    with pytest.raises(KillError) as excinfo:
        kill_process(4242)
    assert "protegidos" in str(excinfo.value)


def test_init_is_refused(monkeypatch):
    with pytest.raises(KillError) as excinfo:
        kill_process(1)
    assert excinfo.value.status == 403


def test_the_monitor_refuses_to_kill_itself(monkeypatch):
    import os
    with pytest.raises(KillError) as excinfo:
        kill_process(os.getpid())
    assert "si mismo" in str(excinfo.value)


def test_kill_can_be_disabled_entirely(monkeypatch, fake_process):
    fake_process(uid=1000)
    monkeypatch.setattr(processes_module.settings, "allow_kill", False)
    with pytest.raises(KillError) as excinfo:
        kill_process(4242)
    assert excinfo.value.status == 403


def test_force_sends_sigkill(monkeypatch, fake_process):
    import signal

    proc = fake_process(uid=1000)
    as_uid(monkeypatch, 1000)
    result = kill_process(4242, force=True)
    assert result["signal"] == "SIGKILL"
    # signal.SIGKILL no existe en Windows; el objetivo es Linux.
    assert proc.signalled == getattr(signal, "SIGKILL", proc.signalled)
