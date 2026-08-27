from pathlib import Path

from opentruth.store import IntegrityError, RunStore, load_jsonl, verify_manifest
import pytest


def _seed(store: RunStore) -> None:
    store.write_json(
        "requirements.json",
        {
            "id": "R-1",
            "statement": "demo",
            "constraints": [
                {"id": "C-0", "requirement_id": "R-1", "statement": "demo", "kind": "happy_path"}
            ],
        },
    )
    store.write_json("plan.json", {"requirement_id": "R-1", "steps": []})
    store.append(
        "actions.jsonl",
        {"id": "A-001", "constraint_id": "C-0", "type": "navigate", "target": "/"},
    )
    png = store.write_blob("screenshots", "A-001.png", b"fake-png")
    store.append(
        "observations.jsonl",
        {"id": "O-001", "action_id": "A-001", "constraint_id": "C-0", "kind": "screenshot", "path": png},
    )
    net = store.write_blob("network", "A-001.json", b'{"requests":[]}\n')
    store.append(
        "observations.jsonl",
        {"id": "O-002", "action_id": "A-001", "constraint_id": "C-0", "kind": "network", "path": net},
    )
    store.write_json(
        "verdict.json",
        {"run_id": store.run_id, "requirements": [], "summary": {}},
    )


def test_seal_hashes_and_rejects_mutation(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    store.create()
    _seed(store)
    store.append(
        "assertions.jsonl",
        {"id": "E-001", "constraint_id": "C-0", "cites": ["O-001"], "result": "pass"},
    )
    manifest = store.seal()
    assert manifest["sealed"] is True
    assert "verdict.json" in manifest["files"]
    assert "observations.jsonl" in manifest["files"]
    assert "screenshots/A-001.png" in manifest["files"]
    assert "network/A-001.json" in manifest["files"]
    verify_manifest(store.root)

    with pytest.raises(Exception):
        store.append("actions.jsonl", {"id": "A-002"})

    obs = store.root / "observations.jsonl"
    obs.chmod(0o644)
    original = obs.read_text(encoding="utf-8")
    obs.write_text(original + '{"id":"O-999"}\n', encoding="utf-8")
    with pytest.raises(IntegrityError, match="changed"):
        verify_manifest(store.root)


def test_jsonl_is_append_only_records(tmp_path: Path) -> None:
    store = RunStore(tmp_path)
    store.create()
    store.append("actions.jsonl", {"id": "A-001", "constraint_id": "C-0", "type": "click"})
    store.append("actions.jsonl", {"id": "A-002", "constraint_id": "C-0", "type": "fill"})
    rows = load_jsonl(store.root / "actions.jsonl")
    assert [r["id"] for r in rows] == ["A-001", "A-002"]
    assert all("timestamp" in r for r in rows)
