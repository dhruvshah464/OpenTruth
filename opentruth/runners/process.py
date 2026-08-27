"""Start and stop a declared local process."""

from __future__ import annotations

import os
import shlex
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from opentruth.discovery import Environment


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_health(url: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as response:
                if 200 <= response.status < 300:
                    return True
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            time.sleep(0.15)
    return False


def start_app(
    env: Environment,
    extra: dict[str, str] | None = None,
    log_path: Path | None = None,
) -> subprocess.Popen[bytes] | None:
    if not env.start:
        return None
    merged = {**os.environ, **env.extra_env, **(extra or {})}
    if env.port is not None:
        merged.setdefault("PORT", str(env.port))
    argv = shlex.split(env.start)
    if argv and argv[0] in {"python", "python3"}:
        argv[0] = sys.executable
    log_handle = log_path.open("wb") if log_path else subprocess.DEVNULL
    proc = subprocess.Popen(
        argv,
        cwd=env.root,
        env=merged,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    proc._opentruth_log = log_handle  # type: ignore[attr-defined]
    return proc


def stop_app(proc: subprocess.Popen[bytes] | None) -> None:
    if proc is None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    log_handle = getattr(proc, "_opentruth_log", None)
    if log_handle not in (None, subprocess.DEVNULL):
        try:
            log_handle.close()
        except Exception:
            pass


def health_url(env: Environment) -> str:
    health = env.health
    if health.startswith("http://") or health.startswith("https://"):
        return health
    if not health.startswith("/"):
        health = "/" + health
    return env.url.rstrip("/") + health
