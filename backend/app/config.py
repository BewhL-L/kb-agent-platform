"""应用配置模块"""
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置，从环境变量读取"""

    APP_NAME: str = "企业智能知识库助手"
    DEBUG: bool = True

    # 数据库
    DATABASE_URL: str = "sqlite:///./knowledge_base.db"
    # 启动时是否用 SQLAlchemy create_all 建表（开发/测试方便）。
    # 生产必须置 false，改用 `alembic upgrade head`——create_all 只建缺失的表，不会改已有表结构。
    AUTO_CREATE_TABLES: bool = True

    # 启动期等待数据库的最长重试次数与退避区间（秒）。
    # 默认 0.5→1→2→4→5… 累计约 2~2.5 分钟，覆盖容器 DNS 未注册、PG crash recovery、
    # 数据库刚重启等瞬时故障。容器内如需更长窗口，用 DB_CONNECT_MAX_ATTEMPTS 覆盖。
    DB_CONNECT_MAX_ATTEMPTS: int = 30
    DB_CONNECT_BASE_DELAY: float = 0.5
    DB_CONNECT_MAX_DELAY: float = 5.0

    # JWT
    SECRET_KEY: str = "your-secret-key-change-this-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080

    # LLM
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/v3"
    LLM_MODEL: str = "doubao-pro-32k"
    EMBEDDING_MODEL: str = "embedding-3"
    EMBEDDING_DIM: int = 1024

    # LLM 容错（超时 / 重试 / 降级）
    LLM_TIMEOUT: int = 60
    LLM_MAX_RETRIES: int = 3
    LLM_RETRY_BASE_DELAY: float = 1.0

    # 文件上传
    UPLOAD_DIR: str = "./uploads"
    MAX_FILE_SIZE_MB: int = 10
    ALLOWED_EXTENSIONS: str = "pdf,docx,txt,md,jpg,jpeg,png"
    # 多模态：图片上传时用 VLM 生成描述，可检索
    MULTIMODAL_ENABLED: bool = True

    # 向量数据库
    VECTOR_DB_PATH: str = "./chroma_db"
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 50
    # 父子分块：小块检索（精度高）、大块返回（上下文完整）
    PARENT_CHUNK_ENABLED: bool = True
    PARENT_CHUNK_SIZE: int = 1000
    CHILD_CHUNK_SIZE: int = 250
    TOP_K: int = 5
    # 相似度阈值：低于该分数的片段视为不相关，直接过滤（降低幻觉）
    SIMILARITY_THRESHOLD: float = 0.3

    # 检索结果缓存（只缓存检索片段，不缓存答案）
    # 失效方式：文档增删改时 bump 该库的版本号，旧 key 自然失效
    RETRIEVAL_CACHE_ENABLED: bool = True
    RETRIEVAL_CACHE_TTL: int = 600

    # Embedding 缓存（相同文本不重复调用，省钱省时）
    EMBEDDING_CACHE_ENABLED: bool = True
    EMBEDDING_CACHE_PATH: str = "./embedding_cache.json"

    # 接口限流（单机内存滑动窗口）
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PER_MINUTE: int = 60

    # 日志
    LOG_LEVEL: str = "INFO"

    # ===== 检索增强（P0）=====
    # 检索模式：vector=纯向量；hybrid=BM25+向量混合(RRF融合)
    RETRIEVAL_MODE: str = "hybrid"
    BM25_INDEX_DIR: str = "./bm25_index"
    BM25_WEIGHT: float = 0.4
    VECTOR_WEIGHT: float = 0.6
    RRF_K: int = 60
    FETCH_K: int = 20          # 融合前每路召回数量
    # Rerank 精排
    RERANK_ENABLED: bool = True
    RERANK_PROVIDER: str = "llm"   # llm=用对话模型打分；cohere=Cohere Rerank API
    RERANK_TOP_N: int = 5
    COHERE_API_KEY: str = ""
    # 查询改写
    QUERY_REWRITE_ENABLED: bool = True
    MULTI_QUERY_COUNT: int = 3
    HYDE_ENABLED: bool = False
    # Self-RAG：检索后自检，不足则重检索
    SELF_RAG_ENABLED: bool = False

    # ===== 上下文工程（P0）=====
    CONTEXT_MAX_TOKENS: int = 6000
    HISTORY_COMPRESS_ENABLED: bool = True
    HISTORY_KEEP_TURNS: int = 6
    MEMORY_ENABLED: bool = True
    LONG_MEMORY_PATH: str = "./long_memory.json"
    TOOL_BUDGET: int = 10

    # ===== 评测（P0）=====
    EVAL_DATASET_PATH: str = "./app/evaluation/data/golden_qa.json"
    EVAL_REPORT_DIR: str = "./eval_reports"
    LLM_JUDGE_ENABLED: bool = True

    # ===== 答案溯源校验（Citation / Grounding）=====
    # 给答案的每个句子算"能在检索片段里找到多少依据"，零成本、可复现
    GROUNDING_ENABLED: bool = True
    # 单句被判为"有依据"的最小字符二元组覆盖率
    GROUNDING_SENTENCE_THRESHOLD: float = 0.30
    # 整篇低于该覆盖率视为低置信（前端可提示"部分内容缺少出处"）
    GROUNDING_MIN_COVERAGE: float = 0.60

    # ===== 可观测性（P1）=====
    LANGFUSE_ENABLED: bool = False
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = "https://cloud.langfuse.com"

    # ===== Agent 编排（P1）=====
    ORCHESTRATION_BACKEND: str = "native"   # native / langgraph

    # ===== A2A 协议（Agent 互操作，对外暴露能力）=====
    # 默认关闭：作品集项目不对公网暴露内部知识库；要用时再打开并配置 Token
    A2A_ENABLED: bool = False
    # 调用方需携带 Authorization: Bearer <A2A_TOKEN>；留空表示拒绝所有调用
    A2A_TOKEN: str = ""
    A2A_PUBLIC_URL: str = "http://localhost:8000/a2a/"

    # ===== LLM Wiki 知识编译层（P1）=====
    WIKI_ENABLED: bool = True
    # 文档上传后是否自动触发编译
    WIKI_AUTO_COMPILE: bool = True
    # 单个文档最多抽取的实体数（控制 token 成本）
    WIKI_MAX_ENTITIES_PER_DOC: int = 15
    # 单页正文最大 token 数
    WIKI_PAGE_MAX_TOKENS: int = 1500
    # 查询时是否启用 Wiki 增强（全局理解型问题先查 Wiki 页）
    WIKI_RETRIEVAL_ENABLED: bool = True
    # Wiki 页命中阈值（页面标题/摘要与问题的相关度）
    WIKI_PAGE_SCORE_THRESHOLD: float = 0.35
    # 每次查询注入 Wiki 页的最大数量
    WIKI_MAX_PAGES_PER_QUERY: int = 2

    # ===== GraphRAG（知识图谱增强检索）=====
    GRAPHRAG_ENABLED: bool = True
    # 局部检索：种子实体数、邻居扩展跳数
    GRAPHRAG_TOP_ENTITIES: int = 5
    GRAPHRAG_LOCAL_HOPS: int = 1
    # 全局检索：参与 map-reduce 的社区数
    GRAPHRAG_TOP_COMMUNITIES: int = 6

    # ===== 推理模型 / 推理时计算（Reasoning）=====
    # 推理模型（带思考链，如 deepseek-r1、doubao-thinking、o 系列）
    REASONING_ENABLED: bool = True
    REASONING_MODEL: str = "deepseek-r1"
    # 是否对复杂问题启用推理（false 时全部走普通模型，省时省钱）
    REASONING_AUTO: bool = True
    # Self-Consistency：多次采样取多数一致（成本高，默认关闭）
    SELF_CONSISTENCY_ENABLED: bool = False
    SELF_CONSISTENCY_SAMPLES: int = 3
    # 简单问题的判定（问题长度低于此值且不含复杂词，直接走普通模型）
    REASONING_MIN_QUESTION_LEN: int = 15

    # ===== 生产化（P1）=====
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    # 异步任务模式：thread=本地线程（开发）；celery=Celery 队列（生产）
    ASYNC_MODE: str = "thread"

    # 向量库提供方：chroma=本地 Chroma（开发）；qdrant=Qdrant（生产）
    VECTOR_PROVIDER: str = "chroma"
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str = ""

    # ===== 成本监控（P1）=====
    COST_TRACKING_ENABLED: bool = True
    # 模型单价（每百万 token，元）：JSON 字符串，键为模型名，值为 [输入单价, 输出单价]
    MODEL_PRICE_CONFIG: str = (
        '{"doubao-pro-32k": [0.8, 2.0], "doubao-lite-32k": [0.3, 0.6],'
        ' "gpt-4o": [17.5, 70.0], "gpt-4o-mini": [1.05, 4.2],'
        ' "gpt-3.5-turbo": [2.5, 10.0], "claude-3-5-sonnet": [21.0, 105.0]}'
    )

    # CORS
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]

    @property
    def allowed_extensions_list(self) -> List[str]:
        return [ext.strip() for ext in self.ALLOWED_EXTENSIONS.split(",")]

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)


settings = Settings()
