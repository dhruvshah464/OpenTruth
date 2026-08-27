"""LLM may propose plan.json. It never writes verdict.json.

Default verify stays deterministic. If the model is down or the proposal
fails the IR allowlist, fall back to expand() so M1–M5 still work.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Protocol

from opentruth.ir import (
    ALLOWED_CHECKS,
    ALLOWED_KINDS,
    IrError,
    RUNNER,
    compile_verification,
    default_actor,
    has_declared_ir,
    sanitize_step,
)
from opentruth.planning import expand
from opentruth.requirement import Requirement

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"

PlanError = IrError


class PlanProposer(Protocol):
    model: str

    def propose(self, prompt: str) -> str: ...


class HttpChatProposer:
    """OpenAI-compatible chat completions. Stdlib only; not a product surface."""

    def __init__(self, base_url: str, api_key: str, model: str, timeout: float = 45.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    @classmethod
    def from_env(
        cls,
        model: str | None = None,
        base_url: str | None = None,
        env: dict[str, str] | None = None,
    ) -> HttpChatProposer:
        env = os.environ if env is None else env
        key = (env.get("OPENTRUTH_LLM_API_KEY") or env.get("OPENAI_API_KEY") or "").strip()
        if not key:
            raise PlanError("OPENTRUTH_LLM_API_KEY missing")
        return cls(
            base_url=base_url
            or env.get("OPENTRUTH_LLM_BASE_URL")
            or DEFAULT_BASE_URL,
            api_key=key,
            model=model or env.get("OPENTRUTH_LLM_MODEL") or DEFAULT_MODEL,
        )

    def propose(self, prompt: str) -> str:
        url = f"{self.base_url}/chat/completions"
        payload = json.dumps(
            {
                "model": self.model,
                "temperature": 0,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            raise PlanError(f"llm request failed: {exc}") from exc
        try:
            return str(body["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as exc:
            raise PlanError(f"llm response missing content: {exc}") from exc


SYSTEM_PROMPT = """You propose an OpenTruth plan IR. Return one JSON object only.
The JSON may include requirement_id, mode, runner, actor, base_url, routes, steps.
Every step must have kind and constraint_id. Do not include verdict, confidence,
result, summary, assertions, or pass/fail. You do not decide if the software works.
The runner will execute the plan and a separate module will derive the verdict."""


def parse_json_object(text: str) -> dict[str, Any]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        raise PlanError("llm output is not a JSON object")
    try:
        obj = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as exc:
        raise PlanError(f"llm output is not JSON: {exc}") from exc
    if not isinstance(obj, dict):
        raise PlanError("llm output is not a JSON object")
    return obj


def render_prompt(
    requirement: Requirement,
    mode: str,
    base_url: str,
    actor: dict[str, str],
    routes: dict[str, dict[str, str]] | None,
) -> str:
    kinds = sorted(ALLOWED_KINDS[mode])
    checks = sorted(ALLOWED_CHECKS[mode])
    return json.dumps(
        {
            "mode": mode,
            "base_url": base_url,
            "actor": actor,
            "routes": routes or {},
            "allowed_step_kinds": kinds,
            "allowed_assert_checks": checks,
            "requirement": requirement.to_json(),
            "instructions": (
                "Propose steps that operate the running app against each C-* id. "
                "Use actor.email and actor.password. HTTP paths start with /. "
                "SQL must be exactly: SELECT COUNT(*) AS n FROM users|identities WHERE email = :email"
            ),
        },
        indent=2,
        sort_keys=True,
    )


def sanitize_plan(
    raw: dict[str, Any] | str,
    requirement: Requirement,
    mode: str,
    base_url: str,
    actor: dict[str, str],
    routes: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    data = parse_json_object(raw) if isinstance(raw, str) else raw
    if not isinstance(data, dict):
        raise PlanError("plan is not an object")
    steps_in = data.get("steps")
    if not isinstance(steps_in, list) or not steps_in:
        raise PlanError("plan has no steps")
    allowed_ids = {c.id for c in requirement.constraints}
    cleaned: list[dict[str, Any]] = []
    for item in steps_in:
        if not isinstance(item, dict):
            continue
        step = sanitize_step(item, allowed_ids, mode, base_url)
        if step is None:
            continue
        cleaned.append(step)
    if not cleaned:
        raise PlanError("no valid steps after allowlist")
    for i, step in enumerate(cleaned, start=1):
        step["id"] = f"S-{i:03d}"
    return {
        "requirement_id": requirement.id,
        "mode": mode,
        "runner": RUNNER[mode],
        "actor": {"email": actor["email"], "password": actor["password"]},
        "base_url": base_url,
        "routes": routes or {},
        "steps": cleaned,
    }


def resolve_proposer(
    llm: PlanProposer | bool | None,
    model: str | None = None,
    base_url: str | None = None,
) -> PlanProposer | None:
    if llm is None or llm is False:
        return None
    if llm is True:
        return HttpChatProposer.from_env(model=model, base_url=base_url)
    return llm


def build_plan(
    requirement: Requirement,
    base_url: str,
    mode: str,
    routes: dict[str, dict[str, str]] | None = None,
    llm: PlanProposer | bool | None = None,
    llm_model: str | None = None,
    llm_base_url: str | None = None,
    email: str | None = None,
    verification: Any = None,
) -> dict[str, Any]:
    actor = default_actor(email)
    if has_declared_ir(verification):
        return compile_verification(verification, requirement, mode, base_url, actor, routes)
    proposer = None
    try:
        proposer = resolve_proposer(llm, model=llm_model, base_url=llm_base_url)
    except PlanError as exc:
        plan = expand(requirement, base_url, email=actor["email"], mode=mode, routes=routes)
        plan["planner"] = "deterministic"
        plan["planner_requested"] = "llm"
        plan["llm_error"] = str(exc)[:500]
        return plan
    if proposer is None:
        plan = expand(requirement, base_url, email=actor["email"], mode=mode, routes=routes)
        plan["planner"] = "deterministic"
        return plan
    try:
        prompt = render_prompt(requirement, mode, base_url, actor, routes)
        raw = proposer.propose(prompt)
        plan = sanitize_plan(raw, requirement, mode, base_url, actor, routes)
        plan["planner"] = "llm"
        plan["planner_model"] = getattr(proposer, "model", "unknown")
        return plan
    except Exception as exc:
        plan = expand(requirement, base_url, email=actor["email"], mode=mode, routes=routes)
        plan["planner"] = "deterministic"
        plan["planner_requested"] = "llm"
        plan["llm_error"] = str(exc)[:500]
        return plan
