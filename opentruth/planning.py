"""Deterministic plan IR. LLM proposals go through opentruth.llm.sanitize_plan."""

from __future__ import annotations

import uuid
from typing import Any

from opentruth.requirement import Requirement

DEFAULT_API_ROUTES = {
    "signup": {"method": "POST", "path": "/api/signup"},
    "login": {"method": "POST", "path": "/api/login"},
    "me": {"method": "GET", "path": "/api/me"},
}


def _match(statement: str, *needles: str) -> bool:
    lower = statement.lower()
    return any(n in lower for n in needles)


def _session_constraint(statement: str) -> bool:
    return _match(statement, "session persist", "persists after refresh", "after refresh")


def _unauthorized_constraint(statement: str) -> bool:
    return _match(statement, "unauthorized", "unauthenticated", "anonymous")


def expand(
    requirement: Requirement,
    base_url: str,
    email: str | None = None,
    mode: str = "browser",
    routes: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Turn one auth-shaped requirement into executable steps citing C-* ids."""
    if mode == "api":
        return expand_api(requirement, base_url, email=email, routes=routes)
    if mode == "state":
        return expand_state(requirement, base_url, email=email, routes=routes)
    if mode != "browser":
        raise ValueError(f"unknown verify mode: {mode}")
    return expand_browser(requirement, base_url, email=email)


def expand_browser(requirement: Requirement, base_url: str, email: str | None = None) -> dict[str, Any]:
    actor_email = email or f"user-{uuid.uuid4().hex[:10]}@example.test"
    password = "correct-horse-battery"
    steps: list[dict[str, Any]] = []
    n = 0

    def add(constraint_id: str, kind: str, **fields: Any) -> None:
        nonlocal n
        n += 1
        steps.append({"id": f"S-{n:03d}", "constraint_id": constraint_id, "kind": kind, **fields})

    happy = requirement.happy_path()
    add(happy.id, "navigate", url=f"{base_url}/signup")
    add(happy.id, "fill", label="Email", value=actor_email)
    add(happy.id, "fill", label="Password", value=password)
    add(happy.id, "click", role="button", name="Create account")
    add(happy.id, "assert", check="url_contains", expect="/login")
    add(happy.id, "assert", check="text_contains", expect="Account created")
    add(happy.id, "fill", label="Email", value=actor_email)
    add(happy.id, "fill", label="Password", value=password)
    add(happy.id, "click", role="button", name="Sign in")
    add(happy.id, "assert", check="url_contains", expect="/dashboard")
    add(happy.id, "assert", check="text_contains", expect="Dashboard")

    rest: list = []
    for constraint in requirement.constraints:
        if constraint.kind == "happy_path":
            continue
        if _session_constraint(constraint.statement):
            add(constraint.id, "reload")
            add(constraint.id, "assert", check="url_contains", expect="/dashboard")
            add(constraint.id, "assert", check="text_contains", expect="Dashboard")
        else:
            rest.append(constraint)

    for constraint in rest:
        stmt = constraint.statement
        cid = constraint.id
        if _match(stmt, "duplicate"):
            add(cid, "navigate", url=f"{base_url}/signup")
            add(cid, "fill", label="Email", value=actor_email)
            add(cid, "fill", label="Password", value=password)
            add(cid, "click", role="button", name="Create account")
            add(cid, "assert", check="text_contains", expect="Email already registered")
        elif _match(stmt, "invalid password", "wrong password", "bad password"):
            add(cid, "navigate", url=f"{base_url}/login")
            add(cid, "fill", label="Email", value=actor_email)
            add(cid, "fill", label="Password", value="not-the-password")
            add(cid, "click", role="button", name="Sign in")
            add(cid, "assert", check="text_contains", expect="Invalid credentials")
        elif _unauthorized_constraint(stmt):
            add(cid, "clear_cookies")
            add(cid, "navigate", url=f"{base_url}/dashboard")
            add(cid, "assert", check="url_contains", expect="/login")
        else:
            add(cid, "assert", check="unsupported_constraint", expect=stmt)

    return {
        "requirement_id": requirement.id,
        "mode": "browser",
        "runner": "browser",
        "actor": {"email": actor_email, "password": password},
        "base_url": base_url,
        "steps": steps,
    }


def expand_api(
    requirement: Requirement,
    base_url: str,
    email: str | None = None,
    routes: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    actor_email = email or f"user-{uuid.uuid4().hex[:10]}@example.test"
    password = "correct-horse-battery"
    resolved = {**DEFAULT_API_ROUTES, **(routes or {})}
    signup = resolved["signup"]
    login = resolved["login"]
    me = resolved["me"]
    steps: list[dict[str, Any]] = []
    n = 0

    def add(constraint_id: str, kind: str, **fields: Any) -> None:
        nonlocal n
        n += 1
        steps.append({"id": f"S-{n:03d}", "constraint_id": constraint_id, "kind": kind, **fields})

    def request(cid: str, spec: dict[str, str], json_body: dict | None = None, cookies: bool = True) -> None:
        add(
            cid,
            "http_request",
            method=spec["method"],
            path=spec["path"],
            json=json_body,
            cookies=cookies,
        )

    creds = {"email": actor_email, "password": password}
    happy = requirement.happy_path()
    request(happy.id, signup, creds)
    add(happy.id, "assert", check="status_equals", expect="201")
    request(happy.id, login, creds)
    add(happy.id, "assert", check="status_equals", expect="200")
    request(happy.id, me)
    add(happy.id, "assert", check="status_equals", expect="200")
    add(happy.id, "assert", check="json_contains", expect=actor_email)

    rest: list = []
    for constraint in requirement.constraints:
        if constraint.kind == "happy_path":
            continue
        if _session_constraint(constraint.statement):
            request(constraint.id, me)
            add(constraint.id, "assert", check="status_equals", expect="200")
            add(constraint.id, "assert", check="json_contains", expect=actor_email)
        else:
            rest.append(constraint)

    for constraint in rest:
        stmt = constraint.statement
        cid = constraint.id
        if _match(stmt, "duplicate"):
            request(cid, signup, creds)
            add(cid, "assert", check="status_equals", expect="409")
            add(cid, "assert", check="json_contains", expect="Email already registered")
        elif _match(stmt, "invalid password", "wrong password", "bad password"):
            request(cid, login, {"email": actor_email, "password": "not-the-password"})
            add(cid, "assert", check="status_equals", expect="401")
            add(cid, "assert", check="json_contains", expect="Invalid credentials")
        elif _unauthorized_constraint(stmt):
            request(cid, me, cookies=False)
            add(cid, "assert", check="status_equals", expect="401")
        else:
            add(cid, "assert", check="unsupported_constraint", expect=stmt)

    return {
        "requirement_id": requirement.id,
        "mode": "api",
        "runner": "http",
        "actor": {"email": actor_email, "password": password},
        "base_url": base_url,
        "routes": resolved,
        "steps": steps,
    }


def expand_state(
    requirement: Requirement,
    base_url: str,
    email: str | None = None,
    routes: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """HTTP setup plus SQL invariants. Durable state, not a dashboard."""
    actor_email = email or f"user-{uuid.uuid4().hex[:10]}@example.test"
    password = "correct-horse-battery"
    resolved = {**DEFAULT_API_ROUTES, **(routes or {})}
    signup = resolved["signup"]
    login = resolved["login"]
    steps: list[dict[str, Any]] = []
    n = 0

    def add(constraint_id: str, kind: str, **fields: Any) -> None:
        nonlocal n
        n += 1
        steps.append({"id": f"S-{n:03d}", "constraint_id": constraint_id, "kind": kind, **fields})

    def request(cid: str, spec: dict[str, str], json_body: dict | None = None) -> None:
        add(
            cid,
            "http_request",
            method=spec["method"],
            path=spec["path"],
            json=json_body,
            cookies=True,
        )

    def count_query(cid: str, table: str) -> None:
        add(
            cid,
            "sql_query",
            sql=f"SELECT COUNT(*) AS n FROM {table} WHERE email = :email",
            params={"email": actor_email},
        )
        add(cid, "assert", check="cell_equals", column="n", expect="1")

    creds = {"email": actor_email, "password": password}
    happy = requirement.happy_path()
    request(happy.id, signup, creds)
    add(happy.id, "assert", check="status_equals", expect="201")
    request(happy.id, login, creds)
    add(happy.id, "assert", check="status_equals", expect="200")

    for constraint in requirement.constraints:
        if constraint.kind == "happy_path":
            continue
        stmt = constraint.statement
        cid = constraint.id
        if _match(stmt, "stored durably", "durable", "user row"):
            count_query(cid, "users")
        elif _match(stmt, "identity"):
            count_query(cid, "identities")
        elif _match(stmt, "duplicate", "second row"):
            request(cid, signup, creds)
            add(cid, "assert", check="status_equals", expect="409")
            count_query(cid, "users")
        else:
            add(cid, "assert", check="unsupported_constraint", expect=stmt)

    return {
        "requirement_id": requirement.id,
        "mode": "state",
        "runner": "state",
        "actor": {"email": actor_email, "password": password},
        "base_url": base_url,
        "routes": resolved,
        "steps": steps,
    }
