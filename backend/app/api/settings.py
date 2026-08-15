"""系统设置API路由 - LLM配置管理（持久化到数据库）"""
import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from loguru import logger

from app.models.database import get_db, SessionLocal
from app.models.user import User
from app.models.system_config import SystemConfig
from app.core.auth import require_admin, get_current_user
from app.core.embedding_service import embedding_service
from app.core.llm import llm_service
from app.config import settings

router = APIRouter(prefix="/api/settings", tags=["系统设置"])


# ========== 数据库配置读写工具 ==========

def db_get(db: Session, key: str, default: str = "") -> str:
    """从数据库读取配置"""
    row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    return row.value if row else default


def db_set(db: Session, key: str, value: str):
    """写入配置到数据库"""
    row = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    if row:
        row.value = value
    else:
        db.add(SystemConfig(key=key, value=value))
    db.commit()


def load_runtime_config_from_db():
    """启动时从数据库加载运行时配置，覆盖默认值（供main.py调用）"""
    db = SessionLocal()
    try:
        keys = {
            "llm_base_url": "LLM_BASE_URL",
            "llm_api_key": "LLM_API_KEY",
            "llm_model": "LLM_MODEL",
            "llm_max_tokens": "LLM_MAX_TOKENS",
            "llm_temperature": "LLM_TEMPERATURE",
            "embedding_base_url": "EMBEDDING_BASE_URL",
            "embedding_api_key": "EMBEDDING_API_KEY",
            "embedding_model": "EMBEDDING_MODEL",
            "milvus_uri": "MILVUS_URI",
            "milvus_host": "MILVUS_HOST",
            "milvus_port": "MILVUS_PORT",
            "milvus_collection": "MILVUS_COLLECTION",
        }
        loaded = []
        for db_key, attr in keys.items():
            val = db_get(db, db_key)
            if val:
                if attr in ("LLM_MAX_TOKENS", "MILVUS_PORT"):
                    setattr(settings, attr, int(val))
                elif attr in ("LLM_TEMPERATURE",):
                    setattr(settings, attr, float(val))
                else:
                    setattr(settings, attr, val)
                loaded.append(db_key)

        if loaded:
            # 用加载的配置重新初始化LLM客户端
            llm_service.reinitialize(
                base_url=settings.LLM_BASE_URL,
                api_key=settings.LLM_API_KEY,
                model=settings.LLM_MODEL,
            )
            embedding_service.reset_client()
            logger.info(f"✅ 已从数据库加载运行时配置: {loaded}")
        else:
            logger.info("ℹ️ 数据库中无运行时配置，使用默认值")
    except Exception as e:
        logger.warning(f"从数据库加载运行时配置失败: {e}")
    finally:
        db.close()


# ========== Pydantic模型 ==========

class LLMConfig(BaseModel):
    base_url: str
    api_key: str = "not-needed"
    model: str
    max_tokens: int = 4096
    temperature: float = 0.7


class LLMConfigResponse(BaseModel):
    base_url: str
    api_key_masked: str
    model: str
    max_tokens: int
    temperature: float
    status: str


class LLMTestRequest(BaseModel):
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None


class EmbeddingConfig(BaseModel):
    base_url: str
    model: str
    api_key: str = "not-needed"


class MilvusConfig(BaseModel):
    uri: str = ""
    host: Optional[str] = None
    port: Optional[int] = None
    collection: str


class MilvusTestRequest(BaseModel):
    uri: Optional[str] = None
    collection: Optional[str] = None


def mask_api_key(key: str) -> str:
    if not key or key == "not-needed":
        return key
    if len(key) <= 8:
        return "****"
    return key[:4] + "****" + key[-4:]


# ========== API路由 ==========

@router.get("/llm", response_model=LLMConfigResponse)
async def get_llm_config(current_user: User = Depends(get_current_user)):
    """获取当前LLM配置"""
    return LLMConfigResponse(
        base_url=settings.LLM_BASE_URL,
        api_key_masked=mask_api_key(settings.LLM_API_KEY),
        model=settings.LLM_MODEL,
        max_tokens=settings.LLM_MAX_TOKENS,
        temperature=settings.LLM_TEMPERATURE,
        status="unknown",
    )


@router.put("/llm")
async def update_llm_config(
    config: LLMConfig,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """更新LLM配置（管理员）- 持久化到数据库"""
    # 1. 更新运行时settings
    settings.LLM_BASE_URL = config.base_url
    if config.api_key and config.api_key != "not-needed" and "****" not in config.api_key:
        settings.LLM_API_KEY = config.api_key
    settings.LLM_MODEL = config.model
    settings.LLM_MAX_TOKENS = config.max_tokens
    settings.LLM_TEMPERATURE = config.temperature

    # 2. 持久化到数据库
    db_set(db, "llm_base_url", settings.LLM_BASE_URL)
    db_set(db, "llm_api_key", settings.LLM_API_KEY)
    db_set(db, "llm_model", settings.LLM_MODEL)
    db_set(db, "llm_max_tokens", str(settings.LLM_MAX_TOKENS))
    db_set(db, "llm_temperature", str(settings.LLM_TEMPERATURE))

    # 3. 重新初始化LLM客户端
    llm_service.reinitialize(
        base_url=settings.LLM_BASE_URL,
        api_key=settings.LLM_API_KEY,
        model=settings.LLM_MODEL,
    )

    # 4. 重置Agent引擎（使其重新初始化以使用新的LLM配置）
    from app.api.chat_agent import reset_agent_engine
    reset_agent_engine()

    logger.info(f"LLM配置已保存到数据库: base_url={config.base_url}, model={config.model}")
    return {"message": "LLM配置已保存（重启后仍然有效）", "model": config.model}


@router.post("/llm/test")
async def test_llm_connection(
    req: LLMTestRequest = None,
    current_user: User = Depends(get_current_user),
):
    """测试LLM连接"""
    base_url = req.base_url if req and req.base_url else settings.LLM_BASE_URL
    api_key = req.api_key if req and req.api_key else settings.LLM_API_KEY
    model = req.model if req and req.model else settings.LLM_MODEL

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "你好，请回复'连接成功'"}],
            max_tokens=20,
            timeout=10,
            extra_body={"enable_thinking": False},
        )
        reply = response.choices[0].message.content
        return {
            "status": "connected",
            "message": f"连接成功，模型回复: {reply}",
            "model": model,
        }
    except Exception as e:
        logger.warning(f"LLM连接测试失败: {e}")
        return {
            "status": "disconnected",
            "message": f"连接失败: {str(e)[:200]}",
            "model": model,
        }


@router.get("/embedding")
async def get_embedding_config(current_user: User = Depends(get_current_user)):
    """获取Embedding模型配置"""
    embedding_key = getattr(settings, 'EMBEDDING_API_KEY', settings.LLM_API_KEY)
    return {
        "base_url": settings.EMBEDDING_BASE_URL,
        "model": settings.EMBEDDING_MODEL,
        "api_key_masked": mask_api_key(embedding_key),
    }


@router.put("/embedding")
async def update_embedding_config(
    config: EmbeddingConfig,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """更新Embedding模型配置（管理员）- 持久化到数据库"""
    settings.EMBEDDING_BASE_URL = config.base_url
    settings.EMBEDDING_MODEL = config.model
    if config.api_key and config.api_key != "not-needed" and "****" not in config.api_key:
        settings.EMBEDDING_API_KEY = config.api_key
        db_set(db, "embedding_api_key", config.api_key)

    db_set(db, "embedding_base_url", config.base_url)
    db_set(db, "embedding_model", config.model)

    embedding_service.reset_client()

    logger.info(f"Embedding配置已保存到数据库: base_url={config.base_url}, model={config.model}")
    return {"message": "Embedding配置已保存（重启后仍然有效）"}


@router.get("/milvus")
async def get_milvus_config(current_user: User = Depends(get_current_user)):
    """获取Milvus配置"""
    return {
        "uri": settings.MILVUS_URI,
        "host": settings.MILVUS_HOST,
        "port": settings.MILVUS_PORT,
        "effective_uri": settings.effective_milvus_uri,
        "collection": settings.MILVUS_COLLECTION,
        "mode": settings.milvus_mode,
    }


@router.put("/milvus")
async def update_milvus_config(
    config: MilvusConfig,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """更新Milvus配置（管理员）- 持久化到数据库"""
    settings.MILVUS_URI = config.uri
    settings.MILVUS_HOST = config.host
    settings.MILVUS_PORT = config.port
    settings.MILVUS_COLLECTION = config.collection

    db_set(db, "milvus_uri", config.uri)
    db_set(db, "milvus_host", config.host or "")
    db_set(db, "milvus_port", str(config.port or ""))
    db_set(db, "milvus_collection", config.collection)

    logger.info(
        f"Milvus配置已保存到数据库: uri={settings.MILVUS_URI}, "
        f"host={settings.MILVUS_HOST}, port={settings.MILVUS_PORT}, "
        f"effective_uri={settings.effective_milvus_uri}, collection={settings.MILVUS_COLLECTION}"
    )
    return {
        "message": "Milvus配置已保存（重启后仍然有效）",
        "effective_uri": settings.effective_milvus_uri,
        "mode": settings.milvus_mode,
    }


@router.post("/milvus/test")
async def test_milvus_connection(
    req: MilvusTestRequest = None,
    current_user: User = Depends(get_current_user),
):
    """测试Milvus知识库连接（用于现场确认知识库是否可用）"""
    from app.core.milvus_store import create_vector_store

    uri = (req.uri if req and req.uri else settings.effective_milvus_uri or "").strip()
    collection = (req.collection if req and req.collection else settings.MILVUS_COLLECTION or "").strip()
    mode = "remote" if uri.startswith(("http://", "https://")) else "local"

    if not uri:
        return {"status": "disconnected", "message": "未配置 Milvus 地址", "uri": uri, "collection": collection, "mode": mode}

    try:
        store = await asyncio.wait_for(
            asyncio.to_thread(create_vector_store, uri),
            timeout=8,
        )
        exists = await asyncio.wait_for(
            store.ensure_collection(collection, dimension=1024),
            timeout=8,
        )
        if not exists:
            return {
                "status": "disconnected",
                "message": f"连接成功，但集合 {collection} 不存在，请检查集合名称或联系总系统创建。",
                "uri": uri,
                "collection": collection,
                "mode": mode,
            }

        # 再做一次检索验证，确认集合可正常查询
        try:
            await asyncio.wait_for(
                store.vector_search(
                    query_vectors=[[0.0] * 1024],
                    collection_name=collection,
                    output_fields=["text"],
                    limit=1,
                ),
                timeout=8,
            )
            return {
                "status": "connected",
                "message": f"连接成功，集合 {collection} 存在且检索可用。",
                "uri": uri,
                "collection": collection,
                "mode": mode,
            }
        except Exception as search_err:
            return {
                "status": "connected",
                "message": f"集合存在，但检索测试失败（可能向量维度不一致）：{str(search_err)[:200]}",
                "uri": uri,
                "collection": collection,
                "mode": mode,
            }
    except Exception as e:
        logger.warning(f"Milvus连接测试失败: {e}")
        return {
            "status": "disconnected",
            "message": f"Milvus连接失败：{str(e)[:200]}",
            "uri": uri,
            "collection": collection,
            "mode": mode,
        }


class EmbeddingTestRequest(BaseModel):
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None


@router.post("/embedding/test")
async def test_embedding_connection(
    req: EmbeddingTestRequest = None,
    current_user: User = Depends(get_current_user),
):
    """测试Embedding模型连接"""
    base_url = req.base_url if req and req.base_url else settings.EMBEDDING_BASE_URL
    api_key = req.api_key if req and req.api_key else getattr(settings, 'EMBEDDING_API_KEY', settings.LLM_API_KEY)
    model = req.model if req and req.model else settings.EMBEDDING_MODEL

    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        response = await client.embeddings.create(
            model=model,
            input=["测试连接"],
        )
        dim = len(response.data[0].embedding)
        return {
            "status": "connected",
            "message": f"连接成功，模型 {model}，向量维度: {dim}",
            "model": model,
            "dimension": dim,
        }
    except Exception as e:
        logger.warning(f"Embedding连接测试失败: {e}")
        return {
            "status": "disconnected",
            "message": f"连接失败: {str(e)[:200]}",
            "model": model,
        }


@router.get("/overview")
async def get_system_overview(current_user: User = Depends(get_current_user)):
    """获取系统概览信息"""
    from app.models.template import Template
    from app.models.conversation import Conversation

    db = SessionLocal()
    try:
        return {
            "app_name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "llm_model": settings.LLM_MODEL,
            "llm_base_url": settings.LLM_BASE_URL,
            "database": "SQLite" if settings.DATABASE_URL.startswith("sqlite") else "MySQL",
            "knowledge_source": (
                f"{'远程Milvus' if settings.milvus_mode == 'remote' else '本地向量存储'} + Embedding "
                f"({settings.EMBEDDING_MODEL} / {settings.MILVUS_COLLECTION} / {settings.effective_milvus_uri})"
            ),
            "stats": {
                "templates": db.query(Template).filter(Template.is_active == True).count(),
                "conversations": db.query(Conversation).count(),
            },
        }
    finally:
        db.close()
