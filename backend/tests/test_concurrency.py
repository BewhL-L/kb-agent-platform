"""
并发模型测试：检索不能阻塞事件循环
==================================
用"心跳"测法：起一个每 10ms tick 的协程，同时调用检索。
如果检索是同步阻塞的，心跳会出现 200ms 的空档；走线程池后应保持在几十毫秒内。
"""
import asyncio
import time

from app.config import settings
from app.services.rag_service import RAGService
from app.services.vector_store import vector_store


def test_aretrieve_does_not_block_event_loop(monkeypatch):
    def slow_query(*args, **kwargs):
        # 模拟同步 HTTP（embedding）或同步 LLM 精排的耗时
        time.sleep(0.2)
        return []

    monkeypatch.setattr(vector_store, "query", slow_query)
    monkeypatch.setattr(settings, "RETRIEVAL_MODE", "vector")
    monkeypatch.setattr(settings, "SELF_RAG_ENABLED", False)

    service = RAGService(vector_store=vector_store)

    async def scenario() -> float:
        gaps = []
        stop = asyncio.Event()

        async def heartbeat():
            last = time.perf_counter()
            while not stop.is_set():
                await asyncio.sleep(0.01)
                now = time.perf_counter()
                gaps.append(now - last)
                last = now

        task = asyncio.create_task(heartbeat())
        await asyncio.sleep(0.02)
        await service.aretrieve(1, "测试问题")
        stop.set()
        await task
        return max(gaps) if gaps else 0.0

    max_gap = asyncio.run(scenario())

    assert max_gap < 0.08, f"事件循环被阻塞 {max_gap * 1000:.0f}ms，检索没有走线程池"
