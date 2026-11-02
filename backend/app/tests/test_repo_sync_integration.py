# 测试阅读入口：用真实本地 HTTP 服务与临时数据库验证分页、故障保留、健康说明和旧库升级。
# 这里的真实 HTTP 不等于访问真实 GitHub；临时数据用于可重复地构造成功/失败场景。
# 阅读方法：先看准备的数据/替身，再看调用入口，最后看 assert 锁定的行为；本文件断言保持原样。
"""Exercise real HTTP pagination -> sync API -> SQL -> health workflow."""
import asyncio
import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

import pytest
import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import repos
from app.api.routes.chat import _build_conversation_tools, _build_engineering_workflow_runtime, _engineering_workflow_response, _persist_engineering_workflow
from app.core.config import settings
from app.core.security import encrypt_token
from app.db.models import AgentWorkflowRun, Base, Issue, PRFile, PRReviewComment, Repository, WorkflowRun
from app.db.session import get_db
from app.schemas.repos import RepoSyncRequest
from app.schemas.workflow import WorkflowClaim, WorkflowSpec, WorkflowTask
from app.services.agents.workflow_orchestrator import WorkflowOrchestrator
from app.services.github.actions import list_workflow_runs
from app.services.github.client import GitHubClient
from app.services.github.issues import list_issues
from app.services.github.pull_requests import list_pull_requests
from app.services.repos_sync import sync_repository


@pytest.fixture
def github_server():
    state = {
        "data": {},
        "metadata": {},
        "errors": {},
        "requests": [],
        "auth_headers": [],
        "bad_shape": False,
        "repeat_link": False,
        "disconnect": False,
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            page = int(query.get("page", [1])[0])
            per_page = int(query.get("per_page", [30])[0])
            state["requests"].append((parsed.path, page, per_page))
            state["auth_headers"].append(self.headers.get("Authorization"))
            if state["disconnect"]:
                self.close_connection = True
                return
            status = state["errors"].get((parsed.path, page), state["errors"].get(parsed.path, 200))
            metadata = state["metadata"].get(parsed.path)
            has_next = False
            if metadata is not None:
                # 仓库元数据是单个 JSON 对象，不走列表分页。
                payload = metadata
            else:
                items = state["data"].get(parsed.path, [])
                batch = items[(page - 1) * per_page:page * per_page]
                payload = batch
                if parsed.path.endswith("/actions/runs"):
                    payload = {"total_count": len(items), "workflow_runs": batch}
                elif parsed.path.endswith("/jobs"):
                    payload = {"total_count": len(items), "jobs": batch}
                has_next = page * per_page < len(items)
            if state["bad_shape"]:
                payload = {"unexpected": "not a list"}
            if status != 200:
                payload = {"message": "permission denied"}
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            if has_next or state["repeat_link"]:
                params = {key: values[0] for key, values in query.items()}
                params["page"] = page if state["repeat_link"] else page + 1
                next_url = f"http://127.0.0.1:{self.server.server_port}{parsed.path}?{urlencode(params)}"
                self.send_header("Link", f'<{next_url}>; rel="next"')
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["url"] = f"http://127.0.0.1:{server.server_port}"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.fixture
def database(github_server):
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        repo = Repository(owner="acme", name="demo", full_name="acme/demo", provider="github_compatible", api_base_url=github_server["url"])
        db.add(repo)
        db.commit()
        yield db, repo
    engine.dispose()


def populate(server):
    server["data"] = {
        "/repos/acme/demo/issues": [{"id": i, "number": i, "title": f"Issue {i}", "state": "open"} for i in range(1, 206)],
        "/repos/acme/demo/pulls": [{"id": 1001, "number": 901, "title": "PR", "state": "open"}],
        "/repos/acme/demo/pulls/901/files": [{"filename": f"file{i}.py", "status": "modified"} for i in range(105)],
        "/repos/acme/demo/pulls/901/comments": [{"id": i, "body": f"Comment {i}"} for i in range(105)],
        "/repos/acme/demo/actions/runs": [{"id": 2001, "name": "CI", "status": "completed", "conclusion": "success"}],
        "/repos/acme/demo/actions/runs/2001/jobs": [{"id": i, "name": f"Job {i}", "conclusion": "success"} for i in range(105)],
    }


@pytest.mark.asyncio
async def test_full_sync_traverses_all_lists_and_persists_facts(github_server, database):
    populate(github_server)
    db, repo = database
    result = await sync_repository(db, repo, RepoSyncRequest())
    assert result.status == "completed"
    assert result.synced == {"issues": 205, "pull_requests": 1, "workflow_runs": 1}
    assert result.sources["issues"]["pages"] == 3
    assert all(source["complete"] for source in result.sources.values())
    assert db.query(Issue).count() == 205
    assert db.query(PRFile).count() == 105
    assert db.query(PRReviewComment).count() == 105
    assert len(db.query(WorkflowRun).one().jobs) == 105
    assert len(set(github_server["requests"])) == len(github_server["requests"])
    db.expire_all()
    assert db.get(Repository, repo.id).sync_metadata["status"] == "completed"
    # Repeating a full sync updates records instead of duplicating them.
    await sync_repository(db, repo, RepoSyncRequest())
    assert db.query(Issue).count() == 205
    assert db.query(PRFile).count() == 105


@pytest.mark.asyncio
async def test_scheduled_sync_defaults_to_all_pages(github_server, database, monkeypatch):
    from app.core.config import Settings, settings
    from app.db import session
    from app.services import scheduler

    assert Settings(_env_file=None).auto_sync_limit is None
    populate(github_server)
    db, repo = database
    monkeypatch.setattr(settings, "auto_sync_enabled", True)
    monkeypatch.setattr(settings, "auto_sync_limit", None)
    factory = sessionmaker(bind=db.get_bind())
    monkeypatch.setattr(session, "SessionLocal", factory)
    monkeypatch.setattr(scheduler, "SessionLocal", factory)
    sleeps = 0

    async def stop_after_first_sync(_seconds):
        nonlocal sleeps
        sleeps += 1
        if sleeps > 1:
            raise asyncio.CancelledError()

    monkeypatch.setattr(scheduler.asyncio, "sleep", stop_after_first_sync)
    with pytest.raises(asyncio.CancelledError):
        await scheduler.periodic_repo_sync_loop()
    db.expire_all()
    assert db.query(Issue).count() == 205
    assert repo.sync_metadata["status"] == "completed"
    assert repo.sync_metadata["sources"]["issues"]["pages"] == 3


@pytest.mark.asyncio
async def test_issue_limit_counts_issues_after_filtering_pr_pages(github_server):
    github_server["data"]["/repos/acme/demo/issues"] = [
        {"id": i, "pull_request": {}} for i in range(3)
    ] + [{"id": i} for i in range(10, 15)]
    items = await list_issues("acme", "demo", limit=3, base_url=github_server["url"])
    assert [item["id"] for item in items] == [10, 11, 12]
    assert items.pages == 2
    assert items.complete is False


@pytest.mark.asyncio
async def test_limit_over_100_fetches_more_pages_and_marks_truncation(github_server, database):
    populate(github_server)
    db, repo = database
    result = await sync_repository(db, repo, RepoSyncRequest(limit=150))
    assert result.status == "partial"
    assert result.synced["issues"] == 150
    assert result.sources["issues"]["pages"] == 2
    assert result.sources["issues"]["complete"] is False
    assert max(request[2] for request in github_server["requests"]) <= 100
    assert repo.last_sync_at is None


@pytest.mark.asyncio
async def test_actions_object_response_is_paginated(github_server):
    github_server["data"]["/repos/acme/demo/actions/runs"] = [{"id": i} for i in range(205)]
    items = await list_workflow_runs("acme", "demo", limit=None, base_url=github_server["url"])
    assert len(items) == 205
    assert items.pages == 3 and items.complete


@pytest.mark.asyncio
async def test_pull_request_list_traverses_all_pages(github_server):
    github_server["data"]["/repos/acme/demo/pulls"] = [{"id": i} for i in range(205)]
    items = await list_pull_requests("acme", "demo", limit=None, base_url=github_server["url"])
    assert len(items) == 205
    assert items.pages == 3 and items.complete


@pytest.mark.asyncio
async def test_exact_limit_at_last_page_is_complete(github_server):
    github_server["data"]["/repos/acme/demo/issues"] = [{"id": i} for i in range(150)]
    items = await list_issues("acme", "demo", limit=150, base_url=github_server["url"])
    assert len(items) == 150 and items.pages == 2 and items.complete


@pytest.mark.asyncio
async def test_connection_failure_is_persisted_as_failed(github_server, database):
    github_server["disconnect"] = True
    db, repo = database
    result = await sync_repository(db, repo, RepoSyncRequest())
    assert result.status == "failed"
    assert len(result.errors) == 3
    assert all("RemoteProtocolError" in error for error in result.errors)
    assert repo.last_sync_at is None


@pytest.mark.asyncio
async def test_timeout_is_not_reported_as_empty(database, monkeypatch):
    async def timeout(*_args, **_kwargs):
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr("app.services.repos_sync.list_workflow_runs", timeout)
    db, repo = database
    result = await sync_repository(db, repo, RepoSyncRequest())
    assert result.status == "partial"
    assert result.sources["workflow_runs"]["status"] == "failed"
    assert result.errors == ["workflow_runs: ReadTimeout"]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 404, 500])
async def test_failed_source_is_not_reported_as_empty(github_server, database, status):
    populate(github_server)
    github_server["errors"]["/repos/acme/demo/actions/runs"] = status
    db, repo = database
    previous = datetime.now(timezone.utc) - timedelta(days=1)
    repo.last_sync_at = previous
    result = await sync_repository(db, repo, RepoSyncRequest())
    assert result.status == "partial"
    assert result.sources["workflow_runs"]["status"] == "failed"
    assert result.errors == [f"workflow_runs: HTTP {status}"]
    assert repo.last_sync_at.replace(tzinfo=timezone.utc) == previous
    assert db.query(Issue).count() == 205


@pytest.mark.asyncio
async def test_second_page_failure_preserves_previous_records(github_server, database):
    populate(github_server)
    db, repo = database
    db.add(Issue(repo_id=repo.id, github_issue_id=999, number=999, title="Previously synced", state="open"))
    db.commit()
    github_server["errors"][("/repos/acme/demo/issues", 2)] = 403
    result = await sync_repository(db, repo, RepoSyncRequest(sync_pull_requests=False, sync_workflow_runs=False))
    assert result.status == "failed"
    assert db.query(Issue).one().title == "Previously synced"
    assert result.sources["issues"]["status"] == "failed"


@pytest.mark.asyncio
async def test_detail_failures_keep_existing_files_comments_jobs_and_logs(github_server, database):
    populate(github_server)
    db, repo = database
    await sync_repository(db, repo, RepoSyncRequest())
    run = db.query(WorkflowRun).one()
    run.logs_text = "previous log"
    db.commit()
    github_server["data"]["/repos/acme/demo/actions/runs"][0]["conclusion"] = "failure"
    for suffix in ("pulls/901/files", "pulls/901/comments", "actions/runs/2001/jobs", "actions/runs/2001/logs"):
        github_server["errors"][f"/repos/acme/demo/{suffix}"] = 403
    result = await sync_repository(db, repo, RepoSyncRequest())
    assert result.status == "partial"
    assert len(result.errors) == 4
    assert db.query(PRFile).count() == 105
    assert db.query(PRReviewComment).count() == 105
    assert len(run.jobs) == 105
    assert run.logs_text == "previous log"


@pytest.mark.asyncio
async def test_empty_sync_is_distinct_from_skipped(github_server, database):
    db, repo = database
    empty = await sync_repository(db, repo, RepoSyncRequest())
    assert empty.status == "empty" and not empty.errors
    assert all(source["status"] == "empty" and source["complete"] for source in empty.sources.values())
    previous = repo.last_sync_at
    skipped = await sync_repository(db, repo, RepoSyncRequest(sync_issues=False, sync_pull_requests=False, sync_workflow_runs=False))
    assert skipped.status == "skipped"
    assert repo.last_sync_at == previous


@pytest.mark.asyncio
@pytest.mark.parametrize("state,expected", [("never", "not_synced"), ("empty", "empty"), ("empty_with_history", "empty"), ("failed", "failed"), ("partial", "partial"), ("old", "stale"), ("legacy", "unknown"), ("full", "ready")])
async def test_health_summary_and_workflow_gate_missing_or_incomplete_data(github_server, database, state, expected, monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", None)
    db, repo = database
    if state in {"partial", "old", "legacy", "full"}:
        populate(github_server)
    if state == "failed":
        for path in ("issues", "pulls", "actions/runs"):
            github_server["errors"][f"/repos/acme/demo/{path}"] = 403
    if state not in {"never", "legacy"}:
        await sync_repository(db, repo, RepoSyncRequest(limit=1 if state == "partial" else None))
    if state == "old":
        repo.sync_metadata = {**repo.sync_metadata, "attempted_at": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()}
    if state in {"legacy", "empty_with_history"}:
        db.add(Issue(repo_id=repo.id, number=99, title="Legacy data", state="open"))
    db.commit()
    tools = _build_conversation_tools(repo, None, db)
    summary = await tools["repo_health.generate_summary"]({}, {})
    assert summary["data_status"] == expected
    assert "数据说明" in summary["answer"]
    context, runners = _build_engineering_workflow_runtime(repo, db, "仓库健康状态", {})
    task = WorkflowTask(id="repo_health", agent_name="repo_health_agent", task_type="repo_health", objective="Assess health", claim=WorkflowClaim(target_type="repository", target_id=str(repo.id)))
    spec = WorkflowSpec(goal="Assess health", trigger_message="health", tasks=[task])
    report = await WorkflowOrchestrator(runners).run_spec(spec, context, allow_replan=False)
    result = report["task_results"][0]
    assert result["confidence"] is None
    assert result["output"]["data_status"] == expected
    if state == "full":
        assert result["status"] == "success"
        assert result["evidence_count"] == 207
        assert "CI 1 次（成功 1，失败 0，其它 0）" in result["summary"]
        assert "整体健康仍需" in report["final_answer"]
    else:
        assert any(f["finding_type"] == "evidence_gap" and f["severity"] == "blocker" for f in report["observation"]["findings"])
        assert "当前不建议直接推进" in report["final_answer"]
    if state in {"never", "empty", "empty_with_history"}:
        assert result["status"] == "skipped"
        assert "Issues：0" not in summary["answer"]
    if state == "failed":
        assert result["status"] == "error"
    workflow_id = _persist_engineering_workflow(db, repo, None, report)
    # 规则综合不是模型故障；已有硬门禁时跳过模型，无硬门禁但缺密钥才是一次降级。
    assert report["synthesis"]["mode"] == "rules"
    assert report["metrics"]["model_fallback_count"] == (1 if state == "full" else 0)
    assert report["observation"]["model_review"]["reason"] == ("not_configured" if state == "full" else "hard_findings_first")
    expected_status = "error" if state == "failed" else "partial"
    assert db.get(AgentWorkflowRun, workflow_id).status == expected_status
    response = _engineering_workflow_response(repo, workflow_id, report)
    assert response["tool_calls"][0]["status"] == expected_status


def test_sync_api_exposes_persisted_failure_and_complete_pagination(github_server, database, monkeypatch):
    db, repo = database
    app = FastAPI()
    app.include_router(repos.router, prefix="/api/repos")
    app.dependency_overrides[get_db] = lambda: db

    async def no_code_analysis(*_args):
        pass

    monkeypatch.setattr(repos, "sync_repository_code_analysis_by_id", no_code_analysis)
    with TestClient(app) as client:
        for path in ("issues", "pulls", "actions/runs"):
            github_server["errors"][f"/repos/acme/demo/{path}"] = 403
        failed = client.post(f"/api/repos/{repo.id}/sync", json={})
        assert failed.status_code == 502
        assert failed.json()["status"] == "failed"
        assert client.get(f"/api/repos/{repo.id}/sync-status").json()["status"] == "failed"
        github_server["errors"].clear()
        populate(github_server)
        response = client.post(f"/api/repos/{repo.id}/sync", json={})
        assert response.status_code == 200
        assert response.json()["synced"]["issues"] == 205
        assert response.json()["sources"]["issues"]["pages"] == 3
        assert client.get(f"/api/repos/{repo.id}/sync-status").json()["status"] == "completed"
        listing = client.get("/api/repos").json()
        assert listing[0]["sync_metadata"]["status"] == "completed"


def _api_app(db, monkeypatch):
    app = FastAPI()
    app.include_router(repos.router, prefix="/api/repos")
    app.dependency_overrides[get_db] = lambda: db
    scheduled = []

    async def record_code_analysis(repo_id):
        scheduled.append(repo_id)

    monkeypatch.setattr(repos, "sync_repository_code_analysis_by_id", record_code_analysis)
    return app, scheduled


def test_full_sync_endpoint_refreshes_metadata_and_all_pages(github_server, database, monkeypatch):
    populate(github_server)
    github_server["metadata"]["/repos/acme/demo"] = {
        "id": 4242,
        "description": "Remote description",
        "default_branch": "trunk",
        "clone_url": "https://example.test/acme/demo.git",
    }
    db, repo = database
    repo.default_branch = "master"
    repo.github_token_encrypted = encrypt_token("token-abc", settings.token_encryption_key)
    db.commit()
    app, scheduled = _api_app(db, monkeypatch)

    with TestClient(app) as client:
        response = client.post(f"/api/repos/{repo.id}/full-sync")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["synced"] == {"issues": 205, "pull_requests": 1, "workflow_runs": 1}
    assert body["sources"]["issues"]["pages"] == 3
    assert all(source["complete"] for source in body["sources"].values())
    assert body["metadata_refreshed"] is True
    assert body["metadata_error"] is None
    assert body["metadata"]["default_branch"] == "trunk"
    assert body["metadata"]["github_id"] == 4242
    assert "Bearer token-abc" in github_server["auth_headers"]
    assert scheduled == [repo.id]

    db.expire_all()
    updated = db.get(Repository, repo.id)
    assert updated.description == "Remote description"
    assert updated.default_branch == "trunk"
    assert updated.clone_url == "https://example.test/acme/demo.git"
    assert updated.github_id == 4242
    assert updated.sync_metadata["limit"] is None


def test_full_sync_metadata_failure_is_best_effort(github_server, database, monkeypatch):
    populate(github_server)
    github_server["errors"]["/repos/acme/demo"] = 403
    db, repo = database
    repo.default_branch = "master"
    db.commit()
    app, scheduled = _api_app(db, monkeypatch)

    with TestClient(app) as client:
        response = client.post(f"/api/repos/{repo.id}/full-sync")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["synced"] == {"issues": 205, "pull_requests": 1, "workflow_runs": 1}
    assert body["metadata_refreshed"] is False
    assert body["metadata_error"] == "metadata: HTTP 403"
    assert scheduled == [repo.id]

    db.expire_all()
    assert db.get(Repository, repo.id).default_branch == "master"


def test_full_sync_total_source_failure_still_returns_structured_body(github_server, database, monkeypatch):
    github_server["metadata"]["/repos/acme/demo"] = {"id": 1, "default_branch": "master"}
    for path in ("issues", "pulls", "actions/runs"):
        github_server["errors"][f"/repos/acme/demo/{path}"] = 403
    db, repo = database
    app, scheduled = _api_app(db, monkeypatch)

    with TestClient(app) as client:
        response = client.post(f"/api/repos/{repo.id}/full-sync")

    # 刻意区别于 /sync 的 502：全量同步要保留 sources/errors 让前端展示逐来源结果。
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["synced"] == {"issues": 0, "pull_requests": 0, "workflow_runs": 0}
    assert len(body["errors"]) == 3
    assert scheduled == [repo.id]


def test_full_sync_unknown_repo_returns_404(github_server, database, monkeypatch):
    db, _repo = database
    app, _scheduled = _api_app(db, monkeypatch)
    with TestClient(app) as client:
        response = client.post(f"/api/repos/{uuid4()}/full-sync")
    assert response.status_code == 404


def test_connect_reuses_shared_metadata_helper(github_server, database, monkeypatch):
    github_server["metadata"]["/repos/acme/demo"] = {
        "id": 5151,
        "description": "Connected description",
        "default_branch": "trunk",
        "clone_url": "https://example.test/acme/demo.git",
    }
    db, _repo = database
    app, scheduled = _api_app(db, monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/api/repos/connect",
            json={
                "owner": "acme",
                "repo": "demo",
                "provider": "github_compatible",
                "api_base_url": github_server["url"],
                "token": "token-abc",
                "initial_sync_limit": 5,
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is True
    db.expire_all()
    updated = db.query(Repository).filter(Repository.full_name == "acme/demo").one()
    assert updated.description == "Connected description"
    assert updated.default_branch == "trunk"
    assert updated.clone_url == "https://example.test/acme/demo.git"
    assert updated.github_id == 5151
    assert scheduled == [updated.id]


@pytest.mark.asyncio
async def test_ci_status_tools_report_successful_runs_instead_of_missing_data(github_server, database):
    db, repo = database
    now = datetime.now(timezone.utc)
    repo.sync_metadata = {
        "status": "completed",
        "sources": {
            "issues": {"status": "completed", "count": 0, "complete": True, "pages": 1},
            "pull_requests": {"status": "completed", "count": 0, "complete": True, "pages": 1},
            "workflow_runs": {"status": "completed", "count": 2, "complete": True, "pages": 1},
        },
        "errors": [],
        "attempted_at": now.isoformat(),
    }
    repo.last_sync_at = now
    db.add_all(
        [
            WorkflowRun(repo_id=repo.id, github_run_id=101, name="Backend CI", status="completed", conclusion="success", created_at=now),
            WorkflowRun(repo_id=repo.id, github_run_id=100, name="Frontend CI", status="completed", conclusion="success", created_at=now - timedelta(minutes=5)),
        ]
    )
    db.commit()
    tools = _build_conversation_tools(repo, None, db)

    health = await tools["repo_health.generate_summary"]({}, {})
    assert health["data_status"] == "ready"
    assert "已同步 2 次 CI 运行" in health["answer"]
    assert "2 次成功" in health["answer"]
    assert "已同步范围内没有失败运行" in health["answer"]
    assert "还没有同步到失败 CI 运行" not in health["answer"]

    runs = await tools["ci.list_workflow_runs"]({}, {})
    assert runs["route"] == "ci_runs"
    assert runs["ci"]["status"] == "all_success"
    assert "共 2 条" in runs["answer"]
    assert "Backend CI" in runs["answer"]
    assert len(runs["runs"]) == 2

    sync_status = await tools["repo.get_sync_status"]({}, {})
    assert sync_status["route"] == "repo_sync_status"
    assert sync_status["sync_status"]["status"] == "completed"
    assert sync_status["sync_status"]["counts"]["workflow_runs"] == 2
    assert "workflow_runs: status=completed" in sync_status["answer"]

    ci_debug = await tools["ci_debug_agent.analyze_workflow_run"]({}, {})
    assert ci_debug["route"] == "ci_status"
    assert "没有可排障的失败 CI" in ci_debug["answer"]
    assert "2 次成功" in ci_debug["answer"]
    assert "尚未同步" not in ci_debug["answer"]


@pytest.mark.asyncio
async def test_ci_status_tools_distinguish_no_runs_from_all_success(github_server, database):
    db, repo = database
    tools = _build_conversation_tools(repo, None, db)

    health = await tools["repo_health.generate_summary"]({}, {})
    assert "尚未同步到 CI 运行记录" in health["answer"]

    runs = await tools["ci.list_workflow_runs"]({}, {})
    assert runs["ci"]["status"] == "no_runs"
    assert "共 0 条" in runs["answer"]

    ci_debug = await tools["ci_debug_agent.analyze_workflow_run"]({}, {})
    assert ci_debug["route"] == "ci_status"
    assert "尚未同步到任何 CI 运行记录" in ci_debug["answer"]


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["bad_shape", "repeat_link"])
async def test_invalid_pagination_fails_explicitly(github_server, fault):
    github_server[fault] = True
    with pytest.raises(ValueError):
        await GitHubClient(base_url=github_server["url"]).get_paginated("/repos/acme/demo/issues")


def test_startup_upgrades_existing_database_without_losing_repository(tmp_path, monkeypatch):
    from app import main
    from app.core.config import settings
    from app.db import session

    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'legacy.db').as_posix()}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        repo = Repository(owner="acme", name="legacy", full_name="acme/legacy")
        db.add(repo)
        db.commit()
        repo_id = str(repo.id)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE repositories DROP COLUMN sync_metadata"))
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(session, "SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(settings, "auto_sync_enabled", False)
    monkeypatch.setattr(settings, "milvus_enabled", False)
    app = main.create_app()
    # Run real startup twice to verify both the upgrade and its idempotency.
    for _ in range(2):
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
    assert "sync_metadata" in {column["name"] for column in inspect(engine).get_columns("repositories")}
    with Session(engine) as db:
        repo = db.query(Repository).one()
        assert str(repo.id) == repo_id and repo.full_name == "acme/legacy"
        assert repo.sync_metadata is None
    engine.dispose()
