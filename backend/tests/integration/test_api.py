"""End-to-end API tests: full runs, approvals, knowledge, policy endpoints."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_settings):
    from ci_agent.api.main import create_app
    from ci_agent.config import get_settings

    app = create_app()
    app.dependency_overrides[get_settings] = lambda: tmp_settings
    with TestClient(app) as test_client:
        yield test_client


def test_health_and_ready(client):
    assert client.get("/healthz").json()["status"] == "ok"
    ready = client.get("/readyz").json()
    assert ready["checks"]["database"]["ok"] is True
    assert ready["checks"]["knowledge"]["records"] > 20


def test_full_run_generate_only(client, sample_python):
    resp = client.post("/api/v1/runs", json={
        "repo_url": str(sample_python),
        "request": "Create CI with lint and tests.",
        "options": {"platform": "github", "publish": False},
    })
    assert resp.status_code == 202, resp.text
    run_id = resp.json()["run_id"]

    run = client.get(f"/api/v1/runs/{run_id}").json()
    assert run["status"] == "succeeded", run.get("error")
    assert "actions/checkout@v4" in run["rendered_yaml"]
    assert run["validation"], "validation results must be recorded"
    assert all(v["passed"] for v in run["validation"])
    assert run["policy"]["decision"] == "ALLOW"
    assert run["explanation"]

    yaml_doc = client.get(f"/api/v1/runs/{run_id}/yaml").json()
    assert yaml_doc["filename"] == ".github/workflows/ci.yml"

    evidence = client.get(f"/api/v1/runs/{run_id}/evidence").json()
    assert evidence["evidence_hash"].startswith("sha256:")
    assert evidence["final_action"] == "generated"

    events = client.get(f"/api/v1/runs/{run_id}/events").json()["events"]
    assert len(events) > 10
    paged = client.get(f"/api/v1/runs/{run_id}/events", params={"after_seq": 5}).json()["events"]
    assert all(e["seq"] > 5 for e in paged)


def test_approval_flow_approve_and_reject(client, sample_python):
    def start():
        resp = client.post("/api/v1/runs", json={
            "repo_url": str(sample_python),
            "request": "lint and test",
            "options": {"platform": "github", "publish": False, "require_approval": True},
        })
        assert resp.status_code == 202
        return resp.json()["run_id"]

    run_id = start()
    assert client.get(f"/api/v1/runs/{run_id}").json()["status"] == "awaiting_approval"
    pending = client.get("/api/v1/approvals/pending").json()["pending"]
    assert run_id in [r["id"] for r in pending]

    decision = client.post(f"/api/v1/runs/{run_id}/approve",
                           json={"decision": "approve", "reason": "looks good"},
                           headers={"X-Actor": "reviewer-1"}).json()
    assert decision["status"] == "succeeded"
    evidence = client.get(f"/api/v1/runs/{run_id}/evidence").json()
    assert evidence["approval"]["approver"] == "reviewer-1"

    run_id2 = start()
    rejected = client.post(f"/api/v1/runs/{run_id2}/approve",
                           json={"decision": "reject", "reason": "not now"},
                           headers={"X-Actor": "reviewer-2"}).json()
    assert rejected["status"] == "cancelled"

    bad = client.post(f"/api/v1/runs/{run_id2}/approve", json={"decision": "approve"})
    assert bad.status_code == 400


def test_unknown_run_404(client):
    assert client.get("/api/v1/runs/does-not-exist").status_code == 404
    assert client.get("/api/v1/knowledge/tools/does-not-exist").status_code == 404


def test_knowledge_endpoints(client):
    tools = client.get("/api/v1/knowledge/tools").json()["tools"]
    assert "ruff" in tools and "syft" in tools
    ruff = client.get("/api/v1/knowledge/tools/ruff").json()
    assert "lint" in ruff["capabilities"]
    stats = client.get("/api/v1/knowledge/stats").json()
    assert stats["tools"] == len(tools)


def test_policy_endpoints(client):
    catalog = client.get("/api/v1/policies/catalog").json()
    assert "ruff" in catalog["tools"]
    decision = client.post("/api/v1/policies/evaluate", json={
        "intent": {"platform": "github", "capabilities": ["lint"], "prohibited_tools": []},
        "plan": {
            "tools": [{"name": "ruff", "version": "0.4.0", "capability": "lint"}],
            "actions": [{"uses": "actions/checkout@v4", "pinned": True}],
            "permissions": {"contents": "read"},
        },
        "repo": {"repo_url": "https://github.com/o/r"},
        "risk_level": "low",
    }).json()
    assert decision["decision"] == "ALLOW"
    assert decision["evaluator"] == "local"
