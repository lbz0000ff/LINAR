"""LINAR — FastAPI entry point.

Usage:
    python main.py                          # 127.0.0.1:8080
    python -m agent.main                   # same via module
    python main.py --host 0.0.0.0 --port 80
"""

import sys
import os

# ── UTF-8 everywhere (Windows defaults to gbk) ──────────────────
if sys.platform == "win32":
    for _s in (sys.stdin, sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, AttributeError):
            pass

_agent_dir = os.path.dirname(os.path.abspath(__file__))
if _agent_dir not in sys.path:
    sys.path.insert(0, _agent_dir)

import uvicorn
from api.app import app


def main():
    import argparse
    parser = argparse.ArgumentParser(description="LINAR FastAPI server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address")
    parser.add_argument("--port", type=int, default=8080, help="Bind port")
    parser.add_argument("--reload", action="store_true", help="Auto-reload on changes")
    args = parser.parse_args()

    uvicorn.run(
        "api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
