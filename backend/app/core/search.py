"""统一检索模块 - 基于 Embedding 语义搜索

使用 embedding 模型将查询文本向量化，然后在 Milvus Lite 中进行
余弦相似度搜索，返回最相关的知识库切片。
"""
import json
from typing import List, Dict

from loguru import logger

from app.config import settings
from app.core.milvus_store import create_vector_store
from app.core.embedding_service import embedding_service


_store = None  # 缓存实例
_store_uri = None


def _get_store():
    """获取或创建向量存储实例（根据 MILVUS_URI 自动选择模式）"""
    global _store, _store_uri
    current_uri = settings.effective_milvus_uri
    if _store is None or _store_uri != current_uri:
        _store = create_vector_store(current_uri)
        _store_uri = current_uri
        logger.info(f"已初始化向量存储: mode={settings.milvus_mode}, uri={current_uri}")
    return _store


async def async_search_policy_chunks(query: str, top_k: int = 5) -> List[Dict]:
    """
    异步版本的知识库语义检索。

    流程：
    1. 调用 embedding 模型将查询文本向量化
    2. 在 Milvus Lite 中进行余弦相似度搜索
    3. 返回最相关的知识库切片
    """
    try:
        # 1. 生成查询向量
        query_vector = await embedding_service.embed_query(query)

        # 2. 向量检索
        store = _get_store()
        entities = await store.vector_search(
            query_vectors=[query_vector],
            collection_name=settings.MILVUS_COLLECTION,
            output_fields=["text", "filename", "department", "metadata"],
            limit=top_k,
        )

        if not entities:
            logger.info("Embedding 语义检索未命中任何结果")
            return []

        # 3. 格式化结果并执行阈值过滤
        hits = []
        SIMILARITY_THRESHOLD = 0.3  # Cosine similarity阈值，低于此值视为无关

        for entity in entities:
            score = entity.get("score", 0)
            if score < SIMILARITY_THRESHOLD:
                continue

            metadata = {}
            raw_meta = entity.get("metadata", "")
            if raw_meta:
                try:
                    metadata = json.loads(raw_meta) if isinstance(raw_meta, str) else raw_meta
                except (json.JSONDecodeError, TypeError):
                    pass

            hits.append({
                "content": entity.get("text", ""),
                "title": metadata.get("title", entity.get("filename", "")),
                "hierarchy": metadata.get("hierarchy", ""),
                "source": entity.get("filename", ""),
                "department": entity.get("department", ""),
                "score": score,
            })

        logger.info(f"Embedding 语义检索成功，返回 {len(hits)} 条有效结果（过滤前 {len(entities)} 条）")
        return hits

    except Exception as e:
        logger.error(f"Embedding 语义检索失败: {e}")
        return []


def search_policy_chunks(query: str, top_k: int = 5) -> List[Dict]:
    """同步版本的知识库检索（兼容旧接口）"""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(
                    asyncio.run, async_search_policy_chunks(query, top_k)
                ).result()
        else:
            return loop.run_until_complete(async_search_policy_chunks(query, top_k))
    except RuntimeError:
        return asyncio.run(async_search_policy_chunks(query, top_k))
