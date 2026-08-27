"""Change/diff proof: compare two sealed runs. Cites both run IDs."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from opentruth.graph import EvidenceGraph, load_graph
from opentruth.store import RunStore, dumps
from opentruth.verdicts import (
    CHANGED,
    FAIL,
    FAILED,
    IMPROVED,
    INCONCLUSIVE,
    INCONCLUSIVE_V,
    NOT_PROVEN,
    PARTIALLY_PROVEN,
    PASS,
    PROVEN,
    REGRESSED,
    UNCHANGED,
    delta,
    roll_diff,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _ref(graph: EvidenceGraph) -> dict[str, Any]:
    manifest_path = graph.run_dir / "manifest.json"
    return {
        "run_id": graph.manifest.get("run_id") or graph.run_dir.name,
        "path": str(graph.run_dir),
        "manifest_sha256": _sha256(manifest_path) if manifest_path.is_file() else None,
        "integrity_ok": graph.integrity_ok,
        "integrity_error": graph.integrity_error,
        "mode": (graph.plan or {}).get("mode"),
    }


def _constraint_rows(graph: EvidenceGraph) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for req in graph.verdict.get("requirements") or []:
        for row in req.get("constraints") or []:
            rows.append(row)
    return rows


def _requirement_block(graph: EvidenceGraph) -> dict[str, Any]:
    reqs = graph.verdict.get("requirements") or []
    if reqs:
        return reqs[0]
    raw = graph.requirements
    if isinstance(raw, dict) and "id" in raw:
        return {"id": raw["id"], "statement": raw.get("statement"), "constraints": raw.get("constraints") or []}
    return {"id": "R-1", "statement": "", "constraints": []}


def diff_runs(left_dir: Path, right_dir: Path, runs_root: Path) -> dict[str, Any]:
    left = load_graph(Path(left_dir))
    right = load_graph(Path(right_dir))
    left_ref = _ref(left)
    right_ref = _ref(right)
    integrity_ok = bool(left.integrity_ok and right.integrity_ok)

    left_rows = {row["id"]: row for row in _constraint_rows(left)}
    right_rows = {row["id"]: row for row in _constraint_rows(right)}
    ids = list(dict.fromkeys([*left_rows.keys(), *right_rows.keys()]))

    right_block = _requirement_block(right)
    left_block = _requirement_block(left)
    statement = right_block.get("statement") or left_block.get("statement") or ""
    req_id = right_block.get("id") or left_block.get("id") or "R-1"

    store = RunStore(Path(runs_root))
    store.create()

    constraints_out: list[dict[str, Any]] = []
    for cid in ids:
        lrow = left_rows.get(cid) or {}
        rrow = right_rows.get(cid) or {}
        left_res = lrow.get("result")
        right_res = rrow.get("result")
        dlt = delta(left_res, right_res)
        statement_c = rrow.get("statement") or lrow.get("statement") or cid
        kind = rrow.get("kind") or lrow.get("kind") or "constraint"
        constraints_out.append(
            {
                "id": cid,
                "kind": kind,
                "statement": statement_c,
                "result": dlt,
                "left": left_res,
                "right": right_res,
            }
        )

    req_json = {
        "id": req_id,
        "statement": statement,
        "constraints": [
            {
                "id": c["id"],
                "requirement_id": req_id,
                "statement": c["statement"],
                "kind": c["kind"],
            }
            for c in constraints_out
        ],
    }
    store.write_json("requirements.json", req_json)
    plan = {
        "mode": "diff",
        "runner": "diff",
        "requirement_id": req_id,
        "left": left_ref,
        "right": right_ref,
        "steps": [
            {"id": f"S-{i:03d}", "constraint_id": c["id"], "kind": "compare"}
            for i, c in enumerate(constraints_out, start=1)
        ],
    }
    store.write_json("plan.json", plan)

    blob = store.write_blob(
        "artifacts",
        "compare.json",
        (dumps({"left": left_ref, "right": right_ref, "constraints": constraints_out}) + "\n").encode("utf-8"),
    )

    for row in constraints_out:
        cid = row["id"]
        action_id = store.allocate("A-")
        store.append(
            "actions.jsonl",
            {
                "id": action_id,
                "constraint_id": cid,
                "type": "compare",
                "target": f"{left_ref['run_id']} → {right_ref['run_id']}",
                "network_path": blob,
                "error": None,
            },
        )
        o_left = store.allocate("O-")
        store.append(
            "observations.jsonl",
            {
                "id": o_left,
                "action_id": action_id,
                "constraint_id": cid,
                "kind": "diff",
                "side": "left",
                "value": row["left"],
                "run_id": left_ref["run_id"],
                "path": left_ref["path"],
                "manifest_sha256": left_ref["manifest_sha256"],
            },
        )
        o_right = store.allocate("O-")
        store.append(
            "observations.jsonl",
            {
                "id": o_right,
                "action_id": action_id,
                "constraint_id": cid,
                "kind": "diff",
                "side": "right",
                "value": row["right"],
                "run_id": right_ref["run_id"],
                "path": right_ref["path"],
                "manifest_sha256": right_ref["manifest_sha256"],
            },
        )
        if row["result"] == REGRESSED:
            e_result = FAIL
        elif row["result"] == CHANGED:
            e_result = INCONCLUSIVE
        else:
            e_result = PASS
        eid = store.allocate("E-")
        store.append(
            "assertions.jsonl",
            {
                "id": eid,
                "constraint_id": cid,
                "action_id": action_id,
                "step_id": None,
                "check": "delta",
                "expect": "no_regression",
                "cites": [o_left, o_right],
                "result": e_result,
                "detail": f"{row['left']} → {row['right']} ({row['result']})",
                "artifact": blob,
            },
        )

    deltas = [c["result"] for c in constraints_out]
    rights = [c["right"] for c in constraints_out]
    req_verdict = roll_diff(deltas, rights, integrity_ok)
    improved = sum(1 for d in deltas if d == IMPROVED)
    regressed = sum(1 for d in deltas if d == REGRESSED)
    unchanged = sum(1 for d in deltas if d == UNCHANGED)
    changed = sum(1 for d in deltas if d == CHANGED)
    right_pass = sum(1 for r in rights if r == PASS)
    conf = (right_pass / len(rights)) if rights else 0.0

    verdict = {
        "run_id": store.run_id,
        "mode": "diff",
        "left": left_ref,
        "right": right_ref,
        "requirements": [
            {
                "id": req_id,
                "statement": statement,
                "verdict": req_verdict,
                "confidence": conf,
                "constraints": constraints_out,
            }
        ],
        "summary": {
            "requirements": 1,
            "proven": int(req_verdict == PROVEN),
            "partially_proven": int(req_verdict == PARTIALLY_PROVEN),
            "failed": int(req_verdict == FAILED),
            "not_proven": int(req_verdict == NOT_PROVEN),
            "inconclusive": int(req_verdict == INCONCLUSIVE_V),
            "confidence": conf,
            "critical_failures": int(regressed > 0),
            "improved": improved,
            "regressed": regressed,
            "unchanged": unchanged,
            "changed": changed,
        },
    }
    store.write_json("verdict.json", verdict)
    store.seal()
    return {"run_dir": store.root, "run_id": store.run_id, "verdict": verdict}


def resolve_run_arg(value: str, search_from: Path) -> Path:
    path = Path(value)
    if path.is_dir() and (path / "manifest.json").is_file():
        return path.resolve()
    candidate = search_from / ".opentruth" / "runs" / value
    if candidate.is_dir() and (candidate / "manifest.json").is_file():
        return candidate.resolve()
    raise FileNotFoundError(f"sealed run not found: {value}")
