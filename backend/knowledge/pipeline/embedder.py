"""向量化和存储模块 - 可选的Milvus向量化"""
from typing import List, Dict
import asyncio

async def embed_and_store(chunks: List[Dict[str, str]], doc_id: int) -> List[str]:
    """
    向量化切片并存储到Milvus（可选功能）
    
    Args:
        chunks: 切片列表
        doc_id: 文档ID
        
    Returns:
        Milvus ID列表
    """
    # 暂时返回空ID列表，表示跳过Milvus存储
    # 实际项目中可以接入Milvus向量数据库
    return ["" for _ in chunks]
