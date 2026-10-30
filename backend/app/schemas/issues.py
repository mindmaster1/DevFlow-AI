# Issue 与分析响应的展示契约；内部 UUID、GitHub ID 和可见编号分别有不同用途。
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.schemas.analysis import IssueAnalysisOutput

# 在路由被引用

class IssueResponse(BaseModel):
    id: UUID
    repo_id: UUID
    number: int
    title: str
    body: str | None = None
    state: str
    labels: list[str] = []
    author: str | None = None
    assignees: list[str] = []
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # SQLAlchemy ORM 对象可以直接传给 Pydantic Response schema 自动映射字段，不需要手动做 dict 转换
    model_config = {"from_attributes": True}


class IssueAnalysisResponse(BaseModel):
    analysis_id: UUID | str
    result: IssueAnalysisOutput
