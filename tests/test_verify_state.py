from pathlib import Path

from opentruth.engine import verify
from opentruth.explain import explain_text
from opentruth.store import load_jsonl, verify_manifest
from opentruth.verdicts import INCONCLUSIVE_V, PARTIALLY_PROVEN, PROVEN

ROOT = Path(__file__).resolve().parents[1]
MINIAUTH = ROOT / "examples" / "miniauth"
UNREACHABLE = Path(__file__).parent / "fixtures" / "unreachable"


def _constraint_map(result: dict) -> dict[str, str]:
    req = result["verdict"]["requirements"][0]
    return {row["id"]: row["result"] for row in req["constraints"]}


def test_state_planted_identity_gap_is_partially_proven(tmp_path: Path) -> None:
    result = verify(MINIAUTH, runs_root=tmp_path, write_identity=False, mode="state")
    assert result["verdict"]["requirements"][0]["verdict"] == PARTIALLY_PROVEN
    results = _constraint_map(result)
    assert results["C-0"] == "pass"
    assert results["C-1"] == "pass"
    assert results["C-2"] == "fail"
    assert results["C-3"] == "pass"
    verify_manifest(result["run_dir"])
    state_obs = [o for o in load_jsonl(result["run_dir"] / "observations.jsonl") if o.get("kind") == "state"]
    assert state_obs, "state proof must record kind=state observations"
    text, code = explain_text(result["run_dir"], "R-1")
    assert code == 0
    assert "C-2" in text
    assert "FAIL" in text
    assert "identities" in text.lower() or "cell_equals" in text


def test_state_with_identity_row_is_proven(tmp_path: Path) -> None:
    result = verify(MINIAUTH, runs_root=tmp_path, write_identity=True, mode="state")
    assert result["verdict"]["requirements"][0]["verdict"] == PROVEN
    assert all(v == "pass" for v in _constraint_map(result).values())
    verify_manifest(result["run_dir"])


def test_state_unreachable_is_inconclusive(tmp_path: Path) -> None:
    result = verify(UNREACHABLE, runs_root=tmp_path, start=True, mode="state")
    assert result["verdict"]["requirements"][0]["verdict"] == INCONCLUSIVE_V
    verify_manifest(result["run_dir"])
