from fastapi.testclient import TestClient

from opentruth.server import create_app
from opentruth.verdicts import PARTIALLY_PROVEN, PROVEN


def test_health_and_marketing_pages() -> None:
    client = TestClient(create_app())
    health = client.get("/api/v1/health")
    assert health.status_code == 200
    body = health.json()
    assert body["ok"] is True
    assert "runs" in body
    assert "llm" in body
    home = client.get("/")
    assert home.status_code == 200
    assert b"OpenTruth" in home.content
    assert b"Verifier" in home.content
    console = client.get("/console")
    assert console.status_code == 200
    assert b"Run full proof" in console.content
    assert b"LLM plan only" in console.content
    for path in ("/engine", "/evidence", "/docs", "/company"):
        assert client.get(path).status_code == 200
    docs = client.get("/docs")
    assert b"M6" in docs.content
    assert b"--llm" in docs.content
    product = client.get("/api/v1/product").json()
    assert product["principle"] == "Verifier ≠ Builder"
    assert len(product["layers"]) == 6
    missing = client.get("/no-such-surface")
    assert missing.status_code == 404
    assert b"No evidence on this path" in missing.content


def test_live_api_verify_through_server() -> None:
    client = TestClient(create_app())
    res = client.post("/api/v1/verify", json={"mode": "api", "persist_session": False})
    assert res.status_code == 200
    body = res.json()
    assert body["verdict"] == PARTIALLY_PROVEN
    run_id = body["run_id"]
    graph = client.get(f"/api/v1/runs/{run_id}")
    assert graph.status_code == 200
    payload = graph.json()
    assert payload["integrity_ok"] is True
    assert payload["root"] == "R-1"
    assert "files" in payload
    explain = client.get(f"/api/v1/runs/{run_id}/explain/C-3")
    assert explain.status_code == 200
    assert "C-3" in explain.json()["text"]
    listed = client.get("/api/v1/runs").json()["runs"]
    assert any(item["run_id"] == run_id for item in listed)
    packed = client.get(f"/api/v1/runs/{run_id}/pack")
    assert packed.status_code == 200
    assert packed.headers["content-type"].startswith("application/zip")
    assert packed.content[:2] == b"PK"
    traversal = client.get(f"/api/v1/runs/{run_id}/file/screenshots/../plan.json")
    assert traversal.status_code == 404
    unknown = client.get("/api/v1/runs/zzzzzzzz")
    assert unknown.status_code == 404
    assert unknown.headers["content-type"].startswith("application/json")


def test_claimed_fix_and_full_loop_through_server() -> None:
    client = TestClient(create_app())
    same = client.post("/api/v1/diff", json={"left": "aaaaaaaa", "right": "aaaaaaaa"})
    assert same.status_code in {400, 404}
    loop = client.post("/api/v1/loop", json={"mode": "api"})
    assert loop.status_code == 200
    body = loop.json()
    assert body["planted"]["verdict"] == PARTIALLY_PROVEN
    assert body["fixed"]["verdict"] == PROVEN
    assert body["diff"]["verdict"] == PROVEN
    assert body["planted"]["run_id"] != body["fixed"]["run_id"]
    dup = client.post(
        "/api/v1/diff",
        json={"left": body["planted"]["run_id"], "right": body["planted"]["run_id"]},
    )
    assert dup.status_code == 400
    graph = client.get(f"/api/v1/runs/{body['diff']['run_id']}")
    assert graph.status_code == 200
    payload = graph.json()
    assert payload["left"]["run_id"] == body["planted"]["run_id"]
    assert payload["right"]["run_id"] == body["fixed"]["run_id"]
    health = client.get("/api/v1/health").json()
    assert health["latest"]["run_id"] == body["diff"]["run_id"]


def test_llm_flag_through_server_falls_back_without_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENTRUTH_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = TestClient(create_app())
    assert client.get("/api/v1/health").json()["llm"] is False
    res = client.post("/api/v1/verify", json={"mode": "api", "llm": True})
    assert res.status_code == 200
    assert res.json()["verdict"] == PARTIALLY_PROVEN
    plan = client.get(f"/api/v1/runs/{res.json()['run_id']}").json()["plan"]
    assert plan["planner"] == "deterministic"
    assert plan["planner_requested"] == "llm"
    assert "OPENTRUTH_LLM_API_KEY missing" in (plan.get("llm_error") or "")
