# Pydantic Schema 校验写法解析

> 分析对象：[backend/app/schemas/](../backend/app/schemas/) 及项目内的 Pydantic 使用方式  
> 学习目标：理解 Schema 目录的组织方式、模型角色的划分、校验链路，以及可复用的写法  
> 技术版本：`pydantic==2.10.4`、`fastapi==0.115.6`、`pydantic-settings==2.10.1`  
> 整理日期：2026-10-28

---

## 目录

1. [整体结构](#一整体结构契约目录--三处内部模型)
2. [一个 Schema 文件的构成](#二一个-schema-文件的构成以-issuespy-为例)
3. [六种模型角色](#三六种模型角色)
4. [约束与校验的写法](#四约束与校验的写法)
5. [三层校验链路](#五三层校验链路)
6. [与 ORM、路由的配合](#六与-orm路由的配合)
7. [可直接复用的 10 个写法](#七可直接复用的-10-个写法)
8. [注意事项与可改进点](#八注意事项与可改进点)
9. [新增接口 Checklist](#九新增接口-checklist)
10. [相关文件速查](#十相关文件速查)

---

## 一、整体结构：契约目录 + 三处内部模型

项目的 Pydantic 使用分成两类位置，职责不同：

| 位置 | 职责 | 是否对外 |
|---|---|---|
| `backend/app/schemas/` | API 请求/响应契约、Agent 输出契约 | 是 |
| `backend/app/core/config.py` | 环境配置（`BaseSettings`） | 否 |
| `backend/app/services/agents/workflow_models.py` | 工作流 LLM 输出模型 | 否 |
| `backend/app/services/skills/registry.py` | Skill 清单与激活记录 | 否 |

`backend/app/schemas/` 下有 **19 个文件、96 个模型类**，路由中用 `response_model=` 声明了 **68 处**响应契约。文件划分以业务模块为单位，基本与 `api/routes/` 一一对应：

| 文件 | 类数 | 主要角色 |
|---|---:|---|
| [rag.py](../backend/app/schemas/rag.py) | 14 | 知识库配置、上传、切片、召回、问答 |
| [knowledge.py](../backend/app/schemas/knowledge.py) | 14 | 文档、记忆、团队、图谱 |
| [workflow.py](../backend/app/schemas/workflow.py) | 8 | 任务图 Spec / TaskResult / Observation |
| [analysis.py](../backend/app/schemas/analysis.py) | 8 | Issue / PR / CI / 安全 Agent 输出 |
| [chat.py](../backend/app/schemas/chat.py) | 7 | 对话请求、响应、历史、工具轨迹 |
| [skills.py](../backend/app/schemas/skills.py) | 5 | Skill 清单与 MCP 工具 |
| [repos.py](../backend/app/schemas/repos.py) | 5 | 仓库连接、同步 |
| [action_drafts.py](../backend/app/schemas/action_drafts.py) | 4 | 安全草稿、审计 |
| [evals.py](../backend/app/schemas/evals.py) | 4 | 评测请求与结果 |
| [project_index.py](../backend/app/schemas/project_index.py) | 4 | 项目索引状态 |
| [pull_requests.py](../backend/app/schemas/pull_requests.py) | 4 | PR、文件、评论、分析 |
| [workspaces.py](../backend/app/schemas/workspaces.py) | 4 | 多仓库工作区 |
| [feedback.py](../backend/app/schemas/feedback.py) | 3 | 回答反馈与复核 |
| 其余 6 个文件 | 各 2 | `issues` / `ci` / `search` / `reports` / `conversations` / `code_graph` |

目录内部只有一条依赖链，**没有循环依赖**：

```
analysis.py  ←── issues.py
             ←── ci.py
             ←── pull_requests.py
```

其余文件只依赖标准库和 Pydantic，彼此独立。`analysis.py` 是唯一被服务层（Agent、评测、`structured_outputs.py`）大量复用的跨层契约。

---

## 二、一个 Schema 文件的构成（以 `issues.py` 为例）

[backend/app/schemas/issues.py](../backend/app/schemas/issues.py) 只有 29 行，但完整展示了这类文件的四个组成部分。

### 1. 文件头注释：声明契约意图

```python
# Issue 与分析响应的展示契约；内部 UUID、GitHub ID 和可见编号分别有不同用途。
```

项目里每个 schema 文件都以一行注释开头，说明三件事：这个契约约束什么、边界在哪、容易混淆的概念是什么。这里的「ID、GitHub ID、number」分别对应用户不可见的主键、远端同步标识、仓库内可见编号。

### 2. 导入区：三类依赖

```python
from datetime import datetime      # 标准库：时间字段
from uuid import UUID              # 标准库：主键，FastAPI 序列化为字符串
from pydantic import BaseModel     # Pydantic：校验与序列化
from app.schemas.analysis import IssueAnalysisOutput  # 跨文件复用
```

顺序稳定为：标准库 → 第三方 → 项目内。最后一行是全目录仅有的三种跨文件依赖之一。

### 3. 实体型响应模型：`IssueResponse`

```python
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

    model_config = {"from_attributes": True}
```

它映射 [db/models.py](../backend/app/db/models.py) 的 `Issue`，但只保留展示需要的字段：

| ORM 字段 | Schema 是否保留 | 原因 |
|---|---|---|
| `id` / `repo_id` | ✅ | 定位对象与隔离边界 |
| `github_issue_id` | ❌ | 远端同步用的内部标识 |
| `number` | ✅ | 仓库内可见编号 |
| `closed_at` | ❌ | 当前 UI 不需要 |
| `title` / `body` / `state` / `labels` | ✅ | 展示字段 |

字段写法遵循三条规则：

- **必填**：`id`、`repo_id`、`number`、`title`、`state` 无默认值，缺失即 422
- **可空**：`body`、`author`、时间字段用 `| None = None`
- **集合默认空**：`labels`、`assignees` 用 `= []`

### 4. `from_attributes = True` 的作用

路由里是直接返回 ORM 对象的：

```python
# backend/app/api/routes/issues.py:279
@router.get("/repos/{repo_id}/issues", response_model=list[IssueResponse])
async def list_issues(repo_id: UUID, db: Session = Depends(get_db)) -> list[Issue]:
    return db.query(Issue).filter(...).all()
```

FastAPI 用 `response_model` 校验返回值时，`from_attributes` 允许 Pydantic 从对象的**属性**上取值。没有它，Pydantic 只接受 dict，会抛出 `Input should be a valid dictionary or instance of IssueResponse`。

这个配置同时完成了**字段裁剪**：ORM 上的 `github_issue_id`、`closed_at` 不在模型里，就不会出现在响应中。

### 5. 包装型响应模型：`IssueAnalysisResponse`

```python
class IssueAnalysisResponse(BaseModel):
    analysis_id: UUID | str
    result: IssueAnalysisOutput
```

这不是数据库实体映射，而是接口返回结构的封装：

- `analysis_id: UUID | str`：正常持久化后是 UUID，联合 `str` 兼容历史数据/流式事件
- `result: IssueAnalysisOutput`：嵌套 `analysis.py` 中的 Agent 输出契约
- 没有 `from_attributes`：它是在路由里手动构造的，不是从 ORM 读取：

```python
# backend/app/api/routes/issues.py:305
return IssueAnalysisResponse(analysis_id=analysis.id, result=result)
```

---

## 三、六种模型角色

### 1. 请求模型（Request）

用于校验客户端入参，通常带字段约束。

```python
# schemas/chat.py:7
class ChatRequest(BaseModel):
    repo_id: UUID
    conversation_id: UUID | None = None
    message: str
    context: dict = Field(default_factory=dict)
```

FastAPI 会把请求体自动解析成该模型，失败返回 422。请求模型也可以继承扩展：

```python
# schemas/chat.py:14
class ChatPlanExecuteRequest(ChatRequest):
    workflow_spec: dict
```

### 2. 响应/读模型（Response）

用于约束返回结构，常见 `from_attributes = True`。

```python
# schemas/feedback.py:41
class ChatFeedbackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    repo_id: UUID
    ...
```

### 3. 包装型模型（Wrapper）

组合多个对象或嵌套 Agent 输出，例如：

- `IssueAnalysisResponse = analysis_id + IssueAnalysisOutput`
- `ActionDraftConfirmResponse = draft + audit_id`
- `ChatResponse = run_id + message_id + answer + tool_calls + ...`

### 4. LLM 输出契约

`analysis.py` 与 `workflow_models.py` 属于这一类。它们的字段主要服务于**约束模型返回**，不是给前端展示。

```python
# schemas/analysis.py:26
class IssueAnalysisOutput(BaseModel):
    conclusion: Literal["进入开发", "等待澄清", "关闭", "拆分", "合并到已有 Issue"]
    priority: Literal["P0", "P1", "P2", "P3"]
    complexity: Literal["S", "M", "L", "XL"]
    confidence: float = Field(ge=0, le=1)
    ...
```

### 5. 服务内部领域模型

不一定放在 `schemas/`，用于服务内部传递结构化数据：

```python
# services/skills/registry.py:18
class SkillManifest(BaseModel):
    name: str
    version: str
    ...
```

### 6. 配置模型（Settings）

```python
# core/config.py:8
class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://..."
    llm_model: str = "deepseek-v4-pro"
    workflow_observer_timeout_seconds: float = Field(default=20.0, gt=0, le=60)
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"), env_file_encoding="utf-8", extra="ignore"
    )

settings = Settings()   # 导入时实例化
```

`BaseSettings` 把 `.env` 与进程环境变量转换成有类型的配置；`extra="ignore"` 允许 `.env` 中存在未声明变量。

---

## 四、约束与校验的写法

### 1. 类型与可选性

| 写法 | 含义 |
|---|---|
| `name: str` | 必填 |
| `name: str \| None = None` | 可空，可省略 |
| `items: list[str] = []` | 可省略，默认空列表 |
| `items: list[str] = Field(default_factory=list)` | 同上，项目内两种写法并存 |

Pydantic v2 会为每个实例深拷贝默认值，所以 `= []` 不存在 Python 函数默认参数那种共享可变对象问题。

### 2. 数值与长度约束

```python
score: float = Field(ge=0, le=1)                       # 闭区间
limit: int = Field(default=5, ge=1, le=20)             # 默认值 + 范围
comment: str | None = Field(default=None, max_length=1000)
objective: str = Field(min_length=1, max_length=1200)
evidence: list[FactQuote] = Field(min_length=2, max_length=4)  # 列表长度
```

约束写在 `Field` 里，校验失败会由 FastAPI 转成 422，或在 Agent 侧被捕获为 `invalid_output` 降级。

### 3. 用 `Literal` 代替字符串枚举

```python
FeedbackRating = Literal["helpful", "unhelpful"]
FeedbackReason = Literal["inaccurate", "not_relevant", ...]
```

类型别名集中定义在文件顶部，多个模型复用。好处是非法值在校验阶段就被拒绝，而不是等到业务逻辑里再判断。

### 4. 固定集合用 `Literal`，跨字段规则用 `model_validator`

```python
# schemas/feedback.py:21
class ChatFeedbackCreate(BaseModel):
    rating: FeedbackRating
    reason: FeedbackReason | None = None

    @model_validator(mode="after")
    def validate_reason(self) -> "ChatFeedbackCreate":
        if self.rating == "helpful" and self.reason is not None:
            raise ValueError("有帮助反馈不需要填写负反馈原因")
        return self
```

这是项目中唯一的 `model_validator`：单字段约束用 `Field`，**字段之间的联动**才用模型级校验。

### 5. 嵌套模型与默认实例

```python
class IssueAnalysisOutput(BaseModel):
    duplicate_candidates: list[DuplicateCandidate] = Field(default_factory=list)
    drafts: IssueDrafts = Field(default_factory=IssueDrafts)
```

嵌套模型会自动递归校验；`default_factory=IssueDrafts` 保证每个实例拿到独立的默认对象。

### 6. 别名与 `populate_by_name`

```python
# schemas/action_drafts.py:31
metadata: dict = Field(default_factory=dict, alias="meta")

model_config = {"from_attributes": True, "populate_by_name": True}
```

ORM 的属性名是 `meta`（数据库列名是 `metadata`），对外字段叫 `metadata`。`alias="meta"` 让 Pydantic 能从 ORM 读取，`populate_by_name` 允许用 `metadata=` 构造。

### 7. 严格模型 vs 宽松模型

工作流对 LLM 输出使用最严格的配置：

```python
# services/agents/workflow_models.py:19
class ModelOutput(BaseModel):
    # 禁止模型夹带未定义字段
    model_config = ConfigDict(extra="forbid", strict=True)
```

而工具参数模型故意放开：

```python
# services/agents/chat_agent.py:47
class GenericToolArgs(BaseModel):
    model_config = ConfigDict(extra="allow")
    message: str | None = Field(default=None, description="原始用户消息")
    ...
```

两者目标不同：

- LLM 计划/审查/综合 → 宁可拒绝，也不接受额外字段
- 通用工具参数 → 允许各工具带自己的参数，具体边界在工具函数里检查

### 8. 用 `model_json_schema()` 把契约写进提示词

```python
# services/agents/workflow_models.py:131
payload = {**payload, "output_schema": output_type.model_json_schema()}
...
# :148
output = output_type.model_validate(raw)
```

模型返回的 JSON 再经过同一个模型校验，失败则降级为 `rules_fallback`。这保证了「提示词描述的格式」和「代码校验的格式」是同一份来源，不会漂移。

---

## 五、三层校验链路

以 Issue 分析接口为例，同一个契约会经过三次边界：

```
LLM 原始 JSON
   │
   │ ① IssueAgent: IssueAnalysisOutput.model_validate(...)
   │    （字段类型、枚举、confidence 范围）
   ▼
IssueAnalysisOutput 对象
   │  .model_dump() → dict
   ▼
AnalysisResult.result_json（数据库 JSON 列）
   │
   │ ② 路由构造 IssueAnalysisResponse(analysis_id, result=dict)
   │    （嵌套模型再次校验）
   ▼
HTTP 响应
   │
   │ ③ FastAPI response_model 序列化与字段裁剪
   ▼
前端 JSON
```

对应代码：

```python
# services/agents/issue_agent.py:31
return IssueAnalysisOutput.model_validate(normalized).model_dump()

# api/routes/issues.py:305
return IssueAnalysisResponse(analysis_id=analysis.id, result=result)
```

**三层各自的职责**：

| 层 | 校验者 | 失败后果 |
|---|---|---|
| ① Agent 输出 | `analysis.py` 模型 | 走规则兜底或报错 |
| ② 响应组装 | 嵌套 Pydantic 模型 | 抛 `ValidationError` → 500 |
| ③ FastAPI 序列化 | `response_model` | 500，同时裁剪多余字段 |

### 流式接口是例外

SSE 接口无法使用 `response_model`，而是把 dict 直接 `json.dumps`：

```python
# api/routes/issues.py:308
@router.post("/issues/{issue_id}/analyze/stream")
async def analyze_issue_stream(...) -> StreamingResponse:
    return StreamingResponse(_issue_analysis_sse(...), media_type="text/event-stream")
```

```python
# api/routes/issues.py:273
yield _encode_sse("final", {"analysis_id": str(analysis.id), "result": result})
```

这条路径只经过 ① 的 Agent 校验，**没有 ② ③**。`/chat/stream`、`/plan/execute/stream`、PR/CI 的 stream 接口同理。这是项目里有意接受的取舍：流式响应需要逐块输出，无法整体校验；代价是最终事件的结构要靠 Agent 侧保证。

---

## 六、与 ORM、路由的配合

### 1. `from_attributes`：ORM 直接作为响应

```python
# api/routes/issues.py:284
@router.get("/issues/{issue_id}", response_model=IssueResponse)
async def get_issue(issue_id: UUID, db: Session) -> Issue:
    return db.get(Issue, issue_id)
```

无需 `IssueResponse.model_validate(issue)`，FastAPI 会自动完成。只有一种情况需要显式转换：模型配置缺失，或需要先做业务加工。

### 2. 手动构造：需要额外字段或嵌套时

```python
# api/routes/issues.py:305
return IssueAnalysisResponse(analysis_id=analysis.id, result=result)

# api/routes/rag.py:423
return RAGAnswerResponse.model_validate(result)
```

### 3. 请求体 → `model_dump`：写库与审计

```python
# api/routes/action_drafts.py:108
request_json=payload.model_dump(mode="json"),
```

`mode="json"` 把 `UUID`、`datetime` 等转成 JSON 可序列化类型，避免直接 `dict(payload)` 或 `.dict()`（Pydantic v2 已移除 `.dict()`）。

### 4. PATCH 语义：`exclude_unset`

```python
# api/routes/rag.py:155
changes = payload.model_dump(exclude_unset=True)
```

只更新客户端显式提交的字段，防止未提交字段的默认值覆盖已有配置。这是 PATCH 接口的关键细节。

### 5. 路由上的两种返回方式

| 方式 | 例子 | 特点 |
|---|---|---|
| `response_model=` | `GET /issues/{id}` | 自动校验、裁剪、生成 OpenAPI |
| 返回普通 `dict` | `POST /chat/plan`、SSE 接口 | 灵活，但无契约保护 |

项目中 `response_model` 覆盖 68 处，未覆盖的主要是流式接口和少量快速内置查询。

---

## 七、可直接复用的 10 个写法

1. **展示模型做 ORM 子集**  
   不把数据库模型直接暴露给前端，内部字段（`github_issue_id` 等）自然被裁剪。

2. **`from_attributes=True` + 直接 return ORM 对象**  
   读接口不需要手写序列化代码。

3. **包装模型组合 Agent 输出**  
   `analysis_id + result` 的形态让「本次分析记录」和「分析内容」边界清晰。

4. **ID 用 `UUID | str` 兼容多来源**  
   持久化记录是 UUID，流式事件/历史数据可能是字符串，联合类型避免两套模型。

5. **枚举用 `Literal` 类型别名集中定义**  
   如 `FeedbackRating`、`WorkflowTaskStatus`，提示词与后端校验共用同一组值。

6. **范围约束写进 `Field`**  
   `ge/le/min_length/max_length` 让非法值在入口被拒绝，而不是散落在业务判断里。

7. **跨字段规则用 `model_validator(mode="after")`**  
   例如「helpful 不应带失败原因」，只写这一处。

8. **LLM 输出用 `extra="forbid", strict=True`**  
   拒绝模型夹带未声明字段，校验失败明确降级，不静默接受。

9. **`model_json_schema()` 注入提示词**  
   让提示词里的输出格式与代码校验同源，减少格式漂移。

10. **`model_dump(mode="json", exclude_unset=True)`**  
    写 JSON 列用 `mode="json"`，PATCH 用 `exclude_unset=True`，语义清晰且不会写入意外字段。

---

## 八、注意事项与可改进点

### 1. 两种 `model_config` 写法并存

项目里同时存在：

```python
model_config = {"from_attributes": True}                     # 字典写法
model_config = ConfigDict(from_attributes=True)              # ConfigDict 写法
```

两者在 Pydantic v2 中都合法，但建议统一为 `ConfigDict(...)`：类型提示更完整，IDE 能发现拼写错误。

### 2. 默认值两种写法并存

```python
labels: list[str] = []                                  # 简写
items: list[str] = Field(default_factory=list)          # 显式工厂
```

Pydantic v2 对两者都会做深拷贝，行为一致。但从可读性和统一性看，建议集合字段统一用 `Field(default_factory=...)`。

### 3. 流式接口缺乏响应契约

SSE 的 `final` 事件结构只靠 Agent 校验与人工约定。可改进方式：

- 在 `_encode_sse` 前用响应模型 `model_dump()` 一次，至少保证结构一致
- 为流式事件定义独立的 `Event` 模型，并在测试中断言字段

### 4. 宽泛的 `dict` 削弱契约

```python
class EvalRunResponse(BaseModel):
    result: dict
```

以及 `ChatResponse` 中的 `agent_events: list[dict]`、`citations: list[dict]`。这些字段结构演进快，用 `dict` 是务实选择，但代价是 OpenAPI 无法描述、前端需要自行约定。建议对稳定下来的子结构抽取嵌套模型。

### 5. `UUID | str` 放宽了校验

`analysis_id: UUID | str`、`run_id: UUID | str` 兼容性更好，但字符串可以是任意内容。如果确认只有两种来源，可考虑 `UUID` 为主、在边界处显式转换；若保留联合类型，应在使用侧校验字符串格式。

### 6. `alias` 必须配合 `populate_by_name`

使用 `alias="meta"` 时，若忘记 `populate_by_name=True`，用字段名 `metadata=` 构造会失败，而从 ORM 读取则正常——这类问题往往只在一个调用路径上暴露，[action_drafts.py](../backend/app/schemas/action_drafts.py) 的处理是正确示范。

### 7. `Field` 约束替代不了业务校验

例如知识库配置里 `chunk_overlap` 与 `chunk_size` 的相对大小、`score_threshold` 与检索方法的组合，都不是单字段约束能表达的。Schema 负责「形状」，业务规则仍应在 service 层校验。

### 8. 大列表响应的校验成本

`response_model=list[IssueResponse]` 会对每个元素做一次校验。数据量大时这是可感知的开销；如果确认返回值可信（来自本系统 ORM），可以在路由上使用 `response_model` 的可选参数减少序列化字段，或在极端场景下显式转换后返回。

### 9. Schema 文件不要混入业务逻辑

API DTO 只做声明。`services/skills/registry.py` 的 `SkillDefinition` 带 `trace_metadata()`、`prompt_summary()` 方法，是因为它是**内部领域模型**而非 API DTO——这类纯格式化方法可以接受，但不应在 DTO 里查库、调外部服务。

---

## 九、新增接口 Checklist

新增一个接口时，按以下顺序落地：

1. **确定角色**：请求模型、响应模型、还是两者都有？
2. **放到对应文件**：`schemas/<业务模块>.py`；跨多个路由复用的契约才考虑独立文件（参考 `analysis.py`）。
3. **决定 `from_attributes`**：直接返回 ORM 对象时加；手动构造的包装模型不加。
4. **补约束**：必填/可空、`Field` 范围、`Literal` 枚举、跨字段 `model_validator`。
5. **路由声明**：`@router.post(..., response_model=XxxResponse)`，入参标注请求模型。
6. **处理特殊路径**：PATCH 用 `exclude_unset=True`；写 JSON 列用 `mode="json"`；SSE 接口至少保证最终事件结构一致。
7. **补测试**：非法枚举、越界数值、缺失必填字段各一条，验证 422。
8. **检查一致性**：字段命名、默认值写法、`ConfigDict` 写法与相邻文件保持一致。

---

## 十、相关文件速查

| 文件 | 作用 |
|---|---|
| [backend/app/schemas/](../backend/app/schemas/) | API 与 Agent 输出契约（19 文件 / 96 类） |
| [backend/app/schemas/analysis.py](../backend/app/schemas/analysis.py) | Issue / PR / CI / 安全 Agent 输出（跨层共享） |
| [backend/app/schemas/issues.py](../backend/app/schemas/issues.py) | Issue 读模型与响应包装（本文示例） |
| [backend/app/schemas/chat.py](../backend/app/schemas/chat.py) | 对话请求/响应、工具轨迹 |
| [backend/app/schemas/feedback.py](../backend/app/schemas/feedback.py) | `model_validator` 示例 |
| [backend/app/schemas/action_drafts.py](../backend/app/schemas/action_drafts.py) | `alias` + `populate_by_name` 示例 |
| [backend/app/services/agents/workflow_models.py](../backend/app/services/agents/workflow_models.py) | 严格 LLM 输出模型 + `model_json_schema()` |
| [backend/app/services/agents/chat_agent.py](../backend/app/services/agents/chat_agent.py) | 宽松工具参数模型 `GenericToolArgs` |
| [backend/app/services/skills/registry.py](../backend/app/services/skills/registry.py) | 内部领域模型 + `model_validate` 解析清单 |
| [backend/app/core/config.py](../backend/app/core/config.py) | `BaseSettings` 配置模型 |
| [backend/app/api/routes/](../backend/app/api/routes/) | `response_model` 与请求体使用点 |
| [docs/architecture/database_schema.md](../docs/architecture/database_schema.md) | 数据库表结构说明（与 Pydantic 契约区分） |

---

## 一句话总结

这套写法的核心是：**用 Pydantic 把「接口形状」和「模型输出形状」都变成可执行契约**——`schemas/` 负责对外边界，`analysis.py` 负责 LLM 输出边界，`from_attributes` 打通 ORM 与响应，`model_validate` 打通 LLM 与业务对象；Schema 只声明结构，业务规则留给 service，流式接口则明确接受契约弱化的取舍。
