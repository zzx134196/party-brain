"""统一检索模块 - 基于 Embedding 语义搜索

使用 embedding 模型将查询文本向量化，然后在 Milvus / 本地向量库中进行
余弦相似度搜索，返回最相关的知识库切片。

检索失败时不再静默返回空列表，而是通过 status 明确暴露失败原因；
远程 Milvus 不可用时自动回退到本地缓存向量库，尽量保证政策咨询有据可查。
"""
import asyncio
import json
from pathlib import Path
from typing import List, Dict, Tuple

from loguru import logger

from app.config import settings
from app.core.milvus_store import create_vector_store
from app.core.embedding_service import embedding_service


_store = None  # 缓存实例
_store_uri = None

# 本地缓存向量库（远程 Milvus 不可用时的降级数据源）
LOCAL_FALLBACK_DB = str(Path(__file__).resolve().parents[2] / "milvus_data.db")

SIMILARITY_THRESHOLD = 0.3  # Cosine similarity阈值，低于此值视为无关


def _get_store():
    """获取或创建向量存储实例（根据 MILVUS_URI 自动选择模式）"""
    global _store, _store_uri
    current_uri = settings.effective_milvus_uri
    if _store is None or _store_uri != current_uri:
        _store = create_vector_store(current_uri)
        _store_uri = current_uri
        logger.info(f"已初始化向量存储: mode={settings.milvus_mode}, uri={current_uri}")
    return _store


def _format_hits(entities: List[Dict]) -> List[Dict]:
    """将向量检索返回的实体格式化为统一结构，并做阈值过滤"""
    hits = []
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
    return hits


def _new_status() -> Dict:
    """创建检索状态对象"""
    return {
        "success": False,
        "error": None,
        "mode": settings.milvus_mode,
        "collection": settings.MILVUS_COLLECTION,
        "used_fallback": False,
        "fallback_reason": None,
        "reason": None,
        "result_count": 0,
    }


async def async_search_policy_chunks_with_status(
    query: str,
    top_k: int = 5,
) -> Tuple[List[Dict], Dict]:
    """
    异步知识库语义检索（带状态返回）。

    返回 (hits, status)：
    - hits: 格式化后的知识库切片
    - status: 检索状态，包含 success/error/mode/used_fallback/reason 等

    远程 Milvus 调用失败时自动尝试本地缓存向量库（backend/milvus_data.db），
    并在 status 中标注 used_fallback，方便上层给用户明确提示。
    """
    status = _new_status()

    # 1. 生成查询向量
    try:
        query_vector = await asyncio.wait_for(
            embedding_service.embed_query(query),
            timeout=15,
        )
    except Exception as e:
        status["error"] = (
            f"Embedding服务不可用（{settings.EMBEDDING_BASE_URL} / "
            f"{settings.EMBEDDING_MODEL}）：{e}"
        )
        logger.error(f"Embedding 语义检索失败: {status['error']}")
        return [], status

    # 2. 向量检索
    store = None
    entities = []
    remote_error = None
    try:
        store = await asyncio.wait_for(asyncio.to_thread(_get_store), timeout=8)
        entities = await asyncio.wait_for(
            store.vector_search(
                query_vectors=[query_vector],
                collection_name=settings.MILVUS_COLLECTION,
                output_fields=["text", "filename", "department", "metadata"],
                limit=top_k,
            ),
            timeout=10,
        )
    except Exception as e:
        remote_error = str(e)
        logger.warning(f"主知识库检索失败（将尝试降级）: {remote_error}")

    # 3. 远程失败或未命中时尝试本地缓存向量库
    if not entities and (remote_error or settings.milvus_mode == "remote"):
        fallback_path = LOCAL_FALLBACK_DB
        if Path(fallback_path).exists():
            try:
                logger.info(f"尝试使用本地缓存知识库: {fallback_path}")
                status["fallback_reason"] = remote_error or "主知识库未命中相关条款"
                fallback_store = create_vector_store(fallback_path)
                entities = await asyncio.wait_for(
                    fallback_store.vector_search(
                        query_vectors=[query_vector],
                        collection_name=settings.MILVUS_COLLECTION,
                        output_fields=["text", "filename", "department", "metadata"],
                        limit=top_k,
                    ),
                    timeout=10,
                )
                status["used_fallback"] = True
            except Exception as fallback_err:
                logger.error(f"本地缓存知识库检索失败: {fallback_err}")
        else:
            logger.warning(f"本地缓存知识库不存在: {fallback_path}")

    # 4. 格式化结果
    hits = _format_hits(entities) if entities else []
    status["result_count"] = len(hits)

    if remote_error:
        if hits:
            status["success"] = True
            status["error"] = remote_error
            logger.info(
                f"主知识库失败但本地缓存命中：{len(hits)} 条结果"
                f"（原始错误: {remote_error[:120]}）"
            )
        else:
            status["success"] = False
            status["error"] = remote_error
            logger.error(f"知识库检索失败且本地缓存未命中: {remote_error}")
            return [], status

    status["success"] = True
    if not hits:
        status["reason"] = "empty_result"
        logger.info("Embedding 语义检索未命中任何结果")

    logger.info(
        f"Embedding 语义检索成功，返回 {len(hits)} 条有效结果"
        f"（mode={status['mode']}, used_fallback={status['used_fallback']}）"
    )
    return hits, status


async def async_search_policy_chunks(query: str, top_k: int = 5) -> List[Dict]:
    """异步版本的知识库语义检索（兼容旧接口，只返回切片列表）。"""
    hits, _ = await async_search_policy_chunks_with_status(query, top_k=top_k)
    return hits


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
