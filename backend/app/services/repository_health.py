# 把本地计数、同步覆盖和新鲜度转成健康快照；“没有发现问题”不能等同于“没有取到数据”。
from datetime import datetime, timedelta, timezone

from app.db.models import Issue, PullRequest, Repository, WorkflowRun


def _run_time(run: WorkflowRun) -> datetime:
    value = run.created_at or run.updated_at
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _describe_run(run: WorkflowRun | None) -> dict | None:
    if run is None:
        return None
    return {
        "id": str(run.id),
        "github_run_id": run.github_run_id,
        "name": run.name,
        "status": run.status,
        "conclusion": run.conclusion,
        "html_url": run.html_url,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


# CI 结论必须区分“没有同步到运行”和“同步到的运行全部成功”，否则全绿会被误报成数据缺失。
def workflow_run_summary(runs: list[WorkflowRun]) -> dict:
    ordered = sorted(runs, key=_run_time, reverse=True)
    success = [run for run in ordered if run.conclusion == "success"]
    failure = [run for run in ordered if run.conclusion == "failure"]
    other = [run for run in ordered if run.conclusion not in {"success", "failure"}]
    latest_failure = next((run for run in ordered if run.conclusion == "failure"), None)
    return {
        "total": len(ordered),
        "success": len(success),
        "failure": len(failure),
        "other": len(other),
        "status": "no_runs" if not ordered else ("has_failures" if failure else "all_success"),
        "latest": _describe_run(ordered[0] if ordered else None),
        "latest_failure": _describe_run(latest_failure),
    }


def repository_health_snapshot(repo: Repository, issues: list[Issue], prs: list[PullRequest], runs: list[WorkflowRun]) -> dict:
    """Describe local evidence and its coverage, without treating absence as health."""
    evidence_count = len(issues) + len(prs) + len(runs)
    metadata = repo.sync_metadata or {}
    sources = metadata.get("sources") or {}
    if not metadata:
        state = "unknown" if evidence_count or repo.last_sync_at else "not_synced"
    elif metadata.get("status") == "failed":
        state = "failed"
    elif any(not sources.get(key, {}).get("complete") for key in ("issues", "pull_requests", "workflow_runs")):
        state = "partial"
    else:
        attempted_at = datetime.fromisoformat(metadata["attempted_at"]) if metadata.get("attempted_at") else None
        if attempted_at and attempted_at.tzinfo is None:
            attempted_at = attempted_at.replace(tzinfo=timezone.utc)
        if not attempted_at or datetime.now(timezone.utc) - attempted_at > timedelta(hours=24):
            state = "stale"
        else:
            state = "empty" if metadata.get("status") == "empty" or not evidence_count else "ready"
    messages = {
        "not_synced": "尚未同步仓库数据，暂无法评估仓库健康；请先执行同步。",
        "unknown": "已有本地记录，但缺少可验证的同步状态和覆盖范围；请重新同步后再评估。",
        "failed": "最近一次同步失败；已有记录仅可作为历史参考，暂无法评估当前仓库健康。",
        "partial": "同步数据不完整：部分数据源失败、未同步或达到数量上限；不能据此判断整个仓库健康。",
        "stale": "同步状态缺少有效时间或已超过 24 小时；数据可能过期，请刷新后再评估。",
        "empty": "本次同步请求成功，但未返回 Issue、PR、CI 记录；数据不足，暂无法评估当前仓库健康。",
        "ready": "以下为本地已同步记录的统计，不代表仓库整体健康或实时远端状态。",
    }
    return {
        "data_status": state,
        "data_sufficient": state == "ready",
        "status": "error" if state == "failed" else ("skipped" if state == "empty" or not evidence_count else "success"),
        "message": messages[state],
        "evidence_count": evidence_count,
        "ci": workflow_run_summary(runs),
        "confidence": None,  # No calibrated probability model exists for these counts.
        "sources": sources,
        "sync_errors": metadata.get("errors") or [],
        "last_sync_at": repo.last_sync_at.isoformat() if repo.last_sync_at else None,
    }
