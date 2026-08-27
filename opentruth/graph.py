"""In-memory evidence graph loaded from a sealed run."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from opentruth.store import IntegrityError, load_json, load_jsonl, verify_manifest


class EvidenceGraph:
    def __init__(self, run_dir: Path, manifest: dict[str, Any]):
        self.run_dir = run_dir
        self.manifest = manifest
        self.integrity_ok = True
        self.integrity_error: str | None = None
        self.requirements = load_json(run_dir / "requirements.json")
        self.plan = load_json(run_dir / "plan.json")
        self.verdict = load_json(run_dir / "verdict.json")
        self.actions = load_jsonl(run_dir / "actions.jsonl")
        self.observations = load_jsonl(run_dir / "observations.jsonl")
        self.assertions = load_jsonl(run_dir / "assertions.jsonl")
        self.nodes: dict[str, dict[str, Any]] = {}
        self.children: dict[str, list[str]] = defaultdict(list)
        self._index()

    def _put(self, node_id: str, graph_kind: str, record: dict[str, Any]) -> dict[str, Any]:
        node = {**record, "kind": graph_kind, "payload_kind": record.get("kind")}
        self.nodes[node_id] = node
        return node

    def _index(self) -> None:
        reqs = self.requirements.get("requirements") or [self.requirements]
        if isinstance(self.requirements, dict) and "id" in self.requirements:
            reqs = [self.requirements]
        for req in reqs:
            self._put(req["id"], "requirement", req)
            for constraint in req.get("constraints") or []:
                self._put(constraint["id"], "constraint", constraint)
                self.children[req["id"]].append(constraint["id"])
        for action in self.actions:
            self._put(action["id"], "action", action)
            self.children[action["constraint_id"]].append(action["id"])
        for obs in self.observations:
            if "id" not in obs:
                continue
            self._put(obs["id"], "observation", obs)
            parent = obs.get("action_id") or obs.get("constraint_id")
            if parent:
                self.children[parent].append(obs["id"])
        for assertion in self.assertions:
            self._put(assertion["id"], "assertion", assertion)
            parent = assertion.get("action_id") or assertion["constraint_id"]
            self.children[parent].append(assertion["id"])

    def get(self, node_id: str) -> dict[str, Any]:
        if node_id not in self.nodes:
            raise KeyError(node_id)
        return self.nodes[node_id]

    def constraint_result(self, constraint_id: str) -> str | None:
        for req in self.verdict.get("requirements") or []:
            for row in req.get("constraints") or []:
                if row["id"] == constraint_id:
                    return row["result"]
        return None

    def requirement_verdict(self, requirement_id: str) -> dict[str, Any] | None:
        for req in self.verdict.get("requirements") or []:
            if req["id"] == requirement_id:
                return req
        return None


def load_graph(run_dir: Path) -> EvidenceGraph:
    run_dir = Path(run_dir)
    try:
        manifest = verify_manifest(run_dir)
        graph = EvidenceGraph(run_dir, manifest)
        return graph
    except IntegrityError as exc:
        # Still load for diagnosis, but mark untrustworthy.
        manifest_path = run_dir / "manifest.json"
        manifest = load_json(manifest_path) if manifest_path.is_file() else {}
        graph = EvidenceGraph(run_dir, manifest)
        graph.integrity_ok = False
        graph.integrity_error = str(exc)
        return graph
