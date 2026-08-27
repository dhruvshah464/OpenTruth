"""Evaluate plan assert steps against captured observations. Emit E-* records."""

from __future__ import annotations

from typing import Any, Callable

from opentruth.verdicts import FAIL, INCONCLUSIVE, PASS

CheckFn = Callable[[list[dict[str, Any]], str], tuple[str, list[str], str]]


def _texts(observations: list[dict[str, Any]]) -> list[tuple[str, str]]:
    out = []
    for obs in observations:
        if obs.get("kind") == "text" and obs.get("value"):
            out.append((obs["id"], str(obs["value"])))
    return out


def _urls(observations: list[dict[str, Any]]) -> list[tuple[str, str]]:
    out = []
    for obs in observations:
        if obs.get("kind") == "url" and obs.get("value"):
            out.append((obs["id"], str(obs["value"])))
    return out


def check_text_contains(observations: list[dict[str, Any]], expect: str) -> tuple[str, list[str], str]:
    hits = [(oid, text) for oid, text in _texts(observations) if expect in text]
    if hits:
        return PASS, [hits[0][0]], f"found {expect!r}"
    if _texts(observations):
        return FAIL, [oid for oid, _ in _texts(observations)][:1], f"missing {expect!r}"
    return INCONCLUSIVE, [], "no text observation"


def check_url_contains(observations: list[dict[str, Any]], expect: str) -> tuple[str, list[str], str]:
    hits = [(oid, url) for oid, url in _urls(observations) if expect in url]
    if hits:
        return PASS, [hits[0][0]], f"url contains {expect!r}"
    if _urls(observations):
        return FAIL, [oid for oid, _ in _urls(observations)][:1], f"url does not contain {expect!r}"
    return INCONCLUSIVE, [], "no url observation"


def check_unsupported(observations: list[dict[str, Any]], expect: str) -> tuple[str, list[str], str]:
    return INCONCLUSIVE, [], f"no planner for constraint: {expect}"


def check_status_equals(observations: list[dict[str, Any]], expect: str) -> tuple[str, list[str], str]:
    http_obs = [o for o in observations if o.get("kind") == "http"]
    if not http_obs:
        return INCONCLUSIVE, [], "no http observation"
    obs = http_obs[0]
    status = obs.get("status")
    if status is None:
        return INCONCLUSIVE, [obs["id"]], obs.get("error") or "http status missing"
    if str(status) == str(expect):
        return PASS, [obs["id"]], f"status {status}"
    return FAIL, [obs["id"]], f"status {status} != {expect}"


def check_json_contains(observations: list[dict[str, Any]], expect: str) -> tuple[str, list[str], str]:
    return check_text_contains(observations, expect)


CHECKS: dict[str, CheckFn] = {
    "text_contains": check_text_contains,
    "url_contains": check_url_contains,
    "status_equals": check_status_equals,
    "json_contains": check_json_contains,
    "unsupported_constraint": check_unsupported,
}


def _state_obs(observations: list[dict[str, Any]]) -> dict[str, Any] | None:
    for obs in observations:
        if obs.get("kind") == "state":
            return obs
    return None


def check_cell_equals(
    observations: list[dict[str, Any]],
    expect: str,
    column: str = "n",
) -> tuple[str, list[str], str]:
    obs = _state_obs(observations)
    if obs is None:
        return INCONCLUSIVE, [], "no state observation"
    if obs.get("error"):
        return INCONCLUSIVE, [obs["id"]], str(obs["error"])
    rows = obs.get("rows") or []
    if not rows:
        return FAIL, [obs["id"]], "no rows"
    value = rows[0].get(column)
    if str(value) == str(expect):
        return PASS, [obs["id"]], f"{column}={value}"
    return FAIL, [obs["id"]], f"{column}={value!r} != {expect!r}"


def evaluate(
    check: str,
    expect: str,
    observations: list[dict[str, Any]],
    extra: dict[str, Any] | None = None,
) -> tuple[str, list[str], str]:
    extra = extra or {}
    if check == "cell_equals":
        return check_cell_equals(observations, expect, str(extra.get("column") or "n"))
    fn = CHECKS.get(check)
    if fn is None:
        return INCONCLUSIVE, [], f"unknown check {check}"
    return fn(observations, expect)
