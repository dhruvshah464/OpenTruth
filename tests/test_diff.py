from pathlib import Path

import pytest

from opentruth.cli import main
from opentruth.diff import diff_runs, resolve_run_arg
from opentruth.engine import verify
from opentruth.explain import explain_text, format_verify_summary
from opentruth.store import RunStore, load_json, load_jsonl, verify_manifest
from opentruth.verdicts import FAILED, IMPROVED, INCONCLUSIVE_V, NOT_PROVEN, PROVEN, REGRESSED, UNCHANGED

ROOT = Path(__file__).resolve().parents[1]
MINIAUTH = ROOT / "examples" / "miniauth"


def _make_run(runs_root: Path, results: dict[str, str]) -> Path:
    store = RunStore(runs_root)
    store.create()
    constraints = [
        {
            "id": cid,
            "requirement_id": "R-1",
            "statement": cid,
            "kind": "happy_path" if cid == "C-0" else "constraint",
        }
        for cid in results
    ]
    store.write_json(
        "requirements.json",
        {"id": "R-1", "statement": "auth", "constraints": constraints},
    )
    store.write_json("plan.json", {"mode": "api", "requirement_id": "R-1", "steps": []})
    for cid, result in results.items():
        aid = store.allocate("A-")
        store.append("actions.jsonl", {"id": aid, "constraint_id": cid, "type": "noop", "target": "/"})
        oid = store.allocate("O-")
        store.append(
            "observations.jsonl",
            {"id": oid, "action_id": aid, "constraint_id": cid, "kind": "http", "value": result},
        )
        eid = store.allocate("E-")
        store.append(
            "assertions.jsonl",
            {
                "id": eid,
                "constraint_id": cid,
                "action_id": aid,
                "check": "status",
                "expect": "pass",
                "cites": [oid],
                "result": result,
                "detail": "",
            },
        )
    store.write_json(
        "verdict.json",
        {
            "run_id": store.run_id,
            "requirements": [
                {
                    "id": "R-1",
                    "statement": "auth",
                    "verdict": "synthetic",
                    "constraints": [
                        {
                            "id": cid,
                            "kind": "happy_path" if cid == "C-0" else "constraint",
                            "statement": cid,
                            "result": res,
                        }
                        for cid, res in results.items()
                    ],
                }
            ],
            "summary": {},
        },
    )
    store.seal()
    return store.root


def _constraint_map(verdict: dict) -> dict[str, dict]:
    req = verdict["requirements"][0]
    return {row["id"]: row for row in req["constraints"]}


def test_diff_synthetic_improved_is_proven(tmp_path: Path) -> None:
    left = _make_run(tmp_path, {"C-0": "pass", "C-3": "fail"})
    right = _make_run(tmp_path, {"C-0": "pass", "C-3": "pass"})
    result = diff_runs(left, right, tmp_path / "diffs")
    verify_manifest(result["run_dir"])
    req = result["verdict"]["requirements"][0]
    assert req["verdict"] == PROVEN
    rows = _constraint_map(result["verdict"])
    assert rows["C-0"]["result"] == UNCHANGED
    assert rows["C-3"]["result"] == IMPROVED
    assert result["verdict"]["summary"]["improved"] == 1
    assert result["verdict"]["summary"]["regressed"] == 0
    assert result["verdict"]["left"]["run_id"] == left.name
    assert result["verdict"]["right"]["run_id"] == right.name

    obs = load_jsonl(result["run_dir"] / "observations.jsonl")
    diff_obs = [o for o in obs if o.get("kind") == "diff"]
    assert diff_obs
    assert {o["run_id"] for o in diff_obs} == {left.name, right.name}
    compare = load_json(result["run_dir"] / "artifacts" / "compare.json")
    assert compare["left"]["run_id"] == left.name

    text, code = explain_text(result["run_dir"], "R-1")
    assert code == 0
    assert "IMPROVED" in text
    assert "UNCHANGED" in text
    assert f"diff {left.name} → {right.name}" in text
    summary = format_verify_summary(result["verdict"], result["run_dir"])
    assert "Improved" in summary
    assert f"{left.name} → {right.name}" in summary


def test_diff_synthetic_regression_is_failed(tmp_path: Path) -> None:
    left = _make_run(tmp_path, {"C-0": "pass", "C-3": "pass"})
    right = _make_run(tmp_path, {"C-0": "pass", "C-3": "fail"})
    result = diff_runs(left, right, tmp_path / "diffs")
    req = result["verdict"]["requirements"][0]
    assert req["verdict"] == FAILED
    assert _constraint_map(result["verdict"])["C-3"]["result"] == REGRESSED
    assertions = load_jsonl(result["run_dir"] / "assertions.jsonl")
    c3 = next(a for a in assertions if a["constraint_id"] == "C-3")
    assert c3["result"] == "fail"
    assert c3["check"] == "delta"


def test_diff_same_planted_bug_is_not_proven(tmp_path: Path) -> None:
    left = _make_run(tmp_path, {"C-0": "pass", "C-3": "fail"})
    right = _make_run(tmp_path, {"C-0": "pass", "C-3": "fail"})
    result = diff_runs(left, right, tmp_path / "diffs")
    assert result["verdict"]["requirements"][0]["verdict"] == NOT_PROVEN


def test_diff_tampered_source_is_inconclusive(tmp_path: Path) -> None:
    left = _make_run(tmp_path, {"C-0": "pass", "C-3": "fail"})
    right = _make_run(tmp_path, {"C-0": "pass", "C-3": "pass"})
    obs = left / "observations.jsonl"
    obs.chmod(0o644)
    obs.write_text(obs.read_text(encoding="utf-8") + '{"id":"O-999"}\n', encoding="utf-8")
    result = diff_runs(left, right, tmp_path / "diffs")
    assert result["verdict"]["requirements"][0]["verdict"] == INCONCLUSIVE_V
    assert result["verdict"]["left"]["integrity_ok"] is False
    verify_manifest(result["run_dir"])


def test_diff_api_claimed_fix_is_proven(tmp_path: Path) -> None:
    planted = verify(MINIAUTH, runs_root=tmp_path, persist_session=False, mode="api")
    fixed = verify(MINIAUTH, runs_root=tmp_path, persist_session=True, mode="api")
    result = diff_runs(planted["run_dir"], fixed["run_dir"], tmp_path / "diffs")
    req = result["verdict"]["requirements"][0]
    assert req["verdict"] == PROVEN
    rows = _constraint_map(result["verdict"])
    assert rows["C-3"]["result"] == IMPROVED
    assert rows["C-0"]["result"] == UNCHANGED
    assert rows["C-4"]["result"] == UNCHANGED
    assert result["verdict"]["summary"]["improved"] == 1
    assert result["verdict"]["summary"]["regressed"] == 0
    text, code = explain_text(result["run_dir"], "C-3")
    assert code == 0
    assert "IMPROVED" in text
    assert planted["run_id"] in text
    assert fixed["run_id"] in text


def test_diff_api_regression_is_failed(tmp_path: Path) -> None:
    fixed = verify(MINIAUTH, runs_root=tmp_path, persist_session=True, mode="api")
    planted = verify(MINIAUTH, runs_root=tmp_path, persist_session=False, mode="api")
    result = diff_runs(fixed["run_dir"], planted["run_dir"], tmp_path / "diffs")
    assert result["verdict"]["requirements"][0]["verdict"] == FAILED
    assert _constraint_map(result["verdict"])["C-3"]["result"] == REGRESSED


def test_cli_diff_by_run_id(tmp_path: Path) -> None:
    runs_root = tmp_path / ".opentruth" / "runs"
    left = verify(MINIAUTH, runs_root=runs_root, persist_session=False, mode="api")
    right = verify(MINIAUTH, runs_root=runs_root, persist_session=True, mode="api")
    with pytest.raises(SystemExit) as exited:
        main(["diff", left["run_id"], right["run_id"], "--path", str(tmp_path)])
    assert exited.value.code == 0
    found = list(runs_root.iterdir())
    assert len(found) == 3
    diff_dir = next(p for p in found if p.name not in {left["run_id"], right["run_id"]})
    verdict = load_json(diff_dir / "verdict.json")
    assert verdict["requirements"][0]["verdict"] == PROVEN
    assert verdict["mode"] == "diff"


def test_resolve_run_arg_prefers_directory(tmp_path: Path) -> None:
    run = _make_run(tmp_path, {"C-0": "pass"})
    assert resolve_run_arg(str(run), tmp_path) == run.resolve()
    with pytest.raises(FileNotFoundError, match="sealed run not found"):
        resolve_run_arg("missing", tmp_path)
