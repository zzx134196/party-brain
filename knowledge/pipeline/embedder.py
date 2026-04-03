"""向量化与存储模块 - Embedding + Milvus"""
from typing import List, Dict

from loguru import logger

from app.config import settings


EMBEDDING_BATCH_SIZE = 10  # 部分API限制单次最多10条


async def get_embeddings(texts: List[str]) -> List[List[float]]:
    """获取文本的Embedding向量（自动分批，每批最多10条）"""
    try:
        from openai import AsyncOpenAI

        embedding_key = getattr(settings, 'EMBEDDING_API_KEY', settings.LLM_API_KEY)
        client = AsyncOpenAI(
            base_url=settings.EMBEDDING_BASE_URL,
            api_key=embedding_key,
        )

        all_embeddings = []
        for i in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batch = texts[i:i + EMBEDDING_BATCH_SIZE]
            response = await client.embeddings.create(
                model=settings.EMBEDDING_MODEL,
                input=batch,
            )
            all_embeddings.extend([item.embedding for item in response.data])
            if i + EMBEDDING_BATCH_SIZE < len(texts):
                logger.debug(f"Embedding进度: {min(i + EMBEDDING_BATCH_SIZE, len(texts))}/{len(texts)}")

        return all_embeddings
    except Exception as e:
        logger.error(f"Embedding获取失败: {e}")
        raise


async def embed_and_store(chunks: List[Dict], document_id: int) -> List[str]:
    """向量化切片并存入Milvus"""
    if not chunks:
        return []

    texts = [chunk["content"] for chunk in chunks]

    # 获取Embedding
    embeddings = await get_embeddings(texts)

    # 存入Milvus
    try:
        from pymilvus import connections, Collection, FieldSchema, CollectionSchema, DataType, utility

        # 连接Milvus
        connections.connect(
            alias="default",
            host=settings.MILVUS_HOST,
            port=settings.MILVUS_PORT,
        )

        collection_name = settings.MILVUS_COLLECTION
        dim = len(embeddings[0])

        # 创建Collection（如果不存在）
        if not utility.has_collection(collection_name):
            fields = [
                FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
                FieldSchema(name="document_id", dtype=DataType.INT64),
                FieldSchema(name="chunk_index", dtype=DataType.INT64),
                FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=10000),
                FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=500),
                FieldSchema(name="hierarchy", dtype=DataType.VARCHAR, max_length=500),
                FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=500),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
            ]
            schema = CollectionSchema(fields=fields, description="政策知识库向量")
            collection = Collection(name=collection_name, schema=schema)

            # 创建索引
            index_params = {
                "metric_type": "IP",
                "index_type": "IVF_FLAT",
                "params": {"nlist": 128},
            }
            collection.create_index(field_name="embedding", index_params=index_params)
            logger.info(f"Milvus Collection '{collection_name}' 已创建")
        else:
            collection = Collection(name=collection_name)

        # 插入数据
        data = [
            [document_id] * len(chunks),                           # document_id
            list(range(len(chunks))),                              # chunk_index
            [c["content"][:9999] for c in chunks],                 # content
            [c.get("title", "")[:499] for c in chunks],            # title
            [c.get("hierarchy", "")[:499] for c in chunks],        # hierarchy
            [c.get("source", "")[:499] for c in chunks],           # source
            embeddings,                                            # embedding
        ]

        result = collection.insert(data)
        collection.flush()

        ids = [str(pk) for pk in result.primary_keys]
        logger.info(f"已向Milvus插入{len(ids)}条向量, document_id={document_id}")

        return ids
    except ImportError:
        logger.warning("pymilvus未安装，跳过向量存储")
        return [f"mock_{i}" for i in range(len(chunks))]
    except Exception as e:
        logger.error(f"Milvus存储失败: {e}")
        raise


async def search_similar(query: str, top_k: int = 5, document_ids: List[int] = None) -> List[Dict]:
    """在知识库中搜索相似内容"""
    try:
        from pymilvus import connections, Collection

        # 获取查询向量
        query_embedding = (await get_embeddings([query]))[0]

        # 连接Milvus
        connections.connect(
            alias="default",
            host=settings.MILVUS_HOST,
            port=settings.MILVUS_PORT,
        )

        collection = Collection(name=settings.MILVUS_COLLECTION)
        collection.load()

        # 构建搜索参数
        search_params = {"metric_type": "IP", "params": {"nprobe": 10}}
        expr = None
        if document_ids:
            ids_str = ", ".join(str(i) for i in document_ids)
            expr = f"document_id in [{ids_str}]"

        results = collection.search(
            data=[query_embedding],
            anns_field="embedding",
            param=search_params,
            limit=top_k,
            expr=expr,
            output_fields=["document_id", "chunk_index", "content", "title", "hierarchy", "source"],
        )

        hits = []
        for hit in results[0]:
            hits.append({
                "score": hit.score,
                "document_id": hit.entity.get("document_id"),
                "chunk_index": hit.entity.get("chunk_index"),
                "content": hit.entity.get("content"),
                "title": hit.entity.get("title"),
                "hierarchy": hit.entity.get("hierarchy"),
                "source": hit.entity.get("source"),
            })

        return hits
    except Exception as e:
        logger.error(f"Milvus搜索失败: {e}")
        return []
