"""Versioned Verification IR.

Requirement YAML is not the IR. This module owns:

    YAML verification block
        → parse
        → validate schema
        → normalize
        → compile
        → existing plan.json step kinds

The same allowlist gates LLM proposals. Hostile IR raises; it does not
fall through to expand() or a fake PROVEN.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from opentruth.requirement import Requirement

SUPPORTED_IR_VERSIONS = frozenset({1})

HOSTILE_KINDS = frozenset(
    {"shell", "eval", "execute", "run", "write", "python", "subprocess", "javascript", "js"}
)
ALLOWED_KINDS = {
    "browser": frozenset({"navigate", "fill", "click", "reload", "clear_cookies", "assert"}),
    "api": frozenset({"http_request", "assert"}),
    "state": frozenset({"http_request", "sql_query", "assert"}),
}
ALLOWED_CHECKS = {
    "browser": frozenset({"url_contains", "text_contains", "unsupported_constraint"}),
    "api": frozenset({"status_equals", "json_contains", "text_contains", "unsupported_constraint"}),
    "state": frozenset(
        {"status_equals", "json_contains", "text_contains", "cell_equals", "unsupported_constraint"}
    ),
}
RUNNER = {"browser": "browser", "api": "http", "state": "state"}
SQL_OK = re.compile(
    r"^SELECT COUNT\(\*\) AS n FROM (users|identities) WHERE email = :email$",
    re.IGNORECASE,
)
METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})
KIND_KEYS = frozenset().union(*ALLOWED_KINDS.values()) | HOSTILE_KINDS
META_KEYS = frozenset({"id", "constraint", "constraint_id", "kind"})


class IrError(ValueError):
    """Verification IR is not executable."""


def has_declared_ir(verification: Any) -> bool:
    return verification is not None


def default_actor(email: str | None = None) -> dict[str, str]:
    return {
        "email": email or f"user-{uuid4().hex[:10]}@example.test",
        "password": "correct-horse-battery",
    }


def _plain(value: Any, depth: int = 0) -> Any:
    if depth > 4:
        raise IrError("json too nested")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        if len(value) > 20:
            raise IrError("json object too large")
        return {str(k)[:64]: _plain(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        if len(value) > 20:
            raise IrError("json list too large")
        return [_plain(v, depth + 1) for v in value]
    raise IrError("json value not serializable")


def normalize_templates(value: Any, actor: dict[str, str], depth: int = 0) -> Any:
    if depth > 6:
        raise IrError("template too nested")
    if isinstance(value, str):
        return (
            value.replace("{{actor.email}}", actor["email"]).replace(
                "{{actor.password}}", actor["password"]
            )
        )
    if isinstance(value, dict):
        return {k: normalize_templates(v, actor, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        return [normalize_templates(v, actor, depth + 1) for v in value]
    return value


def sanitize_step(
    raw: dict[str, Any],
    allowed_ids: set[str],
    mode: str,
    base_url: str,
    *,
    strict: bool = False,
) -> dict[str, Any] | None:
    kind = str(raw.get("kind") or "")
    if kind in HOSTILE_KINDS:
        raise IrError(f"hostile step kind: {kind}")
    if kind not in ALLOWED_KINDS[mode]:
        if strict:
            raise IrError(f"step kind not allowed in {mode} mode: {kind or '(missing)'}")
        return None
    cid = str(raw.get("constraint_id") or raw.get("constraint") or "")
    if cid not in allowed_ids:
        if strict:
            raise IrError(f"unknown constraint: {cid or '(missing)'}")
        return None
    step: dict[str, Any] = {"kind": kind, "constraint_id": cid}
    if kind == "assert":
        check = str(raw.get("check") or "")
        if check not in ALLOWED_CHECKS[mode]:
            if strict:
                raise IrError(f"assert check not allowed in {mode} mode: {check or '(missing)'}")
            return None
        step["check"] = check
        step["expect"] = str(raw.get("expect", ""))
        if check == "cell_equals":
            step["column"] = str(raw.get("column") or "n")
        return step
    if kind == "navigate":
        url = str(raw.get("url") or "")
        if url.startswith("/"):
            url = base_url.rstrip("/") + url
        if ".." in url or "\n" in url:
            if strict:
                raise IrError("navigate url is not allowed")
            return None
        if not url.startswith(base_url) or not url.startswith("http"):
            if strict:
                raise IrError("navigate url must stay on the declared base_url")
            return None
        step["url"] = url
        return step
    if kind == "fill":
        label = str(raw.get("label") or "")
        if not label:
            if strict:
                raise IrError("fill step needs a label")
            return None
        step["label"] = label
        step["value"] = str(raw.get("value") or "")
        return step
    if kind == "click":
        name = str(raw.get("name") or "")
        if not name:
            if strict:
                raise IrError("click step needs a name")
            return None
        step["role"] = str(raw.get("role") or "button")
        step["name"] = name
        return step
    if kind in {"reload", "clear_cookies"}:
        return step
    if kind == "http_request":
        method = str(raw.get("method") or "GET").upper()
        path = str(raw.get("path") or "")
        if method not in METHODS or not path.startswith("/") or ".." in path or len(path) > 200 or "\n" in path:
            if strict:
                raise IrError(f"http_request is not allowed: {method} {path}")
            return None
        step["method"] = method
        step["path"] = path
        if "json" in raw:
            step["json"] = _plain(raw.get("json"))
        else:
            step["json"] = None
        step["cookies"] = bool(raw.get("cookies", True))
        return step
    if kind == "sql_query":
        sql = " ".join(str(raw.get("sql") or "").split())
        if not SQL_OK.match(sql):
            if strict:
                raise IrError("sql_query must be SELECT COUNT(*) AS n FROM users|identities WHERE email = :email")
            return None
        params = raw.get("params") or {}
        if not isinstance(params, dict):
            if strict:
                raise IrError("sql_query params must be a mapping")
            return None
        email = str(params.get("email") or "")
        if not email:
            if strict:
                raise IrError("sql_query params.email is required")
            return None
        step["sql"] = sql
        step["params"] = {"email": email}
        return step
    if strict:
        raise IrError(f"unhandled step kind: {kind}")
    return None


def _flatten_yaml_step(item: dict[str, Any]) -> dict[str, Any]:
    kind_fields = [key for key in item if key in KIND_KEYS]
    declared_kind = str(item.get("kind") or "")
    if declared_kind in HOSTILE_KINDS:
        raise IrError(f"hostile step kind: {declared_kind}")
    if kind_fields:
        hostile = [key for key in kind_fields if key in HOSTILE_KINDS]
        if hostile:
            raise IrError(f"hostile step kind: {hostile[0]}")
        if declared_kind and declared_kind not in kind_fields:
            raise IrError(f"step kind mismatch: {declared_kind}")
        if len(kind_fields) != 1:
            raise IrError("each verification step must declare exactly one kind")
        kind = kind_fields[0]
        payload = item.get(kind)
        flat: dict[str, Any] = {k: v for k, v in item.items() if k in META_KEYS}
        flat["kind"] = kind
        if payload is True or payload is None:
            pass
        elif isinstance(payload, dict):
            for key, value in payload.items():
                if key in META_KEYS:
                    continue
                flat[key] = value
        else:
            raise IrError(f"{kind} payload must be a mapping")
        return flat
    if declared_kind:
        return dict(item)
    extra = [key for key in item if key not in META_KEYS]
    if extra:
        raise IrError(f"unknown verification step field: {extra[0]}")
    raise IrError("verification step is missing a kind")


def _ir_version(raw: dict[str, Any]) -> int:
    if "version" not in raw:
        raise IrError("verification.version is required")
    value = raw.get("version")
    try:
        version = int(value)
    except (TypeError, ValueError) as exc:
        raise IrError(f"unsupported verification.version: {value!r}") from exc
    if version not in SUPPORTED_IR_VERSIONS:
        raise IrError(f"unsupported verification.version: {version}")
    return version


def compile_verification(
    verification: Any,
    requirement: Requirement,
    mode: str,
    base_url: str,
    actor: dict[str, str],
    routes: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Parse, validate, normalize, and compile a declared Verification IR."""
    if mode not in ALLOWED_KINDS:
        raise IrError(f"unknown verify mode: {mode}")
    if not isinstance(verification, dict):
        raise IrError("verification must be a mapping")
    version = _ir_version(verification)
    steps_in = verification.get("steps")
    if steps_in is None:
        steps_in = []
    if not isinstance(steps_in, list):
        raise IrError("verification.steps must be a list")
    allowed_ids = {c.id for c in requirement.constraints}
    actor = {"email": actor["email"], "password": actor["password"]}
    cleaned: list[dict[str, Any]] = []
    for index, item in enumerate(steps_in, start=1):
        if not isinstance(item, dict):
            raise IrError(f"verification step {index} must be a mapping")
        item = normalize_templates(item, actor)
        flat = _flatten_yaml_step(item)
        step = sanitize_step(flat, allowed_ids, mode, base_url, strict=True)
        if step is None:
            raise IrError(f"verification step {index} failed the allowlist")
        declared = str(item.get("id") or "").strip()
        step["id"] = declared if declared else f"S-{index:03d}"
        cleaned.append(step)
    seen: set[str] = set()
    for i, step in enumerate(cleaned, start=1):
        sid = str(step["id"])
        if sid in seen:
            step["id"] = f"S-{i:03d}"
        seen.add(step["id"])
    return {
        "requirement_id": requirement.id,
        "mode": mode,
        "runner": RUNNER[mode],
        "actor": actor,
        "base_url": base_url,
        "routes": routes or {},
        "steps": cleaned,
        "planner": "ir",
        "verification_version": version,
    }
