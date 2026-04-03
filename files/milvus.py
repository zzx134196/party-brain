from typing import Any, Dict, List, Optional, Union
import asyncio
from pymilvus import DataType, AsyncMilvusClient, MilvusClient, AnnSearchRequest, WeightedRanker, CollectionSchema, Function, FunctionType
from pymilvus.milvus_client import IndexParams
from .base import VectorStoreBase
from utils.log import logger
from core.config import config

Feild_map = {
    "int": DataType.INT64,
    "float": DataType.FLOAT,
    "string": DataType.VARCHAR,
    "dense_vector": DataType.FLOAT_VECTOR,
    "float_vector": DataType.FLOAT_VECTOR,
    "sparse_vector": DataType.SPARSE_FLOAT_VECTOR,
    "dict": DataType.JSON,
    "json": DataType.JSON,  # 支持json类型别名
}


class MilvusVectorStore(VectorStoreBase):
    """
    基于Milvus的向量存储实现
    
    支持向量搜索、关键词搜索和混合搜索
    使用Milvus的多向量字段功能和混合搜索
    """
    
    def __init__(
        self,
        uri: str = "http://localhost:19530",
        username: str = "",
        password: str = "",
        use_sparse_vector: bool = True,
        **kwargs
    ):
        """
        初始化Milvus向量存储
        
        参数:
            uri: Milvus服务器地址
            username: 认证用户名
            password: 认证密码
            use_sparse_vector: 是否使用稀疏向量字段
            **kwargs: 其他Milvus客户端参数
        """
        self.uri = uri
        self.username = username
        self.password = password
        self.use_sparse_vector = use_sparse_vector
        
        # 构建连接参数
        conn_params = {"uri": uri}
        if username and password:
            conn_params["user"] = username
            conn_params["password"] = password
        # 创建Milvus客户端
        self.client = None
        self.Asyclient = None
        try:
            self.client = MilvusClient(uri=uri, user=username, password=password)
            self.Asyclient = AsyncMilvusClient(uri=uri, user=username, password=password)
        except Exception as exc:
            logger.warning(f"Milvus client init failed, will retry on demand: {exc}")

    def _ensure_clients(self) -> None:
        if self.client is not None and self.Asyclient is not None:
            return
        self.client = MilvusClient(uri=self.uri, user=self.username, password=self.password)
        self.Asyclient = AsyncMilvusClient(
            uri=self.uri, user=self.username, password=self.password
        )
    
    async def _check_collection_exists(self, collection_name: str) -> bool:
        self._ensure_clients()
        return self.client.has_collection(collection_name)
    
    async def define_collection_schema(self, schema_dict: Dict[str, Any], description: str|None = None) -> CollectionSchema:
        """将字典转换为Milvus集合结构"""
        self._ensure_clients()
        if description is None:
            description = "集合结构配置"
        schema = self.client.create_schema(
            auto_id=True,
            description=description,
        )
        if 'id' not in schema_dict:
            schema.add_field('id',DataType.INT64,is_primary=True)
        for field_name, field_meta in schema_dict.items():
            field_meta = dict(field_meta)
            field_type_str = field_meta.pop('type', 'string')
            field_type = Feild_map.get(field_type_str)
            if field_type is None:
                raise ValueError(f"不支持的字段类型: {field_type_str}，支持的类型: {list(Feild_map.keys())}")
            schema.add_field(field_name, field_type, **field_meta)

        if self.use_sparse_vector:
            bm25_function = Function(
                name="text_bm25_emb",
                input_field_names=["text"],
                output_field_names=["sparse_vector"],
                function_type=FunctionType.BM25,
            )
            schema.add_function(bm25_function)

        return schema
    
    async def define_index_params(self, index_params_dict: Dict[str, Any]) -> IndexParams:
        """将字典转换为Milvus索引参数"""
        self._ensure_clients()
        index_params = self.client.prepare_index_params()
        for _, field_meta in index_params_dict.items():
            index_params.add_index(**field_meta)
        return index_params
    
    async def initialize(self, collection_name: str) -> bool:
        """
        初始化集合
        此方法仅检查集合是否存在并加载到内存，但不会自动创建集合
        集合创建应通过create_collection方法显式执行
        参数:
            collection_name: 要初始化的集合名称，必须提供
        返回:
            初始化成功返回True，失败返回False
        """
        # 检查集合是否存在
        has_collection = await self._check_collection_exists(collection_name)
            
        if not has_collection:
            logger.warning(f"集合 {collection_name} 不存在，请先调用create_collection方法创建")
            return False
            
        # 加载集合到内存
        await self.Asyclient.load_collection(collection_name=collection_name)
        return True
    
    async def create_collection(self, collection_name: str, schema: Dict[str, Any], index_params: Dict[str, Any]) -> bool:
        """
        创建集合
        显式创建一个新的集合，如果集合已存在则返回False
        参数:
            collection_name: 要创建的集合名称，必须提供
        返回:
            创建成功返回True，失败或已存在返回False
        """
        has_collection = await self._check_collection_exists(collection_name)
            
        if has_collection:
            logger.warning(f"集合 {collection_name} 已存在，无需创建")
            return False
            
        # 创建集合
        new_schema = await self.define_collection_schema(schema)
        new_index_params = await self.define_index_params(index_params)
        await self.Asyclient.create_collection(
            collection_name=collection_name,
            schema=new_schema,
            index_params=new_index_params
        )
        
        if await self._check_collection_exists(collection_name):
            return True
        else:
            return False
    
    async def drop_collection(self, collection_name: str):
        """
        删除集合
        参数:
            collection_name: 要删除的集合名称
        """
        self._ensure_clients()
        await self.Asyclient.drop_collection(collection_name=collection_name)
    
    async def get_all_collections(self) -> List[str]:
        """
        获取所有集合名称
        
        返回:
            List[str]: 所有集合名称列表
        """
        self._ensure_clients()
        return self.client.list_collections()
    
    async def add(self, document: Dict[str, Any], collection_name: str) -> int:
        """
        添加单个文档
        参数:
            document: 要添加的文档数据字典
            collection_name: 目标集合名称，必须提供
        返回:
            成功插入的文档数量
        """
        if not await self._check_collection_exists(collection_name):
            raise ValueError(f"集合 {collection_name} 不存在，请先调用create_collection方法创建")
        
        result = await self.Asyclient.insert(collection_name=collection_name,data=document)
        return result['insert_count']
    
    async def add_batch(self, documents: List[Dict[str, Any]], collection_name: str, batch_size: int = 1000) -> int:
        """
        批量添加文档
        参数:
            documents: 要添加的文档数据字典列表或Document对象列表
            collection_name: 目标集合名称，必须提供
        返回:
            成功插入的文档数量
        """
        if not await self._check_collection_exists(collection_name):
            raise ValueError(f"集合 {collection_name} 不存在，请先调用create_collection方法创建")
        
        insert_count = 0
        for i in range(0, len(documents), batch_size):
            batch = documents[i:i+batch_size]
            result = await self.Asyclient.insert(collection_name=collection_name,data=batch)
            insert_count += result['insert_count']
        return insert_count
    
    async def get(self, id: int, collection_name: str) -> Optional[Dict[str, Any]]:
        """
        获取指定ID的文档
        参数:
            id: 文档唯一标识
            collection_name: 目标集合名称，必须提供
        返回:
            文档数据字典，如果不存在返回None
        """
        if not await self._check_collection_exists(collection_name):
            raise ValueError(f"集合 {collection_name} 不存在，请先调用create_collection方法创建")

        result = await self.Asyclient.get(collection_name=collection_name, ids=[id])
        # AsyncMilvusClient.get 返回的是字典列表，直接访问即可
        if result and len(result) > 0:
            return result[0]
        return None
    async def upsert(self, document: Dict[str, Any], collection_name: str) -> int:
        """
        插入或更新文档（如果主键已存在则更新，否则插入）

        这是推荐的更新方式，比delete+insert更高效且避免一致性问题

        参数:
            document: 要插入或更新的文档数据字典（必须包含主键字段）
            collection_name: 目标集合名称，必须提供
        返回:
            成功处理的文档数量
        """
        if not await self._check_collection_exists(collection_name):
            raise ValueError(f"集合 {collection_name} 不存在，请先调用create_collection方法创建")

        result = await self.Asyclient.upsert(collection_name=collection_name, data=document)
        return result['upsert_count']

    async def upsert_batch(self, documents: List[Dict[str, Any]], collection_name: str, batch_size: int = 1000) -> int:
        """
        批量插入或更新文档

        参数:
            documents: 要插入或更新的文档数据字典列表（每个文档必须包含主键字段）
            collection_name: 目标集合名称，必须提供
            batch_size: 每批处理的文档数量
        返回:
            成功处理的文档总数
        """
        if not await self._check_collection_exists(collection_name):
            raise ValueError(f"集合 {collection_name} 不存在，请先调用create_collection方法创建")

        upsert_count = 0
        for i in range(0, len(documents), batch_size):
            batch = documents[i:i+batch_size]
            result = await self.Asyclient.upsert(collection_name=collection_name, data=batch)
            upsert_count += result['upsert_count']
        return upsert_count

    async def update(self, id: int, document: Dict[str, Any], collection_name: str) -> bool:
        """
        更新指定ID的文档（使用delete+insert方式）

        注意：推荐使用upsert方法代替此方法，upsert更高效且避免一致性问题
        此方法保留是为了向后兼容

        参数:
            id: 文档唯一标识
            document: 要更新的文档数据字典
            collection_name: 目标集合名称，必须提供
        返回:
            成功返回True，否则返回False
        """
        if not await self._check_collection_exists(collection_name):
            raise ValueError(f"集合 {collection_name} 不存在，请先调用create_collection方法创建")

        result = await self.delete(id,collection_name)
        if result:
            # 等待索引完全更新后再添加新数据，避免一致性问题
            await asyncio.sleep(0.5)
            result =  await self.add(document,collection_name)
            return result > 0
        return False
    
    async def delete(self, id: int, collection_name: str) -> int:
        """
        删除指定ID的文档

        参数:
            id: 文档唯一标识
            collection_name: 目标集合名称，必须提供

        返回:
            成功返回True，否则返回False
        """
        if not await self._check_collection_exists(collection_name):
            raise ValueError(f"集合 {collection_name} 不存在，请先调用create_collection方法创建")

        result = await self.Asyclient.delete(collection_name=collection_name,ids=[id])
        # 强制同步数据，确保删除立即生效
        await self.flush(collection_name)
        return result['delete_count']
    
    async def delete_batch(self, ids: List[int], collection_name: str) -> int:
        """
        批量删除文档

        参数:
            ids: 文档唯一标识列表
            collection_name: 目标集合名称，必须提供

        返回:
            成功返回True，否则返回False
        """
        if not await self._check_collection_exists(collection_name):
            raise ValueError(f"集合 {collection_name} 不存在，请先调用create_collection方法创建")

        result = await self.Asyclient.delete(collection_name=collection_name,ids=ids)
        # 强制同步数据，确保删除立即生效
        await self.flush(collection_name)
        return result['delete_count']

    async def flush(self, collection_name: str, timeout: Optional[float] = None) -> bool:
        """
        强制将集合数据同步到磁盘，确保删除操作立即生效

        参数:
            collection_name: 目标集合名称
            timeout: 可选的超时时间（秒）

        返回:
            成功返回True
        """
        if not await self._check_collection_exists(collection_name):
            raise ValueError(f"集合 {collection_name} 不存在，请先调用create_collection方法创建")

        await self.Asyclient.flush(collection_name=collection_name, timeout=timeout)
        logger.debug(f"集合 {collection_name} flush 完成")
        return True

    async def vector_search(
        self, 
        dense_vector: List[List[float]],
        collection_name: str, 
        anns_field: str,
        output_fields: List[str] = ["*"],
        limit: int = 10, 
        filter: str = ""
    ) -> List[Dict[str, Any]]:
        """
        向量相似度搜索
        
        参数:
            dense_vector: 查询向量
            collection_name: 目标集合名称，必须提供
            anns_field: 向量字段名，必须提供
            output_fields: 返回字段列表
            limit: 返回结果数量上限
            filter: 元数据过滤条件
            
        返回:
            匹配的文档列表，按相似度降序排列
        """
        if not await self.initialize(collection_name):
            raise ValueError(f"集合 {collection_name} 初始化失败，请检查集合是否存在")
            
        # 如果是sparse_vector字段且未启用稀疏向量
        if anns_field == "sparse_vector" and not self.use_sparse_vector:
            raise ValueError("稀疏向量字段未启用，请使用dense_vector字段")

        search_params = {
            "metric_type": "IP",
            "params": {"nprobe": 10}
        }
        result = await self.Asyclient.search(
            collection_name=collection_name,
            data=dense_vector,
            anns_field=anns_field,
            limit=limit,
            filter=filter,
            output_fields=output_fields,
            search_params=search_params
        )
        entities = [hit['entity'] for hits in result for hit in hits]
        logger.info(
            "Milvus vector_search 结果: collection=%s, hit_groups=%s, entities=%s",
            collection_name,
            len(result),
            len(entities),
        )
        return entities
    
    async def query(self, collection_name: str, filters: Dict[str, Any], limit: int = 10) -> List[Dict[str, Any]]:
        """
        根据过滤条件查询文档

        """
        if not await self.initialize(collection_name):
            raise ValueError(f"集合 {collection_name} 初始化失败，请检查集合是否存在")

        # filters 参数需要转换为表达式字符串
        filter_expr = " && ".join([f'{k} == "{v}"' if isinstance(v, str) else f'{k} == {v}' for k, v in filters.items()])
        result = await self.Asyclient.query(collection_name=collection_name, filter=filter_expr, limit=limit)
        # AsyncMilvusClient.query 返回的是字典列表，不需要额外处理
        return list(result)
    
    
    async def keyword_search(
        self, 
        sparse_vector: List[List[float]],
        collection_name: str, 
        anns_field: str = "sparse_vector",
        output_fields: List[str] = ["text", "filename", "department", "metadata"],
        limit: int = 10, 
        filter: str = ""
    ) -> List[Dict[str, Any]]:
        """
        关键词搜索
        
        参数:
            sparse_vector: 查询向量
            collection_name: 目标集合名称，必须提供
            anns_field: 向量字段名，默认为sparse_vector
            output_fields: 返回字段列表
            limit: 返回结果数量上限
            filter: 元数据过滤条件
            
        返回:
            匹配的文档列表，按相关性降序排列
        """
        if not self.use_sparse_vector and anns_field == "sparse_vector":
            raise ValueError("稀疏向量字段未启用，请使用dense_vector或其他字段")
            
        return await self.vector_search(sparse_vector,collection_name,anns_field,output_fields,limit,filter)
        
    
    async def fulltext_search(
        self,
        query_texts: List[str],
        collection_name: str,
        anns_field: str = "sparse_vector",
        output_fields: List[str] = ["text", "filename", "department", "metadata"],
        limit: int = 10,
        filter: str = "",
    ) -> List[Dict[str, Any]]:
        """
        Milvus 2.5 BM25 全文搜索

        直接传入原始文本，Milvus 内部通过 BM25 Function 自动分词和匹配。
        不需要外部 embedding 模型。

        参数:
            query_texts: 查询文本列表（原始字符串，非向量）
            collection_name: 目标集合名称
            anns_field: 稀疏向量字段名，默认 sparse_vector
            output_fields: 返回字段列表
            limit: 返回结果数量上限
            filter: 元数据过滤条件

        返回:
            匹配的文档列表，按 BM25 相关性降序排列
        """
        if not self.use_sparse_vector:
            raise ValueError("全文搜索需要启用稀疏向量（BM25），请设置 MILVUS_USE_SPARSE_VECTOR=true")

        if not await self.initialize(collection_name):
            raise ValueError(f"集合 {collection_name} 初始化失败，请检查集合是否存在")

        logger.info(
            "Milvus fulltext_search: collection=%s, anns_field=%s, limit=%s, filter=%s, queries=%s",
            collection_name,
            anns_field,
            limit,
            filter,
            query_texts,
        )

        search_params = {
        }
        result = await self.Asyclient.search(
            collection_name=collection_name,
            data=query_texts,
            anns_field=anns_field,
            limit=limit,
            filter=filter,
            output_fields=output_fields,
            search_params=search_params,
        )
        return [hit['entity'] for hits in result for hit in hits]

    async def hybrid_search(
        self,
        dense_vector: List[List[float]],
        collection_name: str,
        sparse_vector: List[List[float]] | None = None,
        output_fields: List[str] = ["text", "filename", "department", "metadata"],
        limit: int = 10, 
        filter: str = "",
        dense_weight: float = 1.0,
        sparse_weight: float = 1.0
    ) -> List[Dict[str, Any]]:
        """
        混合搜索（关键词 + 向量）
        
        参数:
            dense_vector: 查询向量
            sparse_vector: 查询稀疏向量（可选，当use_sparse_vector=False时可以为None）
            collection_name: 目标集合名称，必须提供
            output_fields: 返回字段列表
            limit: 返回结果数量上限
            filter: 元数据过滤条件
            dense_weight: 密集向量权重
            sparse_weight: 稀疏向量权重
            
        返回:
            匹配的文档列表，按混合得分降序排列
        """
        if not await self._check_collection_exists(collection_name):
            raise ValueError(f"集合 {collection_name} 不存在，请先调用create_collection方法创建")
        
        if not await self.initialize(collection_name):
            raise ValueError(f"集合 {collection_name} 初始化失败，请检查集合是否存在")
        
        # 如果不使用稀疏向量或未提供稀疏向量，则只进行密集向量搜索
        if not self.use_sparse_vector or sparse_vector is None:
            return await self.vector_search(
                dense_vector=dense_vector,
                collection_name=collection_name,
                anns_field="dense_vector",
                output_fields=output_fields,
                limit=limit,
                filter=filter
            )
        
        dense_search_params = {'metric_type': 'IP'}
        sparse_search_params = {'metric_type': 'IP'}
        dense_search_request = AnnSearchRequest(
            data=dense_vector,
            anns_field="dense_vector",
            param=dense_search_params,
            limit=limit,
            expr=filter
        )
        sparse_search_request = AnnSearchRequest(
            data=sparse_vector,
            anns_field="sparse_vector",
            param=sparse_search_params,
            limit=limit,
            expr=filter
        )
        result = await self.Asyclient.hybrid_search(
            collection_name=collection_name,
            reqs=[dense_search_request, sparse_search_request],
            ranker=WeightedRanker(dense_weight,sparse_weight),
            output_fields=output_fields,
            limit=limit,
        )
        return [hit['entity'] for hits in result for hit in hits]

    async def release_collection(self, collection_name: str) -> bool:
        """
        从内存中释放集合
        
        参数:
            collection_name: 要释放的集合名称
            
        返回:
            释放成功返回True，失败返回False
        """
        if not await self._check_collection_exists(collection_name):
            logger.warning(f"集合 {collection_name} 不存在，无需释放")
            return False
        
        await self.Asyclient.release_collection(collection_name=collection_name)
        logger.info(f"集合 {collection_name} 已从内存中释放")
        return True

    async def close(self):
        """
        关闭连接，释放所有集合资源
        """
        # 获取所有集合
        collections = self.client.list_collections()
        
        # 释放所有集合
        for collection_name in collections:
            # 尝试释放每个集合，但继续处理其他集合
            try:
                await self.release_collection(collection_name)
            except Exception as e:
                # 这里仍捕获异常是为了确保其他集合能被释放
                logger.error(f"释放集合 {collection_name} 失败: {str(e)}")
        
        logger.info("所有集合已释放，资源已清理")
