"""Tests for launcher port selection and backend URL propagation."""

from __future__ import annotations

import importlib.util
import socket
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("linar_launcher", _ROOT / "linar.py")
assert _SPEC is not None and _SPEC.loader is not None
_LINAR = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_LINAR)


def test_explicit_backend_port_is_preserved() -> None:
    assert _LINAR._select_backend_port("127.0.0.1", 9123) == 9123


def test_default_backend_port_falls_back_when_8080_is_unavailable(monkeypatch) -> None:
    real_socket = socket.socket

    class Reject8080Socket:
        def __init__(self, *args, **kwargs) -> None:
            self._socket = real_socket(*args, **kwargs)

        def __enter__(self):
            self._socket.__enter__()
            return self

        def __exit__(self, *args):
            return self._socket.__exit__(*args)

        def bind(self, address) -> None:
            if address[1] == 8080:
                raise PermissionError("reserved")
            self._socket.bind(address)

        def getsockname(self):
            return self._socket.getsockname()

    monkeypatch.setattr(_LINAR.socket, "socket", Reject8080Socket)

    selected = _LINAR._select_backend_port("127.0.0.1", None)

    assert selected > 0
    assert selected != 8080


def test_backend_origin_uses_loopback_for_wildcard_bind() -> None:
    assert _LINAR._backend_origin("0.0.0.0", 9000) == "http://127.0.0.1:9000"
    assert _LINAR._backend_origin("127.0.0.1", 9000) == "http://127.0.0.1:9000"


def test_explicit_gui_port_is_preserved() -> None:
    assert _LINAR._select_gui_port(6123) == 6123


def test_default_gui_port_falls_back_when_5173_is_unavailable(monkeypatch) -> None:
    real_socket = socket.socket

    class Reject5173Socket:
        def __init__(self, *args, **kwargs) -> None:
            self._socket = real_socket(*args, **kwargs)

        def __enter__(self):
            self._socket.__enter__()
            return self

        def __exit__(self, *args):
            return self._socket.__exit__(*args)

        def bind(self, address) -> None:
            if address[1] == 5173:
                raise PermissionError("reserved")
            self._socket.bind(address)

        def getsockname(self):
            return self._socket.getsockname()

    monkeypatch.setattr(_LINAR.socket, "socket", Reject5173Socket)

    selected = _LINAR._select_gui_port(None)

    assert selected > 0
    assert selected != 5173


def test_gui_origin_uses_ipv4_loopback() -> None:
    assert _LINAR._gui_origin(6123) == "http://127.0.0.1:6123"
