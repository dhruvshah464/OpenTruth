from pathlib import Path

import pytest

from opentruth.engine import verify
from opentruth.explain import explain_text
from opentruth.store import IntegrityError, verify_manifest
from opentruth.verdicts import INCONCLUSIVE_V, PARTIALLY_PROVEN, PROVEN

ROOT = Path(__file__).resolve().parents[1]
MINIAUTH = ROOT / "examples" / "miniauth"
UNREACHABLE = Path(__file__).parent / "fixtures" / "unreachable"

REQUIRED_FILES = (
    "manifest.json",
    "requirements.json",
    "plan.json",
    "actions.jsonl",
    "observations.jsonl",
    "assertions.jsonl",
    "verdict.json",
)


def _constraint_map(result: dict) -> dict[str, str]:
    req = result["verdict"]["requirements"][0]
    return {row["id"]: row["result"] for row in req["constraints"]}


def _assert_layout(run_dir: Path) -> None:
    for name in REQUIRED_FILES:
        assert (run_dir / name).is_file(), name
    assert (run_dir / "screenshots").is_dir()
    assert (run_dir / "network").is_dir()
    assert (run_dir / "artifacts").is_dir()
    verify_manifest(run_dir)


@pytest.mark.browser
def test_planted_bug_is_partially_proven(tmp_path: Path) -> None:
    result = verify(MINIAUTH, runs_root=tmp_path, persist_session=False)
    assert result["verdict"]["requirements"][0]["verdict"] == PARTIALLY_PROVEN
    results = _constraint_map(result)
    assert results["C-0"] == "pass"
    assert results["C-1"] == "pass"
    assert results["C-2"] == "pass"
    assert results["C-3"] == "fail"
    assert results["C-4"] == "pass"
    _assert_layout(result["run_dir"])
    network = list((result["run_dir"] / "network").glob("A-*.json"))
    assert network, "network/ must contain per-action logs"
    artifacts = list((result["run_dir"] / "artifacts").glob("E-*.html"))
    assert artifacts, "failing assertion must write an HTML artifact"

    text, code = explain_text(result["run_dir"], "R-1")
    assert code == 0
    assert "C-3" in text
    assert "FAIL" in text

    fail_id = None
    for line in (result["run_dir"] / "assertions.jsonl").read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        import json

        rec = json.loads(line)
        if rec["constraint_id"] == "C-3" and rec["result"] == "fail":
            fail_id = rec["id"]
            break
    assert fail_id
    focused, fcode = explain_text(result["run_dir"], fail_id)
    assert fcode == 0
    assert fail_id in focused
    assert "cites" in focused.lower() or "O-" in focused


@pytest.mark.browser
def test_fixed_session_is_proven(tmp_path: Path) -> None:
    result = verify(MINIAUTH, runs_root=tmp_path, persist_session=True)
    assert result["verdict"]["requirements"][0]["verdict"] == PROVEN
    results = _constraint_map(result)
    assert all(v == "pass" for v in results.values())
    _assert_layout(result["run_dir"])


def test_unreachable_app_is_inconclusive(tmp_path: Path) -> None:
    result = verify(UNREACHABLE, runs_root=tmp_path, start=True)
    assert result["verdict"]["requirements"][0]["verdict"] == INCONCLUSIVE_V
    results = _constraint_map(result)
    assert all(v == "inconclusive" for v in results.values())
    verify_manifest(result["run_dir"])


@pytest.mark.browser
def test_tamper_refuses_authoritative_verdict(tmp_path: Path) -> None:
    result = verify(MINIAUTH, runs_root=tmp_path, persist_session=False)
    obs = result["run_dir"] / "observations.jsonl"
    obs.chmod(0o644)
    obs.write_text(obs.read_text(encoding="utf-8") + '{"id":"O-999"}\n', encoding="utf-8")
    with pytest.raises(IntegrityError):
        verify_manifest(result["run_dir"])
    text, code = explain_text(result["run_dir"], "R-1")
    assert code == 3
    assert "INTEGRITY FAILED" in text
    assert "not authoritative" in text
