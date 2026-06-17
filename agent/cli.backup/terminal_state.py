"""终端状态管理器

负责确保TUI退出时终端状态始终被正确恢复。
使用多层保护机制防止终端锁定问题。

核心原则：
- 监控线程只检测BROKEN状态（真正的异常），不检测LOCKED
- isatty() == False 不是锁定，是VSCode终端的正常现象
- 强制重置只在atexit退出时执行，不在运行时自动恢复
"""

from __future__ import annotations

import sys
import os

_AGENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _AGENT_DIR not in sys.path:
    sys.path.insert(0, _AGENT_DIR)

import atexit
import signal
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import logger

log = logger.get_logger(__name__)


class TerminalState(Enum):
    NORMAL = "normal"
    FULLSCREEN = "fullscreen"
    LOCKED = "locked"
    BROKEN = "broken"
    MONITORING = "monitoring"


@dataclass
class TerminalStateSnapshot:
    timestamp: float
    state: TerminalState
    platform: str
    is_tty: bool
    term_var: Optional[str]
    console_modes: dict[str, int] = field(default_factory=dict)
    restore_attempts: int = 0
    restored: bool = False


class TerminalStateManager:
    """终端状态管理器 - 只保护真正需要保护的状态"""

    def __init__(self) -> None:
        self._app_instance = None
        self._terminal_restored = False
        self._restore_attempts = 0
        self._max_restore_attempts = 5
        self._snapshot: Optional[TerminalStateSnapshot] = None
        self._monitoring_active = False
        self._monitor_thread: Optional[threading.Thread] = None

        # 注册退出保护（这些是安全的，只在进程退出时触发）
        atexit.register(self._atexit_restore)
        try:
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
        except (OSError, AttributeError):
            pass
        sys.excepthook = self._global_exception_handler

    def set_app(self, app: object) -> None:
        """设置prompt_toolkit应用实例后启动监控"""
        self._app_instance = app
        self._capture_initial_state()
        self._start_monitoring()

    def _capture_initial_state(self) -> None:
        self._snapshot = self._get_terminal_state_snapshot()
        log.debug("Terminal state: %s", self._snapshot.state.value)

    def _atexit_restore(self) -> None:
        """进程退出时恢复终端"""
        log.info("Restoring terminal on exit")
        self._cleanup_terminal()

    def _signal_handler(self, signum: int, frame) -> None:
        log.info("Signal %s: cleaning up terminal", signum)
        self._cleanup_terminal()

    def _global_exception_handler(self, exc_type, exc_value, exc_traceback) -> None:
        log.critical("Unhandled %s: %s", exc_type.__name__, exc_value)
        self._cleanup_terminal()

    def _start_monitoring(self) -> None:
        """启动监控线程（仅监控BROKEN状态）"""
        self._monitoring_active = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="terminal_monitor",
        )
        self._monitor_thread.start()

    def _monitor_loop(self) -> None:
        """监控循环 - 只检测BROKEN（真正异常），不干扰LOCKED"""
        while self._monitoring_active:
            try:
                state = self._get_terminal_state_snapshot()
                if state.state == TerminalState.BROKEN:
                    log.warning("Terminal is broken, attempting recovery")
                    # 只恢复console mode，不调app.exit()（那会关闭TUI）
                    self._restore_via_windows_console()
                elif state.state == TerminalState.LOCKED:
                    # 只是记录，不自动恢复（LOCKED可能是正常的VSCode环境）
                    pass
                # 每30秒debug日志一次（降低日志频率）
                if int(time.time()) % 30 == 0:
                    log.debug("Terminal state: %s", state.state.value)
            except Exception as exc:
                log.error("Monitor error: %s", exc)
            time.sleep(10)

    def _get_terminal_state_snapshot(self) -> TerminalStateSnapshot:
        """获取终端状态 - 使用Windows API精准判断"""
        snapshot = TerminalStateSnapshot(
            timestamp=time.time(),
            state=TerminalState.NORMAL,
            platform=sys.platform,
            is_tty=sys.stdin.isatty() and sys.stdout.isatty(),
            term_var=os.environ.get("TERM"),
            restore_attempts=self._restore_attempts,
            restored=self._terminal_restored,
        )
        try:
            if sys.platform == "win32":
                try:
                    import ctypes
                    from ctypes.wintypes import DWORD
                    STD_INPUT_HANDLE = -10
                    STD_OUTPUT_HANDLE = -11
                    for name, handle in [
                        ("stdin", STD_INPUT_HANDLE),
                        ("stdout", STD_OUTPUT_HANDLE),
                    ]:
                        mode = DWORD(0)
                        ok = ctypes.windll.kernel32.GetConsoleMode(
                            handle, ctypes.byref(mode)
                        )
                        if ok:
                            snapshot.console_modes[name] = mode.value
                        else:
                            snapshot.state = TerminalState.BROKEN
                            break
                    if snapshot.state != TerminalState.BROKEN:
                        mode = snapshot.console_modes.get("stdout", 0)
                        if mode == 0x0003:
                            snapshot.state = TerminalState.NORMAL
                        elif mode == 0x0015:
                            snapshot.state = TerminalState.FULLSCREEN
                        else:
                            snapshot.state = TerminalState.MONITORING
                except Exception as e:
                    log.warning("Windows console detection: %s", e)
                    snapshot.state = TerminalState.BROKEN
            else:
                tty = sys.stdin.isatty() and sys.stdout.isatty()
                snapshot.state = TerminalState.NORMAL if tty else TerminalState.MONITORING
                snapshot.is_tty = tty
        except Exception as e:
            log.error("State detection failed: %s", e)
            snapshot.state = TerminalState.BROKEN
        return snapshot

    def _cleanup_terminal(self) -> None:
        """最终清理 - 只在退出时调用"""
        self._terminal_restored = True
        if self._app_instance:
            try:
                self._app_instance.exit()
            except Exception:
                pass
        if sys.platform == "win32":
            try:
                import ctypes
                STD_INPUT_HANDLE = -10
                STD_OUTPUT_HANDLE = -11
                ctypes.windll.kernel32.SetConsoleMode(STD_INPUT_HANDLE, 0x0080)
                ctypes.windll.kernel32.SetConsoleMode(STD_OUTPUT_HANDLE, 0x0003)
            except Exception:
                pass
        try:
            print(file=sys.stderr, flush=True)
        except Exception:
            pass

    def restore_terminal(self, force: bool = False) -> bool:
        """手动恢复终端 - 不会触发强制重置"""
        if self._terminal_restored and not force:
            return True
        attempt = self._restore_attempts + 1
        self._restore_attempts += 1
        log.info("Restoring terminal (attempt=%d)", attempt)
        try:
            if self._restore_via_prompt_toolkit():
                self._terminal_restored = True
                return True
            if self._restore_via_windows_console():
                self._terminal_restored = True
                return True
            return False
        except Exception as e:
            log.error("Restore failed: %s", e)
            return False

    def _restore_via_prompt_toolkit(self) -> bool:
        if self._app_instance is None:
            return False
        try:
            self._app_instance.exit()
            time.sleep(0.1)
            return True
        except Exception:
            return False

    def _restore_via_windows_console(self) -> bool:
        if sys.platform != "win32":
            return False
        try:
            import ctypes
            STD_INPUT_HANDLE = -10
            STD_OUTPUT_HANDLE = -11
            ok = ctypes.windll.kernel32.SetConsoleMode(STD_INPUT_HANDLE, 0x0080)
            ok = ctypes.windll.kernel32.SetConsoleMode(STD_OUTPUT_HANDLE, 0x0003) and ok
            return bool(ok)
        except Exception:
            return False

    def export_state_snapshot(self) -> str:
        s = self._get_terminal_state_snapshot()
        return (
            f"State: {s.state.value}\n"
            f"Platform: {s.platform}\n"
            f"TTY: {s.is_tty}\n"
            f"TERM: {s.term_var or '-'}\n"
            f"Modes: {s.console_modes}\n"
            f"Attempts: {s.restore_attempts}\n"
            f"Restored: {s.restored}\n"
        )

    def stop_monitoring(self) -> None:
        self._monitoring_active = False


_terminal_manager: Optional[TerminalStateManager] = None


def get_terminal_manager() -> TerminalStateManager:
    global _terminal_manager
    if _terminal_manager is None:
        _terminal_manager = TerminalStateManager()
    return _terminal_manager


def set_terminal_app(app: object) -> None:
    get_terminal_manager().set_app(app)


def restore_terminal_now(force: bool = True) -> bool:
    return get_terminal_manager().restore_terminal(force=force)
