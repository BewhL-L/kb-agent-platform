"""
pytest 全局配置与 fixtures
- 在导入应用前，用内存假实现替换 openai / chromadb，测试不依赖真实 API
- 提供 TestClient、注册并登录的用户、认证头
"""
import json
import math
import sys
import types
import zlib

# ============================================================
# 1. 假 Embedding（词袋向量，让相似文本聚簇）
# ============================================================

EMBED_DIM = 20


def fake_embed_text(text: str):
    # 用 crc32 而不是内置 hash：内置 hash 对 str 有进程级盐（PYTHONHASHSEED），
    # 同一段文本在不同进程会落到不同维度，测试结果不可复现。
    v = [0.0] * EMBED_DIM
    for token in text.replace("，", " ").replace("。", " ").split():
        v[zlib.crc32(token.encode("utf-8")) % EMBED_DIM] += 1.0
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


# ============================================================
# 2. 假 Chroma（内存实现，支持 add/query/delete/count）
# ============================================================

class _FakeCollection:
    def __init__(self, name):
        self.name = name
        self.ids, self.docs, self.embs, self.metas = [], [], [], []

    def count(self):
        return len(self.ids)

    def add(self, ids, documents, embeddings, metadatas):
        self.ids += ids
        self.docs += documents
        self.embs += embeddings
        self.metas += metadatas

    def query(self, query_embeddings, n_results):
        q = query_embeddings[0]
        scored = sorted(
            ((1 - _cosine(q, e), i) for i, e in enumerate(self.embs)),
        )
        top = scored[:n_results]
        return {
            "documents": [[self.docs[i] for _, i in top]],
            "metadatas": [[self.metas[i] for _, i in top]],
            "distances": [[d for d, _ in top]],
        }

    def delete(self, where):
        did = where.get("document_id")
        keep = [i for i, m in enumerate(self.metas) if m.get("document_id") != did]
        self.ids = [self.ids[i] for i in keep]
        self.docs = [self.docs[i] for i in keep]
        self.embs = [self.embs[i] for i in keep]
        self.metas = [self.metas[i] for i in keep]


class _FakeChromaClient:
    def __init__(self, *a, **k):
        self._cols = {}

    def get_or_create_collection(self, name, metadata=None):
        if name not in self._cols:
            self._cols[name] = _FakeCollection(name)
        return self._cols[name]

    def delete_collection(self, name):
        self._cols.pop(name, None)


chroma_stub = types.ModuleType("chromadb")
chroma_stub.PersistentClient = _FakeChromaClient
sys.modules["chromadb"] = chroma_stub


# ============================================================
# 3. 假 OpenAI（同步 Embedding + 异步 Chat）
# ============================================================

class _Message:
    def __init__(self, content, tool_calls=None, reasoning_content=None):
        self.content = content
        self.tool_calls = tool_calls
        if reasoning_content is not None:
            self.reasoning_content = reasoning_content


class _Choice:
    def __init__(self, message):
        self.message = message


class _ChatResponse:
    def __init__(self, message):
        self.choices = [_Choice(message)]


class _Delta:
    def __init__(self, content):
        self.content = content


class _StreamChoice:
    def __init__(self, delta):
        self.delta = delta


class _StreamChunk:
    def __init__(self, content):
        self.choices = [_StreamChoice(_Delta(content))]


class _EmbeddingItem:
    def __init__(self, embedding, index):
        self.embedding = embedding
        self.index = index


class _EmbeddingResponse:
    def __init__(self, data):
        self.data = data


class _Completions:
    async def create(self, **kwargs):
        if kwargs.get("stream"):
            async def _gen():
                for ch in "这是测试答案":
                    yield _StreamChunk(ch)
            return _gen()
        # 推理模型：返回独立的思考链字段
        model = str(kwargs.get("model", ""))
        if "r1" in model or "thinking" in model or "reason" in model:
            return _ChatResponse(_Message(
                "这是推理后的最终答案",
                reasoning_content="首先分析问题，然后检索资料，最后得出结论。",
            ))
        # 带工具的请求：默认不调用工具，直接给答案
        return _ChatResponse(_Message("这是测试答案"))


class _Chat:
    def __init__(self):
        self.completions = _Completions()


class _AsyncClient:
    def __init__(self, *a, **k):
        self.chat = _Chat()


class _Embeddings:
    def create(self, model, input):
        texts = input if isinstance(input, list) else [input]
        data = [_EmbeddingItem(fake_embed_text(t), i) for i, t in enumerate(texts)]
        return _EmbeddingResponse(data)


class _SyncCompletions:
    """同步 Chat stub：按 prompt 类型返回可解析结果（Rerank/改写/Judge/压缩）"""

    def create(self, **kwargs):
        messages = kwargs.get("messages", [])
        joined = " ".join(str(m.get("content", "")) for m in messages)
        if "重新排序" in joined:  # Rerank
            return _ChatResponse(_Message('{"order":[0,1,2,3,4]}'))
        if "压缩以下对话" in joined:  # 历史压缩
            return _ChatResponse(_Message("用户此前咨询了售后政策相关问题。"))
        if "不同表述" in joined:  # Multi-query
            return _ChatResponse(_Message('["改写问题一","改写问题二"]'))
        if "评审" in joined:  # LLM Judge
            return _ChatResponse(_Message('{"score":0.9}'))
        if "抽取" in joined:  # GraphRAG / Wiki 实体抽取
            return _ChatResponse(_Message(json.dumps({
                "entities": [
                    {"name": "RAG", "entity_type": "concept",
                     "summary": "检索增强生成技术",
                     "relations": ["向量检索", "知识图谱"]},
                    {"name": "向量检索", "entity_type": "process",
                     "summary": "用向量相似度找资料",
                     "relations": ["RAG"]},
                    {"name": "知识图谱", "entity_type": "concept",
                     "summary": "用实体和关系组织知识",
                     "relations": ["RAG"]},
                ]
            }, ensure_ascii=False)))
        if "社区" in joined:  # GraphRAG 社区摘要
            return _ChatResponse(_Message(json.dumps(
                {"title": "RAG 与图谱技术",
                 "summary": "该社区包含检索增强生成、向量检索和知识图谱相关内容"},
                ensure_ascii=False)))
        return _ChatResponse(_Message("早期对话摘要内容"))


class _SyncChat:
    def __init__(self):
        self.completions = _SyncCompletions()


class _SyncClient:
    def __init__(self, *a, **k):
        self.embeddings = _Embeddings()
        self.chat = _SyncChat()


openai_stub = types.ModuleType("openai")
openai_stub.AsyncOpenAI = _AsyncClient
openai_stub.OpenAI = _SyncClient

# openai 异常类（llm_service 导入用）
class _APIError(Exception):
    pass


class _APITimeoutError(_APIError):
    pass


class _APIConnectionError(_APIError):
    pass


class _RateLimitError(_APIError):
    pass


class _InternalServerError(_APIError):
    pass


openai_stub.APIError = _APIError
openai_stub.APITimeoutError = _APITimeoutError
openai_stub.APIConnectionError = _APIConnectionError
openai_stub.RateLimitError = _RateLimitError
openai_stub.InternalServerError = _InternalServerError
sys.modules["openai"] = openai_stub


# ============================================================
# 3.5 测试隔离：所有持久化路径重定向到临时目录，测试不污染工程
# ============================================================
import os
import tempfile

_TMP = tempfile.mkdtemp(prefix="kb_test_")
os.environ["BM25_INDEX_DIR"] = os.path.join(_TMP, "bm25")
os.environ["EVAL_REPORT_DIR"] = os.path.join(_TMP, "eval")
os.environ["LONG_MEMORY_PATH"] = os.path.join(_TMP, "long_memory.json")
os.environ["EMBEDDING_CACHE_PATH"] = os.path.join(_TMP, "embed_cache.json")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(_TMP, "test.db").replace("\\", "/")
os.environ["UPLOAD_DIR"] = os.path.join(_TMP, "uploads")
# 测试不允许依赖外部服务：本机 .env 可能指向 Qdrant / Celery（Docker 部署用），这里强制改回假实现
os.environ["VECTOR_PROVIDER"] = "chroma"
os.environ["ASYNC_MODE"] = "thread"
# 测试环境禁用限流，避免密集请求触发 429
os.environ["RATE_LIMIT_ENABLED"] = "false"

# 预创建会在模块加载阶段被检查的目录（如 StaticFiles 挂载 /uploads）
for _var in ("BM25_INDEX_DIR", "EVAL_REPORT_DIR", "UPLOAD_DIR"):
    os.makedirs(os.environ[_var], exist_ok=True)


# ============================================================
# 4. fixtures
# ============================================================
import pytest
from fastapi.testclient import TestClient

from app.database import Base, engine
from app.main import app


@pytest.fixture(scope="function")
def client():
    # 每个测试用一套干净的内存表
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    # 清空内存向量库，隔离用例
    from app.services.vector_store import vector_store
    vector_store.client._cols.clear()

    # 清空 BM25 索引：它是按 kb_id 落盘的，而每个测试的知识库 id 都从 1 重新开始，
    # 不清理会让上一个用例的切片混进这次检索（表现为检索质量莫名下降）。
    import glob

    from app.retrieval import bm25_retriever
    for path in glob.glob(os.path.join(os.environ["BM25_INDEX_DIR"], "*.json")):
        try:
            os.remove(path)
        except OSError:
            pass
    bm25_retriever._CACHE.clear()

    # 检索缓存也是全局的，且 key 只带 kb_id（每轮测试都从 1 开始）——不清会串味
    from app.services.cache import cache as app_cache
    app_cache.clear()

    with TestClient(app) as c:
        yield c


@pytest.fixture
def registered_user(client):
    """注册并登录，返回 (user_info, auth_header)"""
    payload = {"username": "testuser", "email": "test@example.com", "password": "Test1234"}
    client.post("/api/auth/register", json=payload)
    resp = client.post("/api/auth/login", json=payload)
    token = resp.json()["access_token"]
    return payload, {"Authorization": f"Bearer {token}"}
