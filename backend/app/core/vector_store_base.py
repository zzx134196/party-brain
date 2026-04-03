"""向量存储基类（来源：总管理系统SDK）"""
from typing import Any, Dict, List, Optional


class VectorStoreBase:
    """
    向量存储的基类，定义了向量数据库的基本操作接口。
    为了兼容历史测试，基类允许直接实例化，具体实现由子类覆盖。
    """

    def __init__(self, uri: Optional[str] = None, **kwargs) -> None:
        self.uri = uri
        self.options = dict(kwargs)

    async def add(self, document: Dict[str, Any], collection_name: str) -> int:
        raise NotImplementedError("VectorStoreBase.add must be implemented by subclass.")

    async def add_batch(
        self, documents: List[Dict[str, Any]], collection_name: str, batch_size: int = 1000
    ) -> int:
        raise NotImplementedError(
            "VectorStoreBase.add_batch must be implemented by subclass."
        )

    async def get(self, id: int, collection_name: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError("VectorStoreBase.get must be implemented by subclass.")

    async def update(self, id: int, document: Dict[str, Any], collection_name: str) -> bool:
        raise NotImplementedError("VectorStoreBase.update must be implemented by subclass.")

    async def delete(self, id: int, collection_name: str) -> int:
        raise NotImplementedError("VectorStoreBase.delete must be implemented by subclass.")

    async def delete_batch(self, ids: List[int], collection_name: str) -> int:
        raise NotImplementedError(
            "VectorStoreBase.delete_batch must be implemented by subclass."
        )

    async def vector_search(
        self,
        dense_vector: List[List[float]],
        collection_name: str,
        anns_field: str,
        output_fields: List[str] = ["*"],
        limit: int = 10,
        filter: str = "",
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError(
            "VectorStoreBase.vector_search must be implemented by subclass."
        )

    async def query(
        self, collection_name: str, filters: Dict[str, Any], limit: int = 10
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError("VectorStoreBase.query must be implemented by subclass.")

    async def keyword_search(
        self,
        sparse_vector: List[List[float]],
        collection_name: str,
        anns_field: str = "sparse_vector",
        output_fields: List[str] = ["text", "filename", "department", "metadata"],
        limit: int = 10,
        filter: str = "",
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError(
            "VectorStoreBase.keyword_search must be implemented by subclass."
        )

    async def fulltext_search(
        self,
        query_texts: List[str],
        collection_name: str,
        anns_field: str = "sparse_vector",
        output_fields: List[str] = ["text", "filename", "department", "metadata"],
        limit: int = 10,
        filter: str = "",
    ) -> List[Dict[str, Any]]:
        """BM25 全文搜索，直接传入文本"""
        raise NotImplementedError(
            "VectorStoreBase.fulltext_search must be implemented by subclass."
        )

    async def hybrid_search(
        self,
        dense_vector: List[List[float]],
        collection_name: str,
        sparse_vector: List[List[float]] | None = None,
        output_fields: List[str] = ["text", "filename", "department", "metadata"],
        limit: int = 10,
        filter: str = "",
        dense_weight: float = 1.0,
        sparse_weight: float = 1.0,
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError(
            "VectorStoreBase.hybrid_search must be implemented by subclass."
        )
