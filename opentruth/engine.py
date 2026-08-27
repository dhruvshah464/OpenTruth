"""Orchestrate one verification run into a sealed evidence directory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from opentruth.discovery import load_environment
from opentruth.llm import build_plan
from opentruth.requirement import load_requirements
from opentruth.runners.browser import execute_plan
from opentruth.runners.http import execute_http_plan
from opentruth.runners.state import execute_state_plan
from opentruth.store import RunStore, load_jsonl
from opentruth.verdicts import INCONCLUSIVE, build_verdict

from opentruth.runners.process import (
    free_port,
    health_url,
    start_app,
    stop_app,
    wait_health,
)


def _inconclusive_all(store: RunStore, requirement, reason: str) -> list[dict[str, Any]]:
    records = []
    for constraint in requirement.constraints:
        eid = store.allocate("E-")
        rec = store.append(
            "assertions.jsonl",
            {
                "id": eid,
                "constraint_id": constraint.id,
                "step_id": None,
                "check": "reachable",
                "expect": "application reachable",
                "cites": [],
                "result": INCONCLUSIVE,
                "detail": reason,
                "artifact": None,
            },
        )
        records.append(rec)
    return records


def _requirement_path(target: Path, mode: str) -> Path:
    if mode == "state":
        alt = target / "requirements-state.yaml"
        if alt.is_file():
            return alt
    return target / "requirements.yaml"


def verify(
    target: Path,
    runs_root: Path | None = None,
    persist_session: bool | None = None,
    write_identity: bool | None = None,
    start: bool = True,
    mode: str = "browser",
    llm: Any = None,
    llm_model: str | None = None,
    llm_base_url: str | None = None,
) -> dict[str, Any]:
    target = Path(target).resolve()
    runs_root = Path(runs_root) if runs_root else target / ".opentruth" / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)

    req_path = _requirement_path(target, mode)
    requirement = load_requirements(req_path)

    port = free_port() if start else None
    env = load_environment(target, port=port)
    store = RunStore(runs_root)
    store.create()
    store.write_json("requirements.json", requirement.to_json())

    extra: dict[str, str] = {}
    proc = None
    plan: dict[str, Any]

    try:
        db_dir = target / ".opentruth-tmp"
        db_dir.mkdir(exist_ok=True)
        db_file = db_dir / f"{store.run_id}.sqlite"
        extra["MINIAUTH_DB"] = str(db_file)
        if persist_session is not None:
            extra["MINIAUTH_PERSIST_SESSION"] = "1" if persist_session else "0"
        if write_identity is not None:
            extra["MINIAUTH_WRITE_IDENTITY"] = "1" if write_identity else "0"
        if start and env.start:
            log_path = store.root / "artifacts" / "server.log"
            proc = start_app(env, extra=extra, log_path=log_path)
            reachable = wait_health(health_url(env), env.ready_timeout)
        elif not start:
            reachable = wait_health(health_url(env), min(env.ready_timeout, 2.0))
        else:
            reachable = wait_health(health_url(env), env.ready_timeout)

        if not reachable:
            plan = {
                "requirement_id": requirement.id,
                "mode": mode,
                "actor": None,
                "base_url": env.url,
                "steps": [],
                "note": "application not reachable",
            }
            store.write_json("plan.json", plan)
            _inconclusive_all(store, requirement, f"health check failed: {health_url(env)}")
        else:
            plan = build_plan(
                requirement,
                env.url,
                mode=mode,
                routes=env.api_routes or None,
                llm=llm,
                llm_model=llm_model,
                llm_base_url=llm_base_url,
            )
            store.write_json("plan.json", plan)
            try:
                if mode == "api":
                    execute_http_plan(store, plan)
                elif mode == "state":
                    execute_state_plan(store, plan, db_file)
                else:
                    execute_plan(store, plan)
            except Exception as exc:
                _inconclusive_all(store, requirement, f"{mode} runner failed: {exc}")
    finally:
        stop_app(proc)

    assertions = load_jsonl(store.root / "assertions.jsonl")
    verdict = build_verdict(store.run_id, requirement, assertions)
    store.write_json("verdict.json", verdict)
    store.seal()
    return {
        "run_dir": store.root,
        "run_id": store.run_id,
        "verdict": verdict,
    }
