"""Declared environment only — not repository analysis."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Environment:
    root: Path
    url: str
    health: str
    start: str | None
    ready_timeout: float
    extra_env: dict[str, str]
    port: int | None
    api_routes: dict[str, dict[str, str]]
    state_sqlite: str


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def load_environment(root: Path, port: int | None = None) -> Environment:
    path = root / "opentruth.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"missing declared environment: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("opentruth.yaml must be a mapping")
    token = str(port) if port is not None else "{port}"

    def subst(value: str | None) -> str | None:
        if value is None:
            return None
        return value.replace("{port}", token)

    extra = raw.get("env") or {}
    if extra and not isinstance(extra, dict):
        raise ValueError("env must be a mapping")
    extra_env = {str(k): subst(str(v)) or "" for k, v in extra.items()}
    url = subst(_as_str(raw.get("url")))
    if not url:
        raise ValueError("opentruth.yaml needs a url")
    health = subst(_as_str(raw.get("health")) or "/health") or "/health"
    start = subst(_as_str(raw.get("start")))
    timeout = float(raw.get("ready_timeout") or 15)
    api_routes = _load_api_routes(raw.get("api"))
    state_raw = raw.get("state") or {}
    state_sqlite = "auto"
    if isinstance(state_raw, dict) and state_raw.get("sqlite"):
        state_sqlite = str(state_raw.get("sqlite"))
    return Environment(
        root=root,
        url=url.rstrip("/"),
        health=health,
        start=start,
        ready_timeout=timeout,
        extra_env=extra_env,
        port=port,
        api_routes=api_routes,
        state_sqlite=state_sqlite,
    )


def _load_api_routes(raw: Any) -> dict[str, dict[str, str]]:
    if not raw:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("api must be a mapping")
    block = raw.get("routes") if "routes" in raw else raw
    if not isinstance(block, dict):
        raise ValueError("api.routes must be a mapping")
    routes: dict[str, dict[str, str]] = {}
    for name, spec in block.items():
        if name == "routes":
            continue
        if not isinstance(spec, dict):
            continue
        method = str(spec.get("method") or "GET").upper()
        path = str(spec.get("path") or "")
        if not path:
            continue
        routes[str(name)] = {"method": method, "path": path}
    return routes
