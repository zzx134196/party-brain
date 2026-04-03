"""Embedding 服务 - 封装 OpenAI 兼容的 Embedding API"""
import asyncio
from typing import List

from loguru import logger
from openai import AsyncOpenAI

from app.config import settings


class EmbeddingService:
    """Embedding 向量化服务，支持 OpenAI 兼容 API"""

    def __init__(self):
        self._client = None

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(
                base_url=settings.EMBEDDING_BASE_URL,
                api_key=settings.EMBEDDING_API_KEY,
            )
        return self._client

    def reset_client(self):
        """配置更新后重置客户端"""
        self._client = None

    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """
        批量生成文本的 embedding 向量。

        Args:
            texts: 文本列表

        Returns:
            对应的向量列表，每个向量为 float list
        """
        if not texts:
            return []

        client = self._get_client()
        model = settings.EMBEDDING_MODEL

        # 按批次处理，DashScope 限制单次最多 10 条
        batch_size = 6
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            # 截断过长的文本（大多数 embedding 模型最多支持 512-8192 tokens）
            batch = [t[:8000] if len(t) > 8000 else t for t in batch]

            try:
                response = await client.embeddings.create(
                    model=model,
                    input=batch,
                )
                batch_embeddings = [item.embedding for item in response.data]
                all_embeddings.extend(batch_embeddings)
            except Exception as e:
                logger.error(f"Embedding API 调用失败 (batch {i // batch_size}): {e}")
                raise

        logger.info(f"成功生成 {len(all_embeddings)} 个 embedding 向量，维度={len(all_embeddings[0]) if all_embeddings else '?'}")
        return all_embeddings

    async def embed_query(self, query: str) -> List[float]:
        """
        生成单个查询文本的 embedding 向量。

        Args:
            query: 查询文本

        Returns:
            向量 (float list)
        """
        results = await self.embed_texts([query])
        return results[0]

    async def get_dimension(self) -> int:
        """测试连接并获取 embedding 维度"""
        vec = await self.embed_query("测试")
        return len(vec)


# 全局单例
embedding_service = EmbeddingService()
