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
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from opentruth.requirement import Requirement

SUPPORTED_IR_VERSIONS = frozenset({1})
VERIFICATION_KEYS = frozenset({"version", "steps"})

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


@dataclass(frozen=True)
class IrStep:
    """One typed Verification IR step. Not yet an execution-plan step."""

    id: str
    constraint_id: str
    kind: str
    fields: dict[str, Any]


@dataclass(frozen=True)
class VerificationIr:
    """Versioned Verification IR after schema validation."""

    version: int
    steps: tuple[IrStep, ...]


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
    extra = [key for key in item if key not in META_KEYS and key not in KIND_KEYS]
    if extra:
        raise IrError(f"unknown verification step field: {extra[0]}")
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


def parse_verification(verification: Any) -> dict[str, Any]:
    """First pipeline stage: the verification block must be a mapping."""
    if not isinstance(verification, dict):
        raise IrError("verification must be a mapping")
    return dict(verification)


def validate_verification(
    parsed: dict[str, Any],
    requirement: Requirement,
    mode: str,
) -> VerificationIr:
    """Second pipeline stage: typed, versioned schema."""
    if mode not in ALLOWED_KINDS:
        raise IrError(f"unknown verify mode: {mode}")
    extra = [key for key in parsed if key not in VERIFICATION_KEYS]
    if extra:
        raise IrError(f"unknown verification field: {extra[0]}")
    version = _ir_version(parsed)
    steps_in = parsed.get("steps")
    if steps_in is None:
        steps_in = []
    if not isinstance(steps_in, list):
        raise IrError("verification.steps must be a list")
    allowed_ids = {c.id for c in requirement.constraints}
    steps: list[IrStep] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(steps_in, start=1):
        if not isinstance(item, dict):
            raise IrError(f"verification step {index} must be a mapping")
        sid = str(item.get("id") or "").strip()
        if not sid:
            raise IrError(f"verification step {index} id is required")
        if sid in seen_ids:
            raise IrError(f"duplicate verification step id: {sid}")
        seen_ids.add(sid)
        cid = str(item.get("constraint") or item.get("constraint_id") or "").strip()
        if not cid:
            raise IrError(f"verification step {sid} constraint is required")
        if cid not in allowed_ids:
            raise IrError(f"unknown constraint: {cid}")
        flat = _flatten_yaml_step(item)
        kind = str(flat.get("kind") or "")
        if kind in HOSTILE_KINDS:
            raise IrError(f"hostile step kind: {kind}")
        if kind not in ALLOWED_KINDS[mode]:
            raise IrError(f"step kind not allowed in {mode} mode: {kind or '(missing)'}")
        fields = {k: v for k, v in flat.items() if k not in META_KEYS}
        steps.append(IrStep(id=sid, constraint_id=cid, kind=kind, fields=fields))
    return VerificationIr(version=version, steps=tuple(steps))


def normalize_verification(ir: VerificationIr, actor: dict[str, str]) -> VerificationIr:
    """Third pipeline stage: substitute {{actor.*}} templates."""
    actor = {"email": actor["email"], "password": actor["password"]}
    steps = tuple(
        IrStep(
            id=step.id,
            constraint_id=step.constraint_id,
            kind=step.kind,
            fields=normalize_templates(step.fields, actor),
        )
        for step in ir.steps
    )
    return VerificationIr(version=ir.version, steps=steps)


def uncovered_constraint_ids(requirement: Requirement, plan: dict[str, Any]) -> list[str]:
    """A C-* is covered only when the plan has an assert (assertion evidence)."""
    covered = {
        str(step.get("constraint_id"))
        for step in plan.get("steps") or []
        if step.get("kind") == "assert" and step.get("constraint_id")
    }
    return [constraint.id for constraint in requirement.constraints if constraint.id not in covered]


def annotate_coverage(plan: dict[str, Any], requirement: Requirement) -> dict[str, Any]:
    """Stamp uncovered C-* onto plan.json. Missing coverage must not disappear."""
    annotated = dict(plan)
    annotated["uncovered_constraints"] = uncovered_constraint_ids(requirement, plan)
    return annotated


def compile_ir(
    ir: VerificationIr,
    requirement: Requirement,
    mode: str,
    base_url: str,
    actor: dict[str, str],
    routes: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Fourth pipeline stage: Verification IR → existing plan.json kinds."""
    allowed_ids = {c.id for c in requirement.constraints}
    actor = {"email": actor["email"], "password": actor["password"]}
    cleaned: list[dict[str, Any]] = []
    for step in ir.steps:
        raw = {"kind": step.kind, "constraint_id": step.constraint_id, **step.fields}
        compiled = sanitize_step(raw, allowed_ids, mode, base_url, strict=True)
        if compiled is None:
            raise IrError(f"verification step {step.id} failed the allowlist")
        compiled["id"] = step.id
        cleaned.append(compiled)
    plan = {
        "requirement_id": requirement.id,
        "mode": mode,
        "runner": RUNNER[mode],
        "actor": actor,
        "base_url": base_url,
        "routes": routes or {},
        "steps": cleaned,
        "planner": "ir",
        "verification_version": ir.version,
    }
    return annotate_coverage(plan, requirement)


def compile_verification(
    verification: Any,
    requirement: Requirement,
    mode: str,
    base_url: str,
    actor: dict[str, str],
    routes: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Parse → validate schema → normalize → compile → plan.json."""
    parsed = parse_verification(verification)
    ir = validate_verification(parsed, requirement, mode)
    ir = normalize_verification(ir, actor)
    return compile_ir(ir, requirement, mode, base_url, actor, routes)
