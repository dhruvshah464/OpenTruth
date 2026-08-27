"""v0.1.0-m1 acceptance contract.

Outcomes, not live console run ids. Future protocol work (Verification IR
included) must not change these MiniAuth results accidentally.
"""

from pathlib import Path

from opentruth.diff import diff_runs
from opentruth.engine import verify
from opentruth.store import load_json, verify_manifest
from opentruth.verdicts import IMPROVED, PARTIALLY_PROVEN, PROVEN, UNCHANGED

ROOT = Path(__file__).resolve().parents[1]
MINIAUTH = ROOT / "examples" / "miniauth"


def _constraint_map(verdict: dict) -> dict[str, dict]:
    req = verdict["requirements"][0]
    return {row["id"]: row for row in req["constraints"]}


def test_m1_planted_api_is_partially_proven(tmp_path: Path) -> None:
    result = verify(MINIAUTH, runs_root=tmp_path, persist_session=False, mode="api")
    req = result["verdict"]["requirements"][0]
    assert req["verdict"] == PARTIALLY_PROVEN
    rows = {row["id"]: row["result"] for row in req["constraints"]}
    assert rows["C-0"] == "pass"
    assert rows["C-1"] == "pass"
    assert rows["C-2"] == "pass"
    assert rows["C-3"] == "fail"
    assert rows["C-4"] == "pass"
    verify_manifest(result["run_dir"])
    stored = load_json(result["run_dir"] / "verdict.json")
    assert stored["requirements"][0]["verdict"] == PARTIALLY_PROVEN
    plan = load_json(result["run_dir"] / "plan.json")
    assert "verdict" not in plan
    assert plan.get("planner") == "deterministic"


def test_m1_persist_session_api_is_proven(tmp_path: Path) -> None:
    result = verify(MINIAUTH, runs_root=tmp_path, persist_session=True, mode="api")
    req = result["verdict"]["requirements"][0]
    assert req["verdict"] == PROVEN
    assert all(row["result"] == "pass" for row in req["constraints"])
    verify_manifest(result["run_dir"])


def test_m1_diff_planted_to_fixed_improves_c3(tmp_path: Path) -> None:
    planted = verify(MINIAUTH, runs_root=tmp_path, persist_session=False, mode="api")
    fixed = verify(MINIAUTH, runs_root=tmp_path, persist_session=True, mode="api")
    result = diff_runs(planted["run_dir"], fixed["run_dir"], tmp_path / "diffs")
    req = result["verdict"]["requirements"][0]
    assert req["verdict"] == PROVEN
    rows = _constraint_map(result["verdict"])
    assert rows["C-3"]["result"] == IMPROVED
    assert rows["C-0"]["result"] == UNCHANGED
    verify_manifest(result["run_dir"])
    assert load_json(result["run_dir"] / "verdict.json")["requirements"][0]["verdict"] == PROVEN


def test_m1_miniauth_yaml_has_no_verification_block() -> None:
    text = (MINIAUTH / "requirements.yaml").read_text(encoding="utf-8")
    assert "verification:" not in text
