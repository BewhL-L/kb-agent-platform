# 企业级智能知识库 + AI Agent 平台

[![CI](https://github.com/BewhL-L/kb-agent-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/BewhL-L/kb-agent-platform/actions/workflows/ci.yml)

面向企业内部知识问答的全栈应用：文档上传后自动完成解析、切片、向量化与知识编译，支持混合检索、Agent 自主工具调用、图谱增强与 LLM Wiki 页面，并自带评测体系。

不依赖任何托管 RAG 平台，检索链路、Agent 编排、Wiki 编译、评测指标均为自实现。

---

## 能力矩阵

| 模块 | 实现 | 关键接口 |
|---|---|---|
| 知识库管理 | 多知识库、RBAC 协作（owner / editor / viewer） | `POST /api/kb`、`/api/kb/{id}/members` |
| 文档处理 | PDF / DOCX / TXT / MD / 图片；父块 1000 字、子块 250 字；异步线程或 Celery | `POST /api/kb/{id}/upload` |
| 检索增强 | 向量 + BM25 双路召回、RRF 融合、LLM 精排、多查询改写、Self-RAG（可开关） | 内部 `HybridRetriever` |
| 问答 | 普通 RAG / Agentic RAG / 推理模型（思考链）/ 流式 SSE / 跨库问答 | `POST /api/chat`、`/api/chat/stream` |
| AI Agent | Function Calling 循环、工具预算、多 Agent 状态机（规划/检索/撰写/审核） | `POST /api/agent/multi-agent` |
| LLM Wiki | 实体抽取 → 页面编译 → 双链 → 冲突检测 → 版本回滚 | `GET /api/wiki/kb/{id}/pages` |
| GraphRAG | 实体/关系/社区构建，局部检索与 map-reduce 全局检索（**独立入口，未接入主问答链路**） | `POST /api/graphrag/kb/{id}/build` |
| 结构化回答 | 按模板（要点/对比表/时间线）输出严格 JSON，解析失败自动降级 | `POST /api/structured/generate` |
| 评测 | 20 条金标集：关键词命中、上下文精确率/召回率、**拒答召回/误拒率**、LLM 裁判忠实度，可选 RAGAS | `POST /api/evaluation/run` |
| 答案溯源 | 句子级 citation 覆盖率（字符二元组对齐，零成本、可复现），低置信自动标记 | `/api/chat` 返回 `grounding` |
| 性能 | 检索走线程池不阻塞事件循环；片段级缓存 + 版本号失效；外键与复合索引 | `services/retrieval_cache.py` |
| Prompt 治理 | `Prompt(name, version, template)` 注册表，调用记录写入 `prompt_version` | `app/prompts/` |
| 可观测 | 每次调用记录 token 与费用；Langfuse 追踪（可选） | `GET /api/stats/cost` |

## 架构

```
Vue 3 + TS (Element Plus / Pinia / ECharts)
        │  axios + SSE
        ▼
   Nginx  ──/api──►  FastAPI   JWT / RBAC / 限流
                       │
                       ├── 应用层   services/     RAG（检索→生成→溯源）/ Agent / Wiki / 图谱 / 结构化
                       ├── 检索层   retrieval/    缓存（kb 版本号）→ 向量 + BM25 → RRF → LLM 精排
                       ├── 编排层   orchestration/ 原生状态机 / LangGraph（可选）
                       ├── 上下文层 context_engine/ 历史压缩、token 预算、工具预算
                       ├── 模型层   LLM / Embedding / 推理 / 裁判（同步调用走线程池）
                       └── 数据层   PostgreSQL·SQLite（Alembic）/ Qdrant·Chroma / Redis / 本地文件
```

检索与生成在线程池执行，不阻塞事件循环；GraphRAG 是独立入口，未接入主链路。

## 关键设计

1. **混合检索而不是只调 embedding**。BM25 负责型号、专有名词这类精确词项，向量负责语义近似；两路用 RRF 融合，对分数量纲不敏感；最后用 LLM 精排收敛到 Top-5。纯向量在“报销标准是百分之几”这类问题上召回明显更差。
2. **父子分块**。用 250 字子块建索引保证命中精度，命中后回取 1000 字父块保证上下文完整，避免“检索准了但答不全”。
3. **Agent 与 RAG 共用同一条检索链路**。Agent 的 `search_knowledge_base` 工具直接复用 `RAGService.retrieve`，两套入口不会出现“答得出来/答不出来”的割裂。
4. **降级优先于报错**。LLM 重试耗尽、Rerank 解析失败、结构化输出非法、Celery 不可用，都有明确的降级路径；问答接口不会因为模型不听话而 500。
5. **权限分三档落在统一出口**。`require_kb_role(db, kb_id, user, min_role)` 一处定义读/写/管理边界，27 个调用点全部走它，避免各写各的 `if kb.user_id == user.id`。

## 技术栈

后端：Python 3.11、FastAPI、SQLAlchemy 2、Pydantic v2、Alembic、Chroma / Qdrant、Redis、Celery、pytest、ruff
前端：Vue 3.5、TypeScript、Vite 5、Pinia、Vue Router、Element Plus、ECharts、markdown-it、Vitest
部署：Docker Compose（postgres / redis / qdrant / backend / frontend）、Nginx（SSE 免缓冲）、GitHub Actions

## 快速开始

```bash
cp backend/.env.example backend/.env
# 至少填 LLM_API_KEY / LLM_BASE_URL / LLM_MODEL（任意 OpenAI 兼容服务）

docker compose up -d --build
# 前端 http://localhost     后端文档 http://localhost:8000/docs
```

启用 Celery 异步处理（文档量大时）：

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
# 数据库迁移已内置在 backend 启动命令里（scripts/db_bootstrap.py），无需手动执行
```

本地开发（不依赖 Docker）：

```bash
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt
# .env 中改 DATABASE_URL=sqlite:///./knowledge_base.db、VECTOR_PROVIDER=chroma
.venv/Scripts/python scripts/db_bootstrap.py   # 建表 / 升级（空库建全、老库自动 stamp）
.venv/Scripts/python -m uvicorn app.main:app --reload

cd frontend && npm install && npm run dev
```

## 测试

```bash
cd backend && ruff check app tests scripts    # lint（pyflakes 能抓 undefined name）
cd backend && pytest -q                        # 105 passed
cd backend && python scripts/check_docs.py     # 文档一致性（测试数/路径/接口）
cd frontend && npm run test                   # 5 passed（纯函数，vitest）
cd frontend && npm run build                  # 含 vue-tsc 类型检查
```

测试里有六道回归门：

| 门 | 文件 | 拦住什么 |
|---|---|---|
| 迁移可执行 | `test_migrations.py` | 改了模型没生成迁移 / 迁移脚本写坏 |
| 检索质量 | `test_eval_regression.py` | 切片、检索、精排改坏导致 Hit@3 掉线 |
| 溯源与拒答 | `test_grounding.py` | citation 覆盖率与拒答指标退化 |
| 检索缓存 | `test_retrieval_cache.py` | 缓存命不中、文档变更后不失效 |
| 并发不阻塞 | `test_concurrency.py` | 同步检索重新回到事件循环里 |
| 文档一致性 | `scripts/check_docs.py` | 测试数、路径、接口与代码不符；私有文档/密钥混入版本库 |

后端测试用假的 OpenAI / Chroma 替身，不依赖网络与外部服务；每个用例独立建表，互不污染。

工具调用也不必真跑模型：`tool_script` fixture 能让假模型按脚本发起 `tool_calls`，并记录回灌给模型的工具结果——这样就能对"Agent 是否正确调用某个工具"写断言。

## 目录结构

```
backend/
  app/routers/         # 13 组 REST 路由
  app/services/        # RAG、Agent、文档、Wiki、图谱、结构化、溯源、用量
  app/retrieval/       # 向量/BM25/RRF/精排/改写/Self-RAG
  app/wiki/            # 编译、实体抽取、双链、冲突检测、版本
  app/orchestration/   # 原生多 Agent、LangGraph 适配
  app/prompts/         # Prompt 注册表（name + version，调用记录可追溯）
  app/evaluation/      # 金标集、指标、拒答统计、LLM 裁判、RAGAS 适配
  migrations/          # Alembic 迁移（baseline 已固化 13 表 + 50 索引）
  scripts/             # 微调脚本、RBAC 迁移、索引效果实测
  tests/               # 106 个测试（含迁移/检索回归/溯源/缓存/并发五道门）
frontend/
  src/views/           # 13 个页面
  src/api/             # 类型化接口层
  src/utils/           # 结构化回答容错解析
  tests/               # vitest 单元测试
docker-compose.yml     # 开发/预发编排
docker-compose.prod.yml# 生产 overlay（Celery worker）
```

## 已知限制

- 检索已用 `run_in_threadpool` 挪出事件循环，但线程池默认 40 个，极高并发下仍会排队。
- Agent 无 checkpoint / human-in-the-loop，长任务中断后不能续跑。
- 限流是单进程内存窗口，多副本部署需换成 Redis 计数。
- BM25 索引按知识库整文件读写，适合中小规模；十万级切片应换成倒排索引服务。
- 文档原文经 `/uploads` 静态目录访问，未做签名 URL，多租户场景需要补。
- 溯源校验用字符二元组对齐，对大幅改写的句子偏保守——它是提示，不是判决。
- 检索缓存只做"片段级 + 版本号失效"，没有语义缓存；多实例必须用 Redis，否则各进程各一份。
- A2A（Agent 互操作）默认关闭，避免公网暴露内部知识库。
