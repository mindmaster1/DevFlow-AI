# DevFlow AI 本地部署文档

> 部署日期：2026-10-22  
> 最后更新：2026-10-23（服务重启复核）  
> 部署环境：macOS 27.2 / Apple Silicon (arm64)  
> 项目路径：`/Users/smithdong/Desktop/DevFlow-AI`  
> 部署结果：后端、前端、PostgreSQL、Milvus、MinIO、etcd 全部可运行；RAG 与 DeepSeek ChatAgent 已通过端到端验证。

本文记录本次部署的完整操作、配置变更、验证结果和故障处理过程，可直接用于复现部署或后续运维。

---

## 1. 部署结果摘要

| 项目 | 结果 |
|---|---|
| 前端 Next.js | http://localhost:3000 ，HTTP 200 |
| 后端 FastAPI | http://localhost:8000 ，`/health` 返回 `{"status":"ok","app":"DevFlow AI"}` |
| API 文档 | http://localhost:8000/docs ，HTTP 200 |
| PostgreSQL | `localhost:5432`，容器 healthy，数据库 `devflow` |
| Milvus | `localhost:19530`，`/healthz` 返回 `OK`，集合 `devflow_rag_qwen1024` |
| MinIO / Silo | API `localhost:9000`，控制台 http://localhost:9001 |
| etcd | 容器内 `2379`（未映射到宿主机） |
| Embedding | Qwen/Qwen3-Embedding-0.6B，1024 维，本地推理 |
| LLM | DeepSeek `deepseek-v4-pro`，OpenAI 兼容接口 |
| GitHub | 已登录 `mindmaster1`，令牌已写入后端 `.env` |
| 演示数据 | 仓库 `course-demo/devflow-sample-api`，5 条 RAG 文档 |
| 离线测试 | 65 个 Workflow 相关测试全部通过 |

---

## 2. 环境与版本

### 2.1 主机

| 项目 | 值 |
|---|---|
| 操作系统 | macOS 27.2（Darwin 27.2.0） |
| 架构 | arm64（Apple Silicon） |
| Shell | zsh |
| 项目目录 | `/Users/smithdong/Desktop/DevFlow-AI` |

### 2.2 工具链

| 工具 | 版本 | 说明 |
|---|---|---|
| Homebrew | 7.0.10 | 安装系统级工具 |
| uv | 0.11.26 | 管理 Python 版本与虚拟环境 |
| Python | 3.12.13 | 由 uv 安装，位于 `backend/.venv` |
| Node.js | v26.10.0 | 运行 Next.js |
| npm | 11.19.1 | 安装前端依赖 |
| Git | 2.52.0 | 仓库克隆与代码分析 |
| Colima | 0.10.3 | macOS 上的 Docker 运行时 |
| Lima | 2.2.1 | Colima 依赖的虚拟机管理工具 |
| Docker CLI | 29.9.2 | 宿主机客户端 |
| Docker Compose | 5.6.1 | 以 CLI 插件方式安装 |
| Docker Engine | 29.5.2 | Colima 虚拟机内实际守护进程 |
| GitHub CLI (gh) | 2.103.0 | GitHub 登录与令牌管理 |

### 2.3 关键 Python 包

| 包 | 版本 |
|---|---|
| fastapi | 0.115.6 |
| uvicorn | 0.34.0 |
| pydantic | 2.10.4 |
| SQLAlchemy | 2.0.36 |
| psycopg | 3.2.3 |
| pymilvus | 3.0.2 |
| langchain | 1.2.17 |
| langgraph | 1.1.10 |
| ragas | 0.4.3 |
| openai | 2.53.0 |
| sentence-transformers | 6.2.0 |
| transformers | 5.20.2 |
| torch | 2.14.1 |
| httpx | 0.28.1 |

### 2.4 容器镜像

| 镜像 | 大小 | 用途 |
|---|---|---|
| `pgvector/pgvector:pg16` | 650 MB | PostgreSQL + pgvector 扩展 |
| `quay.io/coreos/etcd:v3.5.18` | 82.8 MB | Milvus 元数据存储 |
| `pgsty/silo:RELEASE.2026-09-16T00-00-00Z` | 207 MB | MinIO 兼容对象存储（Milvus 依赖） |
| `milvusdb/milvus:v2.5.4` | 2.19 GB | 向量数据库（standalone） |

> 说明：项目 `docker-compose.yml` 使用的是 MinIO 的社区分支 `pgsty/silo`，不是官方 `minio/minio` 镜像。该镜像兼容 MinIO 协议，并支持原有的 `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` 变量。

---

## 3. 架构与端口

```
浏览器
  │
  ├── http://localhost:3000  Next.js 前端
  │        │
  │        └── http://localhost:8000  FastAPI 后端
  │                  ├── PostgreSQL  localhost:5432
  │                  ├── Milvus      localhost:19530 / healthz 9091
  │                  ├── GitHub REST API（GITHUB_TOKEN）
  │                  └── DeepSeek API（LLM_API_KEY）
  │
  └── 本地基础设施（Docker Compose / Colima）
           ├── devflow-ai-postgres  5432
           ├── devflow-ai-etcd      容器内 2379
           ├── devflow-ai-minio     9000 / 9001
           └── devflow-ai-milvus    19530 / 9091
```

### 端口清单

| 端口 | 服务 | 是否暴露到宿主机 |
|---|---|---|
| 3000 | Next.js 前端 | 是 |
| 8000 | FastAPI 后端 | 是 |
| 5432 | PostgreSQL | 是 |
| 9000 | MinIO/Silo S3 API | 是 |
| 9001 | MinIO/Silo 控制台 | 是 |
| 19530 | Milvus gRPC | 是 |
| 9091 | Milvus 指标 / 健康检查 | 是 |
| 2379 | etcd | 否（仅容器网络） |
| 6379 | Redis（可选 profile） | 未启动 |

### Docker 数据卷

- `devflow_postgres_data`
- `devflow_etcd_data`
- `devflow_minio_data`

Milvus 自身数据通过 etcd + MinIO 持久化；PostgreSQL 数据在命名卷中。停止容器不会删除数据，`docker compose down` 也不会删除命名卷（除非加 `-v`）。

---

## 4. 部署前准备

### 4.1 确认系统状态

```bash
python3 --version        # 系统自带 3.9.6，版本过低，不能直接用
node --version           # v26.10.0
uv --version             # 0.11.26
docker --version         # 初始不存在
gh --version             # 初始不存在
brew --version           # 7.0.10
uname -m                 # arm64
```

项目要求：

- Python 3.10+（本项目使用 3.12）
- Node.js 18+（本项目使用 26）
- Docker + Docker Compose
- 可访问 Docker Hub、PyPI、Hugging Face（国内网络需要镜像加速）
- 约 10 GB 可用磁盘（镜像、虚拟环境、模型缓存）

### 4.2 部署方案选择

经确认采用以下方案：

| 决策点 | 选择 | 原因 |
|---|---|---|
| 容器运行时 | Colima | 纯命令行、无需 GUI/管理员授权，适合自动部署 |
| Embedding | 本地 Qwen3-Embedding-0.6B | 完整语义向量检索；DeepSeek 不提供 Embedding |
| DeepSeek Key | 复用本机 `.claude/settings.local.json` 中已有的 Key | 经项目负责人确认 |
| GitHub 登录 | `gh` 浏览器设备码登录 | 无需手动创建 PAT |

---

## 5. 详细部署步骤

### 5.1 安装系统工具

```bash
brew install colima docker docker-compose gh
```

安装内容：

- `colima 0.10.3`
- `docker 29.9.2`
- `docker-compose 5.6.1`
- `gh 2.103.0`
- 依赖 `lima 2.2.1`

Homebrew 的 `docker-compose` 默认安装为独立命令。为了支持 `docker compose` 子命令，建立 CLI 插件软链接：

```bash
mkdir -p ~/.docker/cli-plugins
ln -sf /opt/homebrew/bin/docker-compose ~/.docker/cli-plugins/docker-compose
docker compose version   # 输出：Docker Compose version 5.6.1
```

### 5.2 安装并配置 Colima

首次启动：

```bash
colima start --cpu 4 --memory 8 --disk 60 --vm-type vz
```

参数含义：

- 4 vCPU、8 GB 内存：满足 Milvus standalone 的常规内存需求
- 60 GB 磁盘：镜像 + 数据 + 向量索引
- `vz`：使用 macOS Virtualization.framework，Apple Silicon 性能更好

首次启动遇到并解决了三个问题：

1. **虚拟机内没有可用的 `/etc/resolv.conf`**  
   Ubuntu 24.04 中 `/etc/resolv.conf` 是指向 `/run/systemd/resolve/stub-resolv.conf` 的悬空软链接，导致 `quay.io` 等域名解析失败（`dial tcp: lookup quay.io on [::1]:53: connection refused`）。  
   处理：在虚拟机内替换该软链接并写入公共 DNS；随后把 DNS 固化到 Colima 配置中：

   ```bash
   colima ssh -- sudo sh -c 'rm -f /etc/resolv.conf && printf "nameserver 223.5.5.5\nnameserver 8.8.8.8\n" > /etc/resolv.conf'
   ```

2. **Colima 启动卡在 Ubuntu cloud-init**  
   `esm-cache.service` 长时间处于 starting，`cloud-final.service` 等待其完成，`colima start` 无法退出。  
   处理：停止并禁用 `esm-cache.service`，等待 `apt-get update` 完成：

   ```bash
   colima ssh -- sudo systemctl stop esm-cache.service
   colima ssh -- sudo systemctl disable esm-cache.service
   ```

3. **Docker Hub 直连 TLS 握手超时**  
   `docker pull` 报 `net/http: TLS handshake timeout`。  
   处理：为 Docker 配置国内镜像加速器，并持久化到 Colima 配置。

最终修改 `~/.colima/default/colima.yaml`：

```yaml
docker:
  registry-mirrors:
    - https://docker.m.daocloud.io

network:
  dns:
    - 223.5.5.5
    - 8.8.8.8
```

然后重启 Colima 使配置生效：

```bash
colima stop
colima start
```

验证：

```bash
docker info | grep -A2 "Registry Mirrors"
# Registry Mirrors:
#  https://docker.m.daocloud.io/
```

> 备注：Colima 的 `docker.registry-mirrors` 会在启动时重写虚拟机内的 `/etc/docker/daemon.json`，因此不要只手工修改 daemon.json，否则重启后会被覆盖。

### 5.3 创建后端 `.env`

从示例文件复制：

```bash
cd /Users/smithdong/Desktop/DevFlow-AI
cp .env.example .env
```

本次对 `.env` 的实际改动：

| 变量 | 设置方式 | 说明 |
|---|---|---|
| `LLM_API_KEY` | 复用 `.claude/settings.local.json` 中的 DeepSeek Key | 经负责人确认；不写入文档 |
| `LLM_BASE_URL` | `https://api.deepseek.com` | 保持示例值 |
| `LLM_MODEL` | `deepseek-v4-pro` | 通过 `/models` 接口确认可用 |
| `TOKEN_ENCRYPTION_KEY` | 随机生成 | 使用 Python `secrets.token_urlsafe(32)` |
| `GITHUB_TOKEN` | 通过 `gh auth token` 写入 | 账号 `mindmaster1` |
| 其他变量 | 保持 `.env.example` 原值 | 数据库、Milvus、RAG、上下文预算等 |

生成加密密钥的示例：

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

> 重要：`TOKEN_ENCRYPTION_KEY` 用于加密数据库中保存的仓库访问令牌。一旦更换，已有密文将无法解密，需要重新填写仓库令牌。请与 `.env` 一起妥善保存。

`.env` 已被项目 `.gitignore` 忽略：

```gitignore
.env
.env.*
!.env.example
```

### 5.4 创建 Python 虚拟环境并安装依赖

```bash
cd /Users/smithdong/Desktop/DevFlow-AI/backend
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
uv pip install --python .venv/bin/python -r requirements-local-embedding.txt
```

说明：

- `requirements.txt` 包含 FastAPI、SQLAlchemy、pymilvus、LangChain、Ragas 等主依赖。
- `requirements-local-embedding.txt` 包含 `sentence-transformers>=5.0.0`，会间接安装 torch、transformers 等。
- 本项目虚拟环境未安装 pip，统一使用 `uv pip` 管理。

验证：

```bash
.venv/bin/python --version          # Python 3.12.13
.venv/bin/python -c "from app.main import app; print(len(app.routes))"
# 输出：104
```

### 5.5 安装前端依赖并构建

```bash
cd /Users/smithdong/Desktop/DevFlow-AI/frontend
npm install
npm run build
```

构建结果：16 个路由全部编译成功，包括 `/`、`/repos`、`/knowledge`、`/rag`、`/evals`、`/chat` 等。

> 安装时 npm 提示 `next@15.1.2` 存在安全公告（CVE-2025-66478）。本地开发不受影响；若用于生产，请升级到已修复版本。

### 5.6 启动基础设施容器

```bash
cd /Users/smithdong/Desktop/DevFlow-AI
docker compose up -d postgres etcd minio milvus
```

启动顺序由 `depends_on` 保证：etcd、MinIO 先启动，Milvus 依赖它们。

验证：

```bash
docker compose ps
# 预期 4 个容器均为 Up，postgres 为 Up (healthy)

docker exec devflow-ai-postgres pg_isready -U devflow -d devflow
# /var/run/postgresql:5432 - accepting connections

curl -s http://localhost:9000/minio/health/live -o /dev/null -w "%{http_code}\n"
# 200

curl -s http://localhost:9091/healthz
# OK
```

Milvus 启动时 `/healthz` 可能短暂返回 `Not all components are healthy, 3/8`、`4/8` 等，等待 30–90 秒即可变为 `OK`。这是组件逐个就绪的正常过程。

### 5.7 下载本地 Embedding 模型

项目默认使用：

- Provider：`qwen_local`
- 模型：`Qwen/Qwen3-Embedding-0.6B`
- 维度：`1024`
- Milvus 集合：`devflow_rag_qwen1024`

首次下载模型（约 1.19 GB）时遇到两个问题：

1. Hugging Face Xet 下载在 64 MB 处停滞；
2. 通过系统 VPN 代理下载速度被限制到约 0.3 MB/s。

最终可复现的下载命令：

```bash
cd /Users/smithdong/Desktop/DevFlow-AI/backend
NO_PROXY='*' no_proxy='*' \
HF_ENDPOINT=https://hf-mirror.com \
HF_HUB_DISABLE_XET=1 \
.venv/bin/python - <<'PY'
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")
print("dimension:", model.get_sentence_embedding_dimension())
vec = model.encode(["DevFlow AI embedding smoke test"], normalize_embeddings=True)
print("encoded:", len(vec), "x", len(vec[0]))
PY
```

预期输出：

```text
dimension: 1024
encoded: 1 x 1024
```

模型缓存位置：

```text
~/.cache/huggingface/hub/models--Qwen--Qwen3-Embedding-0.6B
```

缓存约 1.1 GB。下载过程中产生的两个 `.incomplete` 临时文件已清理。

> 注意：下载时绕过代理（`NO_PROXY='*'`）是针对本机 VPN 代理限速的临时方案；如果换网络环境，可先直接尝试默认命令。

### 5.8 初始化演示数据

```bash
cd /Users/smithdong/Desktop/DevFlow-AI/backend
PYTHONPATH=. .venv/bin/python ../scripts/seed_demo_data.py
```

注意必须设置 `PYTHONPATH=.`，否则脚本从 `scripts/` 目录执行时找不到 `app` 包，会报：

```text
ModuleNotFoundError: No module named 'app'
```

执行结果：

```text
Seeded demo data for repo course-demo/devflow-sample-api
(0230f44f-3bdf-4c7a-85ca-b8a530c8ac77)
```

写入内容：

- 3 个 Issue
- 1 个 Pull Request 及 2 个文件、2 条 Review 评论
- 2 个 Workflow Run（含失败日志）
- 5 条 RAG 文档（issue ×3、pull_request ×1、workflow_run ×1）

> 该演示仓库是虚构的，自动同步会请求 `course-demo/devflow-sample-api` 并得到 HTTP 404，属于预期行为。

### 5.9 启动后端

```bash
cd /Users/smithdong/Desktop/DevFlow-AI/backend
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

启动过程会：

1. `Base.metadata.create_all()` 自动建表；
2. 为旧数据库补充缺失字段（兼容升级逻辑）；
3. 清理历史代码向量；
4. 启动周期同步协程（`AUTO_SYNC_ENABLED=true`，默认 300 秒）；
5. 初始化 Milvus 状态。

验证：

```bash
curl -s http://localhost:8000/health
# {"status":"ok","app":"DevFlow AI"}

curl -s http://localhost:8000/api/repos
# [{"id":"0230f44f-...","full_name":"course-demo/devflow-sample-api", ...}]
```

### 5.10 启动前端

```bash
cd /Users/smithdong/Desktop/DevFlow-AI/frontend
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev
```

启动输出：

```text
▲ Next.js 15.1.2
- Local: http://localhost:3000
✓ Ready in 7.2s
```

如不设置 `NEXT_PUBLIC_API_BASE_URL`，`next.config.js` 会回退到 `http://localhost:8000`。

### 5.11 GitHub 登录与令牌配置

使用 GitHub CLI 设备码登录：

```bash
gh auth login --hostname github.com --git-protocol https --web
```

终端会输出一次性验证码并打开/提示打开：

```text
https://github.com/login/device
```

本次登录账号：

- 用户名：`mindmaster1`
- Token scopes：`gist`、`read:org`、`repo`
- 凭据保存位置：系统 keyring

将令牌写入 `.env`（不要直接打印到终端日志）：

```bash
cd /Users/smithdong/Desktop/DevFlow-AI
export GH_TOKEN_VALUE=$(gh auth token)
python3 - <<'PY'
import os, pathlib
token = os.environ["GH_TOKEN_VALUE"]
p = pathlib.Path(".env")
lines = p.read_text().splitlines()
p.write_text("\n".join(
    "GITHUB_TOKEN=" + token if line.startswith("GITHUB_TOKEN=") else line
    for line in lines
) + "\n")
PY
```

配置 Git 凭据助手：

```bash
gh auth setup-git
```

重启后端使新的 `GITHUB_TOKEN` 生效（Pydantic Settings 在导入时读取 `.env`）：

```bash
pkill -f "uvicorn app.main:app"
cd backend
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

验证 GitHub 客户端：

```bash
cd backend
.venv/bin/python - <<'PY'
import asyncio
from app.services.github.client import GitHubClient

async def main():
    repo = await GitHubClient().get_repo("octocat", "Hello-World")
    print("github api ok:", repo["full_name"])

asyncio.run(main())
PY
```

预期输出：

```text
github api ok: octocat/Hello-World
```

> 首次设备码曾因未在有效期内完成授权而过期；重新执行 `gh auth login` 生成新码后成功。设备码通常 15 分钟内有效。

### 5.12 2026-10-23 服务重启复核

次日检查发现 Colima 未运行，后端、前端进程也已停止（通常是机器重启或上个终端会话结束导致）。按以下顺序恢复：

```bash
colima start
cd /Users/smithdong/Desktop/DevFlow-AI
docker compose up -d postgres etcd minio milvus

# 等待 Milvus 完全就绪
until [ "$(curl -s http://localhost:9091/healthz)" = "OK" ]; do sleep 2; done

# 后端
cd backend
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 另开终端启动前端
cd frontend
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev
```

复核结果：

- 4 个容器全部 Up，PostgreSQL healthy
- 后端 `/health` 返回 200
- 前端 `http://localhost:3000` 返回 200
- 演示仓库仍存在
- RAG 状态 `ready`，文档数仍为 5
- 说明 Docker 命名卷和 Milvus 数据在重启后保持完好

---

## 6. 部署操作时间线

| 时间（2026-10-22，约） | 操作 | 结果 |
|---|---|---|
| 16:44–17:05 | 阅读 README、`.env.example`、`docker-compose.yml`、后端配置与依赖 | 确认技术栈、所需服务与端口 |
| 17:05 | 检查本机工具链 | 缺 Docker/gh；系统 Python 3.9 过旧；Node 26、uv、brew 可用 |
| 17:08–17:12 | `brew install colima docker docker-compose gh` | 安装成功 |
| 17:10 | 从 `.env.example` 生成 `.env` | 写入 DeepSeek Key、随机加密密钥 |
| 17:10–17:12 | 创建 `backend/.venv`，安装主依赖与本地 Embedding 依赖 | 成功 |
| 17:10–17:12 | `npm install` | 成功 |
| 17:11–17:16 | Colima 首次启动；排查 VM DNS、cloud-init、Docker Hub TLS 超时 | 配置 DNS 与 daocloud 镜像加速 |
| 17:13–17:23 | `docker compose up` 拉取镜像；多次因网络中断重试 | 4 个容器启动 |
| 17:15–17:26 | Qwen 模型下载；Xet/代理限速排障；改用 hf-mirror 直连 | 模型下载完成，编码测试通过 |
| 17:23 | 基础设施健康检查 | Postgres/MinIO/etcd/Milvus 正常 |
| 17:24 | 启动后端 uvicorn | `/health` 200 |
| 17:25 | 启动前端 Next.js | 首页 200，各页面 200 |
| 17:29 | 执行 `seed_demo_data.py` | 演示仓库与 5 条 RAG 文档写入 |
| 17:30 | 运行 65 个离线 Workflow 测试 | 全部通过（31.95s） |
| 17:31 | 验证 RAG 混合检索 | 向量 + BM25 双路召回成功 |
| 17:31 | 验证 ChatAgent 非流式与 SSE 流式 | DeepSeek 返回正常，工具轨迹正常 |
| 17:33–17:40 | GitHub 设备码登录、写令牌、重启后端、GitHub 客户端验证 | 账号 `mindmaster1` 登录成功 |
| 2026-10-23 08:55 | 发现服务停止，重新启动全栈 | 全部恢复，数据完好 |

---

## 7. 验证记录

### 7.1 离线测试

```bash
cd backend
.venv/bin/python -m pytest \
  app/tests/test_workflow_models.py \
  app/tests/test_workflow_orchestrator.py \
  app/tests/test_workflow_policy.py -q
```

结果：

```text
65 passed in 31.95s
```

### 7.2 后端健康检查

```bash
curl -s http://localhost:8000/health
# {"status":"ok","app":"DevFlow AI"}
```

### 7.3 RAG 状态

```bash
REPO=0230f44f-3bdf-4c7a-85ca-b8a530c8ac77
curl -s "http://localhost:8000/api/rag/$REPO/status"
```

关键字段：

```json
{
  "document_count": 5,
  "source_types": {"issue": 3, "pull_request": 1, "workflow_run": 1},
  "vector_store": {
    "backend": "milvus",
    "status": "ready",
    "collection": "devflow_rag_qwen1024"
  },
  "generation": {"llm_configured": true, "model": "deepseek-v4-pro"}
}
```

### 7.4 RAG 混合检索

```bash
curl -s -X POST "http://localhost:8000/api/rag/$REPO/search" \
  -H "Content-Type: application/json" \
  -d '{"question":"login token 500 error","top_k":3}'
```

结果：命中 Issue `Login API returns 500 when token expires`，`retrieval.sources` 同时包含 `vector` 与 `keyword`，说明 Milvus 向量召回和 BM25 关键词召回都工作正常，融合分数 1.0。

### 7.5 ChatAgent（非流式）

```bash
curl -s -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"repo_id":"'$REPO'","message":"用一句话总结当前仓库最紧急的 Issue。"}'
```

结果：

- `route`: `direct_answer`
- 正确识别最紧急 Issue：`Login API returns 500 when token expires`
- `model_usage` 显示 `deepseek-v4-pro`，provider 返回真实 token 用量
- `completion.status`: `completed`

### 7.6 ChatAgent（SSE 流式）

```bash
curl -N -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"repo_id":"'$REPO'","message":"只回复 OK，不要调用任何工具。"}'
```

结果：

```text
event: delta
data: {"content": "OK"}

event: final
data: {... "route": "direct_answer", "tool_calls": [], ...}
```

### 7.7 DeepSeek API 验证

- `GET https://api.deepseek.com/models` 确认 `deepseek-v4-pro` 可用
- `POST /chat/completions` 普通文本调用成功
- `response_format={"type":"json_object"}` 返回合法 JSON：`{"ok":true}`

> `deepseek-v4-pro` 会返回 `reasoning_content`（思考内容）。项目代码只读取 `content`，不会把思考内容当作回答展示。

### 7.8 GitHub API 验证

通过项目自身的 `GitHubClient` 读取公共仓库 `octocat/Hello-World` 成功，说明 `.env` 中的 `GITHUB_TOKEN` 已被正确加载。

---

## 8. 配置变更清单

本次部署**没有修改任何应用源码**，只修改了本地配置与环境文件：

| 文件/位置 | 变更 | 是否纳入版本控制 |
|---|---|---|
| `项目根/.env` | 新建；写入 DeepSeek Key、GitHub Token、随机加密密钥等 | 否（`.gitignore` 已忽略） |
| `项目根/.gitignore` | 增加 `.claude/settings.local.json`，避免本地密钥被提交 | 是 |
| `~/.colima/default/colima.yaml` | 增加 Docker registry mirror 与 VM DNS | 否（用户级配置） |
| `~/.docker/cli-plugins/docker-compose` | 软链接到 Homebrew 的 docker-compose | 否（用户级配置） |
| `~/.cache/huggingface/...` | Qwen3-Embedding-0.6B 模型缓存 | 否（用户级缓存） |
| `backend/.venv` | Python 3.12 虚拟环境与依赖 | 否（已忽略） |
| `frontend/node_modules` | 前端依赖 | 否（已忽略） |

### `.gitignore` 新增内容

```gitignore
# Claude Code local settings (may contain local secrets)
.claude/settings.local.json
```

### `.env` 中的敏感变量（文档不记录值）

```dotenv
LLM_API_KEY=<DeepSeek API Key>
GITHUB_TOKEN=<GitHub Token>
TOKEN_ENCRYPTION_KEY=<随机生成的加密密钥>
```

---

## 9. 日常运维命令

### 9.1 查看状态

```bash
colima status
cd /Users/smithdong/Desktop/DevFlow-AI
docker compose ps
curl -s http://localhost:8000/health
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:3000/
curl -s http://localhost:9091/healthz
```

### 9.2 启动全部服务

```bash
colima start
cd /Users/smithdong/Desktop/DevFlow-AI
docker compose up -d postgres etcd minio milvus

cd backend
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 新终端
cd /Users/smithdong/Desktop/DevFlow-AI/frontend
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev
```

### 9.3 停止全部服务

```bash
# 若使用 screen 常驻方式
screen -S devflow-backend -X quit
screen -S devflow-frontend -X quit

# 若是普通终端方式
pkill -f "uvicorn app.main:app"
pkill -f "next dev"

cd /Users/smithdong/Desktop/DevFlow-AI
docker compose down
colima stop
```

> `docker compose down` 保留命名卷；如需连数据一起删除，使用 `docker compose down -v`（会丢失 Postgres/etcd/MinIO 数据，谨慎）。

### 9.4 查看日志

```bash
# 容器
docker logs -f devflow-ai-milvus
docker logs -f devflow-ai-postgres
docker logs -f devflow-ai-minio
docker logs -f devflow-ai-etcd

# 后端/前端在启动它们的终端中查看
```

### 9.5 修改 `.env` 后

必须重启后端：

```bash
pkill -f "uvicorn app.main:app"
cd backend
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 9.6 更新 GitHub 令牌

```bash
gh auth login --hostname github.com --git-protocol https --web
cd /Users/smithdong/Desktop/DevFlow-AI
export GH_TOKEN_VALUE=$(gh auth token)
python3 - <<'PY'
import os, pathlib
token = os.environ["GH_TOKEN_VALUE"]
p = pathlib.Path(".env")
lines = p.read_text().splitlines()
p.write_text("\n".join(
    "GITHUB_TOKEN=" + token if line.startswith("GITHUB_TOKEN=") else line
    for line in lines
) + "\n")
PY
```

然后重启后端。

### 9.7 使用 screen 常驻运行（当前采用）

为避免后端/前端随启动它的终端或 Claude 会话一起退出，本次使用 macOS 自带的 `screen` 把它们放入独立会话：

```bash
mkdir -p /Users/smithdong/Desktop/DevFlow-AI/.data/logs

screen -dmS devflow-backend /bin/zsh -lc '
  cd /Users/smithdong/Desktop/DevFlow-AI/backend &&
  exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 \
    >> /Users/smithdong/Desktop/DevFlow-AI/.data/logs/backend.log 2>&1'

screen -dmS devflow-frontend /bin/zsh -lc '
  cd /Users/smithdong/Desktop/DevFlow-AI/frontend &&
  NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 exec npm run dev \
    >> /Users/smithdong/Desktop/DevFlow-AI/.data/logs/frontend.log 2>&1'
```

查看与操作：

```bash
screen -ls                          # 查看会话
screen -r devflow-backend           # 进入后端会话（Ctrl+A 然后 D 脱离）
screen -r devflow-frontend          # 进入前端会话
screen -S devflow-backend -X quit   # 停止后端
screen -S devflow-frontend -X quit  # 停止前端
```

日志：

```text
.data/logs/backend.log
.data/logs/frontend.log
```

> screen 会话在终端关闭、Claude 会话结束后仍然保留；但**机器重启后不会自动恢复**，需要重新执行上述命令（Colima 和容器也需要重新启动）。如需开机自启，可改用 macOS LaunchAgent。

---

## 10. 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `colima is not running` | VM 未启动，或机器重启后未恢复 | `colima start` |
| `Cannot connect to the Docker daemon` | Docker context 不在 colima，或 VM 未启动 | `colima start`；`docker context use colima` |
| `dial tcp: lookup quay.io ... connection refused` | VM 内 DNS 不可用 | 在 `~/.colima/default/colima.yaml` 的 `network.dns` 写入 `223.5.5.5`、`8.8.8.8`，重启 Colima |
| `net/http: TLS handshake timeout` | Docker Hub 直连不稳定 | 配置 `docker.registry-mirrors: https://docker.m.daocloud.io`，重启 Colima |
| Milvus `/healthz` 返回 `3/8`、`4/8` | 组件尚在启动 | 等待 30–90 秒，直到返回 `OK` |
| 后端启动失败，连接数据库被拒绝 | Postgres 未就绪/端口占用 | `docker exec devflow-ai-postgres pg_isready...`；`lsof -nP -iTCP:5432 -sTCP:LISTEN` |
| `ModuleNotFoundError: No module named 'app'` | 从 `scripts/` 直接执行脚本 | `cd backend && PYTHONPATH=. .venv/bin/python ../scripts/seed_demo_data.py` |
| Hugging Face 模型下载停滞 | Xet 或系统代理限速 | `NO_PROXY='*' HF_ENDPOINT=https://hf-mirror.com HF_HUB_DISABLE_XET=1` |
| RAG 状态显示 `degraded` | Milvus 未启动或不可达 | 检查 `docker compose ps` 与 `http://localhost:9091/healthz` |
| 演示仓库同步显示 404 | `course-demo/devflow-sample-api` 是虚构仓库 | 预期行为；接入真实仓库后自动恢复 |
| 修改 `.env` 后配置不生效 | Pydantic Settings 在进程导入时读取 | 重启后端 |
| 前端请求 API 失败 | `NEXT_PUBLIC_API_BASE_URL` 未设置或后端未启动 | 设置 `http://localhost:8000` 并重启 `npm run dev` |
| 端口被占用 | 旧进程未退出 | `lsof -nP -iTCP:8000 -sTCP:LISTEN`，再终止对应 PID |

---

## 11. 安全注意事项

1. **`.env` 含真实密钥**，已被 `.gitignore` 忽略。不要提交、打包或发送给他人。
2. **`.claude/settings.local.json` 也含 DeepSeek Key**，本次已加入 `.gitignore`，避免未来初始化 Git 仓库时误提交。
3. **`TOKEN_ENCRYPTION_KEY` 必须保持稳定**。更换会导致数据库中已加密的仓库令牌无法解密。
4. 本地 Postgres 与 MinIO 使用示例口令 `devflow` / `minioadmin`，仅适合受控本地环境；对外部署前必须更换。
5. `pgsty/silo` 启动日志会提示默认凭据 `minioadmin:minioadmin`，生产环境应设置 `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`。
6. DeepSeek Key 曾保存在 `.claude/settings.local.json` 中；如该文件曾被分享或提交，应到 DeepSeek 控制台轮换密钥。
7. GitHub Token 为 `gho_` 开头的 OAuth 令牌，保存在系统 keyring 和 `.env` 中；如泄露，执行 `gh auth logout` 并重新登录，同时更新 `.env`。
8. 本项目会连接真实 GitHub 仓库并克隆代码；仅接入有权限的仓库，避免把敏感代码送入第三方模型。

---

## 12. 已知限制与后续建议

1. **Next.js 15.1.2 安全公告**  
   npm 安装时提示 CVE-2025-66478。建议在正式部署前升级到已修复版本，并重新执行 `npm install && npm run build`。

2. **Milvus standalone 资源占用**  
   Milvus 镜像 2.19 GB，启动需要 30–90 秒，内存占用较高。Colima 分配了 4 CPU / 8 GB 内存；如需同时运行其他服务，建议提高内存。

3. **Colima 不会开机自启**  
   机器重启后需要手动执行 `colima start` 和 `docker compose up -d`。如需开机自启，可将上述命令写入 `launchd` LaunchAgent。

4. **后台进程生命周期**  
   后端和前端最初作为 Claude Code 后台任务运行，会话结束时会一起停止。现已改用 `screen` 独立会话（`devflow-backend` / `devflow-frontend`），不会随终端或 Claude 会话退出；但机器重启后需要重新执行启动命令。长期运行建议进一步使用 `launchd` 托管并配置日志轮转。

5. **演示仓库自动同步 404**  
   `AUTO_SYNC_ENABLED=true` 每 300 秒同步一次；虚构演示仓库会持续返回 404。接入真实仓库后正常。如只想保留演示数据，可在 `.env` 设置 `AUTO_SYNC_ENABLED=false` 并重启后端。

6. **本地 Embedding 模型**  
   首次部署需下载约 1.19 GB 模型；模型缓存位于 `~/.cache/huggingface`。更换模型或维度必须同步更换 Milvus 集合并重建索引，不能直接复用旧集合。

7. **RAG 重排**  
   当前默认使用本地启发式重排；`qwen3-rerank` 需要配置 `DASHSCOPE_API_KEY` / `RERANK_BASE_URL` 后才可用。

8. **GitHub 令牌作用域**  
   当前令牌包含 `repo`、`read:org`、`gist`。如需访问组织仓库或 Actions 日志，请确认令牌权限；私有仓库需 `repo` 权限。

---

## 附录 A：关键文件与目录

| 路径 | 说明 |
|---|---|
| `项目根/.env` | 本地环境变量（含密钥，已忽略） |
| `项目根/.env.example` | 环境变量模板 |
| `项目根/docker-compose.yml` | PostgreSQL / etcd / MinIO / Milvus 编排 |
| `backend/requirements.txt` | 后端主依赖 |
| `backend/requirements-local-embedding.txt` | 本地 Embedding 依赖 |
| `backend/.venv/` | Python 3.12 虚拟环境 |
| `frontend/node_modules/` | 前端依赖 |
| `scripts/seed_demo_data.py` | 演示数据初始化脚本 |
| `~/.colima/default/colima.yaml` | Colima VM 配置（CPU/内存/DNS/镜像加速） |
| `~/.cache/huggingface/hub/models--Qwen--Qwen3-Embedding-0.6B` | Qwen 模型缓存 |
| `/var/lib/docker`（VM 内） | Docker 数据（命名卷） |

## 附录 B：从零复现速查

```bash
# 1. 系统工具
brew install colima docker docker-compose gh
mkdir -p ~/.docker/cli-plugins
ln -sf /opt/homebrew/bin/docker-compose ~/.docker/cli-plugins/docker-compose

# 2. Colima（首次）
colima start --cpu 4 --memory 8 --disk 60 --vm-type vz
# 如遇 DNS/镜像问题，编辑 ~/.colima/default/colima.yaml 后 colima stop && colima start

# 3. 环境变量
cd /Users/smithdong/Desktop/DevFlow-AI
cp .env.example .env
# 填写 LLM_API_KEY、TOKEN_ENCRYPTION_KEY、GITHUB_TOKEN

# 4. 后端依赖
cd backend
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
uv pip install --python .venv/bin/python -r requirements-local-embedding.txt

# 5. 前端依赖
cd ../frontend
npm install

# 6. 基础设施
cd ..
docker compose up -d postgres etcd minio milvus
until [ "$(curl -s http://localhost:9091/healthz)" = "OK" ]; do sleep 2; done

# 7. 模型（首次）
cd backend
NO_PROXY='*' no_proxy='*' HF_ENDPOINT=https://hf-mirror.com HF_HUB_DISABLE_XET=1 \
.venv/bin/python - <<'PY'
from sentence_transformers import SentenceTransformer
m = SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")
print(m.get_sentence_embedding_dimension())
PY

# 8. 演示数据
PYTHONPATH=. .venv/bin/python ../scripts/seed_demo_data.py

# 9. 启动
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
# 新终端：
cd ../frontend && NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 npm run dev
```

---

## 附录 C：本次部署未执行的操作

为避免误解，以下内容**没有**在本次部署中执行：

- 没有修改任何后端或前端源码。
- 没有升级或降级 `requirements.txt` / `package.json` 中的版本。
- 没有初始化 Git 仓库，也没有提交任何代码。
- 没有启动可选 Redis profile。
- 没有配置 Milvus 认证（`MILVUS_TOKEN` 为空，使用本地无认证模式）。
- 没有配置 `DASHSCOPE_API_KEY` / `RERANK_BASE_URL`，因此使用本地启发式重排。
- 没有运行 `test_workflow_live_models.py`（会产生真实模型费用，需要显式设置 `DEVFLOW_RUN_LIVE_LLM=1`）。
- 没有运行完整 RAGAS 评测（需要前端触发或调用 `/api/evals/rag/run`，会产生 Judge 模型费用）。
