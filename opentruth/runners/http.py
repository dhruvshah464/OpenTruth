"""Direct HTTP runner. Observations use kind=http; not an OpenAPI product."""

from __future__ import annotations

import json
import http.cookiejar
import urllib.error
import urllib.request
from typing import Any

from opentruth.assertions import evaluate
from opentruth.store import RunStore
from opentruth.verdicts import FAIL, INCONCLUSIVE


class HttpRunner:
    def __init__(self, store: RunStore, base_url: str):
        self.store = store
        self.base_url = base_url.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.authed = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.anon = urllib.request.build_opener()
        self.last: dict[str, Any] | None = None

    def _opener(self, cookies: bool) -> urllib.request.OpenerDirector:
        return self.authed if cookies else self.anon

    def _request(self, method: str, path: str, json_body: dict | None, cookies: bool) -> dict[str, Any]:
        url = path if path.startswith("http://") or path.startswith("https://") else self.base_url + path
        headers = {"Accept": "application/json"}
        data = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method.upper(), headers=headers)
        try:
            with self._opener(cookies).open(req, timeout=10) as resp:
                body = resp.read()
                return {
                    "method": method.upper(),
                    "url": url,
                    "status": int(resp.status),
                    "headers": dict(resp.headers.items()),
                    "body": body.decode("utf-8", errors="replace"),
                }
        except urllib.error.HTTPError as exc:
            body = exc.read()
            return {
                "method": method.upper(),
                "url": url,
                "status": int(exc.code),
                "headers": dict(exc.headers.items()) if exc.headers else {},
                "body": body.decode("utf-8", errors="replace"),
            }
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return {
                "method": method.upper(),
                "url": url,
                "status": None,
                "headers": {},
                "body": "",
                "error": str(exc),
            }

    def observe_exchange(
        self,
        constraint_id: str,
        action_type: str,
        target: str,
        exchange: dict[str, Any] | None,
        locator_error: str | None = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        action_id = self.store.allocate("A-")
        payload = json.dumps(
            {"action_id": action_id, "kind": "http", "exchange": exchange or {}},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        network_rel = self.store.write_blob(
            "network",
            f"{action_id}.json",
            (payload + "\n").encode("utf-8"),
        )
        self.store.append(
            "actions.jsonl",
            {
                "id": action_id,
                "constraint_id": constraint_id,
                "type": action_type,
                "target": target,
                "network_path": network_rel,
                "error": locator_error,
            },
        )
        observations: list[dict[str, Any]] = []

        def observe(kind: str, **fields: Any) -> dict[str, Any]:
            oid = self.store.allocate("O-")
            rec = self.store.append(
                "observations.jsonl",
                {"id": oid, "action_id": action_id, "constraint_id": constraint_id, "kind": kind, **fields},
            )
            observations.append(rec)
            return rec

        if exchange:
            observe(
                "http",
                value=str(exchange.get("status")),
                method=exchange.get("method"),
                url=exchange.get("url"),
                status=exchange.get("status"),
                error=exchange.get("error"),
            )
            observe("url", value=exchange.get("url"))
            observe("text", value=(exchange.get("body") or "")[:4000])
        observe("network", path=network_rel)
        return action_id, observations

    def run_step(self, step: dict[str, Any]) -> list[dict[str, Any]]:
        kind = step["kind"]
        cid = step["constraint_id"]
        emitted: list[dict[str, Any]] = []
        if kind == "http_request":
            target = f"{step.get('method', 'GET')} {step.get('path', '')}"
            cookies = step.get("cookies", True)
            try:
                exchange = self._request(step["method"], step["path"], step.get("json"), cookies=bool(cookies))
                error = exchange.get("error")
            except Exception as exc:
                exchange = None
                error = str(exc)
            self.last = exchange
            action_id, _obs = self.observe_exchange(cid, "http_request", target, exchange, locator_error=error)
            if error:
                assertion_id = self.store.allocate("E-")
                rec = self.store.append(
                    "assertions.jsonl",
                    {
                        "id": assertion_id,
                        "constraint_id": cid,
                        "action_id": action_id,
                        "step_id": step["id"],
                        "check": "action_executed",
                        "expect": kind,
                        "cites": [],
                        "result": INCONCLUSIVE,
                        "detail": error,
                        "artifact": None,
                    },
                )
                emitted.append(rec)
            return emitted

        if kind == "assert":
            action_id, observations = self.observe_exchange(
                cid, "assert", step.get("check", "assert"), self.last
            )
            result, cites, detail = evaluate(step["check"], str(step.get("expect", "")), observations)
            assertion_id = self.store.allocate("E-")
            artifact = None
            if result in (FAIL, INCONCLUSIVE) and self.last:
                artifact = self.store.write_blob(
                    "artifacts",
                    f"{assertion_id}.json",
                    (json.dumps(self.last, sort_keys=True, indent=2) + "\n").encode("utf-8"),
                )
            rec = self.store.append(
                "assertions.jsonl",
                {
                    "id": assertion_id,
                    "constraint_id": cid,
                    "action_id": action_id,
                    "step_id": step["id"],
                    "check": step["check"],
                    "expect": step.get("expect"),
                    "cites": cites,
                    "result": result,
                    "detail": detail,
                    "artifact": artifact,
                },
            )
            emitted.append(rec)
            return emitted

        assertion_id = self.store.allocate("E-")
        rec = self.store.append(
            "assertions.jsonl",
            {
                "id": assertion_id,
                "constraint_id": cid,
                "step_id": step["id"],
                "check": "action_executed",
                "expect": kind,
                "cites": [],
                "result": INCONCLUSIVE,
                "detail": f"http runner cannot execute {kind}",
                "artifact": None,
            },
        )
        emitted.append(rec)
        return emitted


def execute_http_plan(store: RunStore, plan: dict[str, Any]) -> list[dict[str, Any]]:
    runner = HttpRunner(store, plan["base_url"])
    assertions: list[dict[str, Any]] = []
    for step in plan["steps"]:
        assertions.extend(runner.run_step(step))
    return assertions
