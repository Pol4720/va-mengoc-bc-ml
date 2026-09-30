"""Local lab API: authentication, CORS/PNA, whitelisted overrides and a full synthetic job."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vamengoc.api.server import _validate_overrides, create_app
from vamengoc.config import find_project_root


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    root = find_project_root()
    api = create_app(root, token="secret-token")
    # redirect run artefacts to a temporary directory
    from vamengoc.config import Project

    orig_init = Project.__init__

    def patched(self: Project, root_: Path | None = None, overrides: dict | None = None) -> None:
        from vamengoc.config import deep_merge

        over = deep_merge({"paths": {"runs_dir": str(tmp_path / "runs")}}, overrides or {})
        orig_init(self, root_, over)

    monkeypatch.setattr(Project, "__init__", patched)
    return TestClient(api)


H = {"X-Lab-Token": "secret-token"}


def test_health_and_auth(client: TestClient) -> None:
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert client.get("/api/tunables").status_code == 401
    assert client.get("/api/tunables", headers={"X-Lab-Token": "wrong"}).status_code == 401
    t = client.get("/api/tunables", headers=H).json()["tunables"]
    assert any(x["path"] == "sdc.min_cell" and x["value"] == 5 for x in t)
    assert client.get("/api/runs/nope", headers=H).status_code == 404
    assert client.get("/api/runs/nope/bundle", headers=H).status_code == 404


def test_cors_and_private_network(client: TestClient) -> None:
    r = client.options(
        "/api/runs",
        headers={
            "Origin": "https://pol4720.github.io",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-Lab-Token",
            "Access-Control-Request-Private-Network": "true",
        },
    )
    assert r.headers.get("access-control-allow-origin") == "https://pol4720.github.io"
    assert r.headers.get("access-control-allow-private-network") == "true"
    r = client.options("/api/runs", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert r.headers.get("access-control-allow-origin") is None


def test_override_whitelist() -> None:
    assert _validate_overrides({"sdc": {"min_cell": 10}}) == {"sdc": {"min_cell": 10}}
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        _validate_overrides({"paths": {"raw_dir": "/etc"}})
    with pytest.raises(HTTPException):
        _validate_overrides({"security": {"hmac_key_file": "x"}})


def test_synthetic_job_end_to_end(client: TestClient) -> None:
    r = client.post(
        "/api/runs",
        headers=H,
        json={
            "source": "synthetic",
            "synthetic_scale": 0.02,
            "synthetic_seed": 3,
            "overrides": {
                "analysis": {"lca": {"k_range": [1, 3]}, "qc_safety": {"permutation_tests": 3}},
                "sdc": {"min_cell": 5},
            },
        },
    )
    assert r.status_code == 202, r.text
    job_id = r.json()["id"]
    deadline = time.time() + 600
    status = {}
    while time.time() < deadline:
        status = client.get(f"/api/runs/{job_id}", headers=H).json()
        if status["status"] in {"done", "failed"}:
            break
        time.sleep(1)
    assert status["status"] == "done", status
    assert status["verification"]["ok"]
    bundle = client.get(f"/api/runs/{job_id}/bundle", headers=H).json()
    assert bundle["meta"]["lab_job"] == job_id and bundle["meta"]["synthetic"] is True
    assert any(j["id"] == job_id for j in client.get("/api/runs", headers=H).json())
    bad = client.post("/api/runs", headers=H, json={"overrides": {"paths": {"raw_dir": "/"}}})
    assert bad.status_code == 422
    raw = client.post("/api/runs", headers=H, json={"source": "raw"})
    assert raw.status_code in (202, 409)
