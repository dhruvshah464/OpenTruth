"""Playwright browser runner. Each interaction is an A-* with O-* observations."""

from __future__ import annotations

import json
from typing import Any

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeout, sync_playwright

from opentruth.assertions import evaluate
from opentruth.store import RunStore
from opentruth.verdicts import FAIL, INCONCLUSIVE


def _page_text(page: Page) -> str:
    try:
        return page.inner_text("body")
    except Exception:
        return ""


class BrowserRunner:
    def __init__(self, store: RunStore, page: Page):
        self.store = store
        self.page = page
        self._pending: list[dict[str, Any]] = []
        self.page.on("request", self._on_request)
        self.page.on("response", self._on_response)

    def _on_request(self, request: Any) -> None:
        self._pending.append({"method": request.method, "url": request.url, "phase": "request"})

    def _on_response(self, response: Any) -> None:
        self._pending.append(
            {
                "method": response.request.method,
                "url": response.url,
                "phase": "response",
                "status": response.status,
            }
        )

    def drain_network(self) -> list[dict[str, Any]]:
        events = list(self._pending)
        self._pending.clear()
        return events

    def observe_action(
        self,
        constraint_id: str,
        action_type: str,
        target: str,
        locator_error: str | None = None,
    ) -> tuple[str, list[dict[str, Any]]]:
        action_id = self.store.allocate("A-")
        network_events = self.drain_network()
        payload = json.dumps(
            {"action_id": action_id, "requests": network_events},
            sort_keys=True,
            separators=(",", ":"),
        )
        network_rel = self.store.write_blob(
            "network",
            f"{action_id}.json",
            (payload + "\n").encode("utf-8"),
        )
        action = self.store.append(
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

        try:
            png = self.page.screenshot(full_page=True)
            rel = self.store.write_blob("screenshots", f"{action_id}.png", png)
            observe("screenshot", path=rel)
        except Exception as exc:
            observe("screenshot", path=None, error=str(exc))
        try:
            observe("url", value=self.page.url)
        except Exception as exc:
            observe("url", value=None, error=str(exc))
        observe("text", value=_page_text(self.page)[:4000])
        observe("network", path=network_rel)
        _ = action
        return action_id, observations

    def run_step(self, step: dict[str, Any]) -> list[dict[str, Any]]:
        kind = step["kind"]
        cid = step["constraint_id"]
        emitted: list[dict[str, Any]] = []
        if kind == "assert":
            # Observe current page, then evaluate.
            action_id, observations = self.observe_action(cid, "assert", step.get("check", "assert"))
            result, cites, detail = evaluate(step["check"], step.get("expect", ""), observations)
            assertion_id = self.store.allocate("E-")
            artifact = None
            if result in (FAIL, INCONCLUSIVE):
                html = self.page.content().encode("utf-8")
                artifact = self.store.write_blob("artifacts", f"{assertion_id}.html", html)
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

        error = None
        target = ""
        try:
            if kind == "navigate":
                target = step["url"]
                self.page.goto(target, wait_until="domcontentloaded")
            elif kind == "fill":
                target = step["label"]
                self.page.get_by_label(step["label"]).fill(step["value"])
            elif kind == "click":
                target = step.get("name") or step.get("role", "click")
                locator = self.page.get_by_role(step.get("role", "button"), name=step["name"])
                locator.click()
                self.page.wait_for_load_state("domcontentloaded")
            elif kind == "reload":
                target = self.page.url
                self.page.reload(wait_until="domcontentloaded")
            elif kind == "clear_cookies":
                target = "cookies"
                self.page.context.clear_cookies()
            else:
                error = f"unknown step kind {kind}"
        except PlaywrightTimeout as exc:
            error = f"timeout: {exc}"
        except Exception as exc:
            error = str(exc)
        action_id, _observations = self.observe_action(cid, kind, target, locator_error=error)
        if error and kind in {"fill", "click", "navigate", "reload", "clear_cookies"}:
            assertion_id = self.store.allocate("E-")
            html = b""
            try:
                html = self.page.content().encode("utf-8")
            except Exception:
                pass
            artifact = None
            if html:
                artifact = self.store.write_blob("artifacts", f"{assertion_id}.html", html)
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
                    "artifact": artifact,
                },
            )
            emitted.append(rec)
        return emitted


def execute_plan(store: RunStore, plan: dict[str, Any]) -> list[dict[str, Any]]:
    assertions: list[dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        runner = BrowserRunner(store, page)
        try:
            for step in plan["steps"]:
                assertions.extend(runner.run_step(step))
        finally:
            context.close()
            browser.close()
    return assertions
