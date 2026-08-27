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


def test_api_planted_bug_is_partially_proven(tmp_path: Path) -> None:
    result = verify(MINIAUTH, runs_root=tmp_path, persist_session=False, mode="api")
    assert result["verdict"]["requirements"][0]["verdict"] == PARTIALLY_PROVEN
    results = _constraint_map(result)
    assert results["C-0"] == "pass"
    assert results["C-1"] == "pass"
    assert results["C-2"] == "pass"
    assert results["C-3"] == "fail"
    assert results["C-4"] == "pass"
    verify_manifest(result["run_dir"])
    http_obs = [o for o in load_jsonl(result["run_dir"] / "observations.jsonl") if o.get("kind") == "http"]
    assert http_obs, "API proof must record kind=http observations"
    network = list((result["run_dir"] / "network").glob("A-*.json"))
    assert network
    artifacts = list((result["run_dir"] / "artifacts").glob("E-*.json"))
    assert artifacts, "failing HTTP assertion must write a JSON artifact"
    text, code = explain_text(result["run_dir"], "R-1")
    assert code == 0
    assert "C-3" in text
    assert "FAIL" in text
    assert "C-4" in text


def test_api_fixed_session_is_proven(tmp_path: Path) -> None:
    result = verify(MINIAUTH, runs_root=tmp_path, persist_session=True, mode="api")
    assert result["verdict"]["requirements"][0]["verdict"] == PROVEN
    assert all(v == "pass" for v in _constraint_map(result).values())
    verify_manifest(result["run_dir"])


def test_api_unreachable_is_inconclusive(tmp_path: Path) -> None:
    result = verify(UNREACHABLE, runs_root=tmp_path, start=True, mode="api")
    assert result["verdict"]["requirements"][0]["verdict"] == INCONCLUSIVE_V
    verify_manifest(result["run_dir"])
