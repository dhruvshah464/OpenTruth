"""v0.3 MiniTodos protocol experiment.

IR + API + Diff against a non-MiniAuth app. Outcomes, not live run ids.
Success is planner=ir and expand() never called — not that the todo app 'works'.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import yaml

from opentruth.diff import diff_runs
from opentruth.engine import verify
from opentruth.store import load_json, verify_manifest
from opentruth.verdicts import FAILED, IMPROVED, PARTIALLY_PROVEN, PROVEN, UNCHANGED

ROOT = Path(__file__).resolve().parents[1]
MINITODOS = ROOT / "examples" / "minitodos"


def _constraint_map(verdict: dict) -> dict[str, dict]:
    req = verdict["requirements"][0]
    return {row["id"]: row for row in req["constraints"]}


def _rows(verdict: dict) -> dict[str, str]:
    req = verdict["requirements"][0]
    return {row["id"]: row["result"] for row in req["constraints"]}


def _copy_app(tmp_path: Path, *, strip_verification: bool = False) -> Path:
    dest = tmp_path / "minitodos"
    shutil.copytree(
        MINITODOS,
        dest,
        ignore=shutil.ignore_patterns(".opentruth*", ".opentruth-tmp*", "__pycache__", "*.pyc"),
    )
    if strip_verification:
        path = dest / "requirements.yaml"
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        raw.pop("verification", None)
        path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return dest


def test_v03_yaml_declares_verification_ir() -> None:
    text = (MINITODOS / "requirements.yaml").read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    assert raw["verification"]["version"] == 1
    assert raw["verification"]["steps"]


def test_v03_planted_api_is_partially_proven(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("MINITODOS_PERSIST_COMPLETE", raising=False)
    calls: list[object] = []

    import opentruth.llm as llm

    real = llm.expand

    def wrapped(*args: object, **kwargs: object) -> object:
        calls.append((args, kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(llm, "expand", wrapped)

    result = verify(MINITODOS, runs_root=tmp_path, mode="api")
    req = result["verdict"]["requirements"][0]
    assert req["verdict"] == PARTIALLY_PROVEN
    rows = _rows(result["verdict"])
    assert rows["C-0"] == "pass"
    assert rows["C-1"] == "pass"
    assert rows["C-2"] == "fail"
    assert rows["C-3"] == "pass"
    plan = load_json(result["run_dir"] / "plan.json")
    assert plan.get("planner") == "ir"
    assert plan.get("verification_version") == 1
    assert "verdict" not in plan
    assert calls == []
    verify_manifest(result["run_dir"])
    stored = load_json(result["run_dir"] / "verdict.json")
    assert stored["requirements"][0]["verdict"] == PARTIALLY_PROVEN


def test_v03_persist_complete_api_is_proven(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MINITODOS_PERSIST_COMPLETE", "1")
    calls: list[object] = []

    import opentruth.llm as llm

    real = llm.expand

    def wrapped(*args: object, **kwargs: object) -> object:
        calls.append((args, kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(llm, "expand", wrapped)

    result = verify(MINITODOS, runs_root=tmp_path, mode="api")
    req = result["verdict"]["requirements"][0]
    assert req["verdict"] == PROVEN
    assert all(row["result"] == "pass" for row in req["constraints"])
    plan = load_json(result["run_dir"] / "plan.json")
    assert plan.get("planner") == "ir"
    assert calls == []
    verify_manifest(result["run_dir"])


def test_v03_diff_planted_to_fixed_improves_c2(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("MINITODOS_PERSIST_COMPLETE", raising=False)
    planted = verify(MINITODOS, runs_root=tmp_path, mode="api")
    monkeypatch.setenv("MINITODOS_PERSIST_COMPLETE", "1")
    fixed = verify(MINITODOS, runs_root=tmp_path, mode="api")
    result = diff_runs(planted["run_dir"], fixed["run_dir"], tmp_path / "diffs")
    req = result["verdict"]["requirements"][0]
    assert req["verdict"] == PROVEN
    rows = _constraint_map(result["verdict"])
    assert rows["C-2"]["result"] == IMPROVED
    assert rows["C-0"]["result"] == UNCHANGED
    assert rows["C-1"]["result"] == UNCHANGED
    assert rows["C-3"]["result"] == UNCHANGED
    verify_manifest(result["run_dir"])
    assert load_json(result["run_dir"] / "verdict.json")["requirements"][0]["verdict"] == PROVEN


def test_v03_stripped_ir_is_not_silent_proven(tmp_path: Path) -> None:
    app = _copy_app(tmp_path, strip_verification=True)
    result = verify(app, runs_root=tmp_path / "runs", mode="api")
    req = result["verdict"]["requirements"][0]
    assert req["verdict"] != PROVEN
    plan = load_json(result["run_dir"] / "plan.json")
    assert plan.get("planner") == "deterministic"
    assert "verification_version" not in plan
    # Wrong planner hitting MiniAuth routes against a todo app: happy path fails.
    assert req["verdict"] == FAILED
    assert _rows(result["verdict"])["C-0"] == "fail"
