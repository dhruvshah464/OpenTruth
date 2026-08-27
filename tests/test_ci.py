import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

from opentruth.ci import emit_ci, format_github_summary, pack_error_exit, pack_run
from opentruth.cli import main
from opentruth.store import IntegrityError, RunStore, verify_manifest
from opentruth.verdicts import FAILED, INCONCLUSIVE_V, NOT_PROVEN, PARTIALLY_PROVEN, PROVEN, exit_code

ROOT = Path(__file__).resolve().parents[1]
MINIAUTH = ROOT / "examples" / "miniauth"
UNREACHABLE = Path(__file__).parent / "fixtures" / "unreachable"


def _sealed_run(tmp_path: Path) -> Path:
    store = RunStore(tmp_path)
    store.create()
    store.write_json(
        "requirements.json",
        {
            "id": "R-1",
            "statement": "auth",
            "constraints": [
                {"id": "C-0", "requirement_id": "R-1", "statement": "auth", "kind": "happy_path"}
            ],
        },
    )
    store.write_json("plan.json", {"mode": "api", "requirement_id": "R-1", "steps": []})
    store.append("actions.jsonl", {"id": "A-001", "constraint_id": "C-0", "type": "noop", "target": "/"})
    store.append(
        "observations.jsonl",
        {"id": "O-001", "action_id": "A-001", "constraint_id": "C-0", "kind": "http", "value": "pass"},
    )
    store.append(
        "assertions.jsonl",
        {
            "id": "E-001",
            "constraint_id": "C-0",
            "action_id": "A-001",
            "check": "status",
            "expect": "pass",
            "cites": ["O-001"],
            "result": "pass",
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
                    "verdict": PROVEN,
                    "constraints": [{"id": "C-0", "kind": "happy_path", "statement": "auth", "result": "pass"}],
                }
            ],
            "summary": {"confidence": 1.0, "proven": 1},
        },
    )
    store.seal()
    return store.root


def test_exit_code_ci_contract() -> None:
    assert exit_code(PROVEN) == 0
    assert exit_code(PARTIALLY_PROVEN) == 1
    assert exit_code(FAILED) == 1
    assert exit_code(NOT_PROVEN) == 1
    assert exit_code(INCONCLUSIVE_V) == 2
    assert exit_code("unknown") == 1


def test_github_summary_and_outputs(tmp_path: Path) -> None:
    run_dir = tmp_path / "abcd1234"
    run_dir.mkdir()
    verdict = {
        "run_id": "abcd1234",
        "requirements": [
            {
                "id": "R-1",
                "statement": "auth",
                "verdict": PROVEN,
                "constraints": [{"id": "C-0", "result": "pass"}, {"id": "C-3", "result": "improved"}],
            }
        ],
        "summary": {"confidence": 1.0, "improved": 1, "regressed": 0, "unchanged": 4},
        "left": {"run_id": "before01"},
        "right": {"run_id": "after002"},
    }
    md = format_github_summary(verdict, run_dir)
    assert "**PROVEN**" in md
    assert "`C-3`" in md
    assert "improved" in md
    assert "before01" in md
    out = tmp_path / "github_output"
    summary = tmp_path / "summary.md"
    summary.write_text("existing\n", encoding="utf-8")
    emit_ci(verdict, run_dir, env={"GITHUB_OUTPUT": str(out), "GITHUB_STEP_SUMMARY": str(summary)})
    text = out.read_text(encoding="utf-8")
    assert "verdict=PROVEN" in text
    assert "run-id=abcd1234" in text
    assert "run-dir=" in text
    combined = summary.read_text(encoding="utf-8")
    assert "existing" in combined
    assert "**PROVEN**" in combined


def test_pack_sealed_run_roundtrip(tmp_path: Path) -> None:
    run_dir = _sealed_run(tmp_path / "runs")
    bundle = pack_run(run_dir, tmp_path / "bundles")
    assert bundle.is_file()
    assert bundle.name == f"{run_dir.name}.zip"
    extract = tmp_path / "extracted"
    with zipfile.ZipFile(bundle) as archive:
        names = archive.namelist()
        assert f"{run_dir.name}/manifest.json" in names
        assert f"{run_dir.name}/verdict.json" in names
        archive.extractall(extract)
    verify_manifest(extract / run_dir.name)


def test_pack_refuses_tampered_run(tmp_path: Path) -> None:
    run_dir = _sealed_run(tmp_path / "runs")
    obs = run_dir / "observations.jsonl"
    obs.chmod(0o644)
    obs.write_text(obs.read_text(encoding="utf-8") + '{"id":"O-999"}\n', encoding="utf-8")
    with pytest.raises(IntegrityError):
        pack_run(run_dir, tmp_path / "bad.zip")
    assert pack_error_exit(IntegrityError("changed")) == 3


def test_cli_pack_latest(tmp_path: Path) -> None:
    run_dir = _sealed_run(tmp_path / ".opentruth" / "runs")
    dest = tmp_path / "out.zip"
    with pytest.raises(SystemExit) as exited:
        main(["pack", "--path", str(tmp_path), "--out", str(dest)])
    assert exited.value.code == 0
    assert dest.is_file()
    with zipfile.ZipFile(dest) as archive:
        assert f"{run_dir.name}/manifest.json" in archive.namelist()


def test_cli_verify_github_outputs_and_pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runs = tmp_path / "runs"
    github_out = tmp_path / "github_output"
    github_sum = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_OUTPUT", str(github_out))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(github_sum))
    with pytest.raises(SystemExit) as exited:
        main(
            [
                "verify",
                "--path",
                str(MINIAUTH),
                "--mode",
                "api",
                "--out",
                str(runs),
                "--persist-session",
            ]
        )
    assert exited.value.code == 0
    text = github_out.read_text(encoding="utf-8")
    assert "verdict=PROVEN" in text
    assert "run-id=" in text
    assert "run-dir=" in text
    assert "**PROVEN**" in github_sum.read_text(encoding="utf-8")
    run_id = next(line.split("=", 1)[1].strip() for line in text.splitlines() if line.startswith("run-id="))
    bundle = tmp_path / "ci.zip"
    with pytest.raises(SystemExit) as packed:
        main(["pack", "--path", str(tmp_path), "--run", str(runs / run_id), "--out", str(bundle)])
    assert packed.value.code == 0
    assert bundle.is_file()


def test_cli_unreachable_exit_inconclusive(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exited:
        main(["verify", "--path", str(UNREACHABLE), "--mode", "api", "--out", str(tmp_path)])
    assert exited.value.code == 2


def test_action_skips_pack_when_verify_never_ran() -> None:
    """v0.1 freeze: install failure must not make pack fail the job on a missing binary."""
    text = (ROOT / "action.yml").read_text(encoding="utf-8")
    assert "command -v opentruth" in text
    assert "steps.pack.outputs.bundle" in text
    assert "force-include" not in (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_action_and_workflow_are_ci_not_saas() -> None:
    action = yaml.safe_load((ROOT / "action.yml").read_text(encoding="utf-8"))
    assert action["runs"]["using"] == "composite"
    assert "verdict" in action["outputs"]
    assert "bundle" in action["outputs"]
    steps = " ".join(step.get("uses") or step.get("run") or "" for step in action["runs"]["steps"])
    assert "actions/upload-artifact" in steps
    assert "opentruth verify" in steps
    assert "opentruth pack" in steps
    assert "--llm" in (ROOT / "action.yml").read_text(encoding="utf-8")
    assert "llm" in action["inputs"]
    workflow = yaml.safe_load(
        (ROOT / ".github" / "workflows" / "opentruth.yml").read_text(encoding="utf-8")
    )
    verify_steps = workflow["jobs"]["verify"]["steps"]
    miniauth = next(step for step in verify_steps if step.get("name") == "Prove MiniAuth (API)")
    minitodos = next(step for step in verify_steps if step.get("name") == "Prove MiniTodos (API IR)")
    assert miniauth["uses"] == "./"
    assert miniauth["with"]["path"] == "examples/miniauth"
    assert miniauth["with"]["persist-session"] == "true"
    assert minitodos["uses"] == "./"
    assert minitodos["with"]["path"] == "examples/minitodos"
    assert minitodos["env"]["MINITODOS_PERSIST_COMPLETE"] == "1"
    assert workflow["jobs"]["test"]["steps"][-1]["run"] == 'pytest -m "not browser" -q'


def test_wheel_includes_site_assets_once(tmp_path: Path) -> None:
    """pip install of the Action path builds a wheel; site files must not duplicate."""
    dest = tmp_path / "wheels"
    dest.mkdir()
    subprocess.check_call(
        [sys.executable, "-m", "pip", "wheel", "--no-deps", "--quiet", "-w", str(dest), str(ROOT)],
    )
    wheels = list(dest.glob("opentruth-*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as archive:
        names = archive.namelist()
    site = [name for name in names if name.startswith("opentruth/site/")]
    assert "opentruth/site/404.html" in site
    assert "opentruth/site/index.html" in site
    assert site.count("opentruth/site/404.html") == 1
    assert "force-include" not in (ROOT / "pyproject.toml").read_text(encoding="utf-8")
