"""向量存储封装 - 支持远程 Milvus 和本地 SQLite+numpy 两种模式

根据 MILVUS_URI 配置自动选择：
- http://xxx:19530 → 远程 Milvus 模式（生产环境）
- sqlite 或文件路径 → 本地 SQLite + numpy 模式（开发测试）
"""
import json
import os
import asyncio
import sqlite3
import struct
from typing import Any, Dict, List, Optional
from loguru import logger


def create_vector_store(uri: str):
    """工厂函数：根据 URI 创建合适的向量存储实例"""
    if uri.startswith("http://") or uri.startswith("https://"):
        return MilvusVectorStore(uri=uri)
    else:
        return LocalVectorStore(db_path=uri)


# ═══════════════════════════════════════════════════════════════════════════════
# 远程 Milvus 向量存储（连接总系统 Milvus 实例）
# ═══════════════════════════════════════════════════════════════════════════════

class MilvusVectorStore:
    """远程 Milvus 向量存储（连接 Milvus 服务器）"""

    def __init__(self, uri: str = "http://127.0.0.1:19530"):
        self.uri = uri
        self.client = None
        try:
            from pymilvus import MilvusClient
            self.client = MilvusClient(uri=uri)
            logger.info(f"Milvus 远程连接成功: {uri}")
        except Exception as exc:
            logger.warning(f"Milvus 连接失败: {exc}")
        self._loaded_collections = set()

    def _ensure_client(self):
        if self.client is not None:
            return
        from pymilvus import MilvusClient
        self.client = MilvusClient(uri=self.uri)

    async def ensure_collection(self, collection_name: str, dimension: int = 1024) -> bool:
        """确保 collection 存在"""
        self._ensure_client()
        if self.client.has_collection(collection_name):
            return True
        # 远程 Milvus 通常由总系统创建 collection，这里只检查
        logger.warning(f"集合 {collection_name} 不存在，请先通过总系统创建")
        return False

    async def insert_with_vectors(self, rows, vectors, collection_name, dimension=1024):
        """带向量的批量插入"""
        self._ensure_client()
        data = []
        for row, vec in zip(rows, vectors):
            data.append({
                "text": row.get("text", ""),
                "dense_vector": vec,
                "filename": row.get("filename", ""),
                "department": row.get("department", ""),
                "metadata": row.get("metadata", "{}"),
            })
        result = self.client.insert(collection_name=collection_name, data=data)
        ids = result.get("ids", [])
        logger.info(f"向 {collection_name} 写入 {len(ids)} 条记录")
        return ids

    def _ensure_loaded(self, collection_name: str):
        """确保 collection 已 load 到内存（远程 Milvus 必须）"""
        if collection_name in self._loaded_collections:
            return
        try:
            self.client.load_collection(collection_name)
            self._loaded_collections.add(collection_name)
            logger.info(f"已加载集合到内存: {collection_name}")
        except Exception as e:
            logger.warning(f"加载集合 {collection_name} 失败（可能已加载）: {e}")
            self._loaded_collections.add(collection_name)

    async def vector_search(self, query_vectors, collection_name,
                            output_fields=None, limit=10, filter_expr=""):
        """向量语义搜索"""
        self._ensure_client()
        self._ensure_loaded(collection_name)
        if output_fields is None:
            output_fields = ["text", "filename", "department", "metadata"]
        result = await asyncio.to_thread(
            self.client.search,
            collection_name=collection_name,
            data=query_vectors,
            anns_field="dense_vector",
            limit=limit,
            output_fields=output_fields,
            search_params={"metric_type": "IP"},
            filter=filter_expr if filter_expr else "",
        )
        hits = []
        for hit_list in result:
            for hit in hit_list:
                entity = hit.get("entity", {})
                entity["score"] = hit.get("distance", 0)
                hits.append(entity)
        return hits

    async def delete_by_filter(self, collection_name, filter_expr):
        self._ensure_client()
        if not self.client.has_collection(collection_name):
            return 0
        self.client.delete(collection_name=collection_name, filter=filter_expr)
        logger.info(f"从 {collection_name} 删除记录，条件: {filter_expr}")
        return 0


# ═══════════════════════════════════════════════════════════════════════════════
# 本地 SQLite + numpy 向量存储（开发测试用，无需 Milvus 服务器）
# ═══════════════════════════════════════════════════════════════════════════════

def _vec_to_bytes(vec: List[float]) -> bytes:
    """将 float 列表转为 bytes"""
    return struct.pack(f"{len(vec)}f", *vec)


def _bytes_to_vec(data: bytes) -> List[float]:
    """将 bytes 转为 float 列表"""
    n = len(data) // 4
    return list(struct.unpack(f"{n}f", data))


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """计算余弦相似度"""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class LocalVectorStore:
    """本地 SQLite + numpy 向量存储（开发测试用）"""

    def __init__(self, db_path: str = "./vector_store.db"):
        self.db_path = db_path
        self._init_db()
        logger.info(f"本地向量存储初始化: {db_path}")

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vectors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                collection TEXT NOT NULL,
                text TEXT,
                filename TEXT,
                department TEXT,
                metadata TEXT,
                vector BLOB
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_collection
            ON vectors(collection)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_filename
            ON vectors(collection, filename)
        """)
        conn.commit()
        conn.close()

    async def ensure_collection(self, collection_name: str, dimension: int = 1024) -> bool:
        """本地模式不需要预创建，直接返回 True"""
        return True

    async def insert_with_vectors(self, rows, vectors, collection_name, dimension=1024):
        """批量插入文本+向量"""
        conn = sqlite3.connect(self.db_path)
        ids = []
        for row, vec in zip(rows, vectors):
            cur = conn.execute(
                "INSERT INTO vectors (collection, text, filename, department, metadata, vector) VALUES (?,?,?,?,?,?)",
                (
                    collection_name,
                    row.get("text", ""),
                    row.get("filename", ""),
                    row.get("department", ""),
                    row.get("metadata", "{}"),
                    _vec_to_bytes(vec),
                )
            )
            ids.append(cur.lastrowid)
        conn.commit()
        conn.close()
        logger.info(f"本地向量存储: 写入 {len(ids)} 条记录到 {collection_name}")
        return ids

    async def vector_search(self, query_vectors, collection_name,
                            output_fields=None, limit=10, filter_expr=""):
        """向量语义搜索（余弦相似度）"""
        if not query_vectors:
            return []
        query_vec = query_vectors[0]

        conn = sqlite3.connect(self.db_path)
        rows = conn.execute(
            "SELECT id, text, filename, department, metadata, vector FROM vectors WHERE collection = ?",
            (collection_name,)
        ).fetchall()
        conn.close()

        if not rows:
            return []

        # 计算余弦相似度并排序
        scored = []
        for row in rows:
            vec = _bytes_to_vec(row[5])
            score = _cosine_similarity(query_vec, vec)
            scored.append({
                "text": row[1],
                "filename": row[2],
                "department": row[3],
                "metadata": row[4],
                "score": score,
            })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:limit]

    async def delete_by_filter(self, collection_name, filter_expr):
        """按文件名删除"""
        conn = sqlite3.connect(self.db_path)
        # 解析简单的 filename == "xxx" 过滤条件
        if 'filename ==' in filter_expr:
            fname = filter_expr.split('"')[1] if '"' in filter_expr else ""
            if fname:
                conn.execute(
                    "DELETE FROM vectors WHERE collection = ? AND filename = ?",
                    (collection_name, fname)
                )
        conn.commit()
        conn.close()
        logger.info(f"本地向量存储: 删除记录，条件: {filter_expr}")
        return 0
