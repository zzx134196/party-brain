"""政策知识库API路由"""
import os
import shutil
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session
from loguru import logger

from app.config import settings
from app.models.database import get_db
from app.models.user import User
from app.models.policy import PolicyDocument, PolicyChunk, QueryLog
from app.core.auth import get_current_user, require_admin
from app.core.search import async_search_policy_chunks

router = APIRouter(prefix="/api/policy", tags=["政策知识库"])

ALLOWED_EXTS = {".pdf", ".docx", ".doc", ".wps", ".txt"}


# ─── 辅助 ──────────────────────────────────────────────────────────────────────

def _doc_to_dict(doc: PolicyDocument) -> dict:
    return {
        "id": doc.id,
        "filename": doc.filename,
        "title": doc.title or doc.filename,
        "file_type": doc.file_type,
        "status": doc.status,
        "chunk_count": doc.chunk_count or 0,
        "version": doc.version,
        "department": doc.department or "",
        "is_active": doc.is_active,
        "created_at": str(doc.created_at) if doc.created_at else None,
        "updated_at": str(doc.updated_at) if doc.updated_at else None,
    }


async def _do_process(doc_id: int):
    """后台任务：切片 + embedding 向量化 + 写入 Milvus Lite"""
    from app.models.database import SessionLocal
    from app.core.document_processor import extract_text_from_file, split_into_chunks
    from app.core.milvus_store import create_vector_store
    from app.core.embedding_service import embedding_service

    db = SessionLocal()
    try:
        doc = db.query(PolicyDocument).filter(PolicyDocument.id == doc_id).first()
        if not doc:
            return

        doc.status = "processing"
        db.commit()

        # 提取文本
        text = extract_text_from_file(doc.file_path)
        if not text.strip():
            doc.status = "failed"
            db.commit()
            logger.warning(f"文档 {doc.filename} 提取文本为空")
            return

        # 切片（传入科室信息）
        chunks = split_into_chunks(text, doc.filename, department=doc.department or "")
        if not chunks:
            doc.status = "failed"
            db.commit()
            return

        # 删除旧切片记录（重新处理场景）
        db.query(PolicyChunk).filter(PolicyChunk.document_id == doc_id).delete()
        db.commit()

        # ── embedding 向量化 ──────────────────────────────────────────────
        chunk_texts = [c.get("text", "") for c in chunks]
        logger.info(f"正在为 {doc.filename} 的 {len(chunk_texts)} 个切片生成 embedding...")
        
        try:
            vectors = await embedding_service.embed_texts(chunk_texts)
        except Exception as e:
            logger.error(f"Embedding 生成失败: {e}")
            doc.status = "failed"
            db.commit()
            return

        dimension = len(vectors[0]) if vectors else 1024

        # ── 写入 Milvus Lite ──────────────────────────────────────────────
        store = create_vector_store(settings.effective_milvus_uri)

        # 删除旧记录（若有）
        try:
            await store.delete_by_filter(
                settings.MILVUS_COLLECTION,
                f'filename == "{doc.filename}"',
            )
        except Exception as e:
            logger.warning(f"清理旧记录失败（可忽略）: {e}")

        milvus_ids = await store.insert_with_vectors(
            chunks, vectors, settings.MILVUS_COLLECTION, dimension=dimension
        )

        # 写入本地 chunk 记录
        for i, (chunk, mid) in enumerate(zip(chunks, milvus_ids)):
            import json
            meta = {}
            try:
                meta = json.loads(chunk.get("metadata", "{}"))
            except Exception:
                pass
            db.add(PolicyChunk(
                document_id=doc_id,
                chunk_index=i,
                title=meta.get("title", ""),
                content=chunk["text"],
                hierarchy=meta.get("hierarchy", ""),
                milvus_id=str(mid),
            ))

        doc.status = "indexed"
        doc.chunk_count = len(chunks)
        db.commit()
        logger.info(f"文档 {doc.filename} 入库完成，共 {len(chunks)} 条切片（embedding dim={dimension}）")

    except Exception as e:
        logger.error(f"处理文档 {doc_id} 失败: {e}")
        db = SessionLocal()
        try:
            doc = db.query(PolicyDocument).filter(PolicyDocument.id == doc_id).first()
            if doc:
                doc.status = "failed"
                db.commit()
        finally:
            db.close()
    finally:
        db.close()


# ─── 文档管理接口 ───────────────────────────────────────────────────────────────

@router.get("/documents")
async def list_documents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取所有文档列表"""
    docs = db.query(PolicyDocument).order_by(PolicyDocument.id.desc()).all()
    return [_doc_to_dict(d) for d in docs]


@router.post("/documents/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    department: Optional[str] = Form(None),
    auto_process: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """上传单个文档"""
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_EXTS:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型，仅支持: {', '.join(ALLOWED_EXTS)}")

    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    file_path = os.path.join(settings.UPLOAD_DIR, file.filename)

    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    doc = PolicyDocument(
        filename=file.filename,
        title=title or os.path.splitext(file.filename)[0],
        file_path=file_path,
        file_type=ext.lstrip("."),
        status="pending",
        department=department or "",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    if auto_process:
        background_tasks.add_task(_do_process, doc.id)

    return {"message": f"{file.filename} 上传成功", "document": _doc_to_dict(doc)}


@router.post("/batch-upload")
async def batch_upload(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    department: Optional[str] = Form(None),
    auto_process: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """批量上传文档"""
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    results = []
    for file in files:
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in ALLOWED_EXTS:
            results.append({"filename": file.filename, "status": "skipped", "reason": "不支持的文件类型"})
            continue
        file_path = os.path.join(settings.UPLOAD_DIR, file.filename)
        with open(file_path, "wb") as f:
            f.write(await file.read())
        doc = PolicyDocument(
            filename=file.filename,
            title=os.path.splitext(file.filename)[0],
            file_path=file_path,
            file_type=ext.lstrip("."),
            status="pending",
            department=department or "",
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)
        if auto_process:
            background_tasks.add_task(_do_process, doc.id)
        results.append({"filename": file.filename, "status": "uploaded", "id": doc.id})

    success = sum(1 for r in results if r["status"] == "uploaded")
    return {"message": f"批量上传完成，成功 {success}/{len(files)} 个", "results": results}


@router.post("/documents/{doc_id}/process")
async def process_document(
    doc_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """触发文档切片解析入库"""
    doc = db.query(PolicyDocument).filter(PolicyDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    if doc.status == "processing":
        raise HTTPException(status_code=400, detail="文档正在处理中")
    background_tasks.add_task(_do_process, doc_id)
    return {"message": f"{doc.filename} 开始解析入库"}


@router.post("/documents/batch-process")
async def batch_process(
    background_tasks: BackgroundTasks,
    doc_ids: Optional[List[int]] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """批量触发解析（不传 doc_ids 则处理所有 pending/failed）"""
    if doc_ids:
        docs = db.query(PolicyDocument).filter(PolicyDocument.id.in_(doc_ids)).all()
    else:
        docs = db.query(PolicyDocument).filter(
            PolicyDocument.status.in_(["pending", "failed"])
        ).all()

    count = 0
    for doc in docs:
        if doc.status != "processing":
            background_tasks.add_task(_do_process, doc.id)
            count += 1

    return {"message": f"已触发 {count} 个文档解析入库"}


@router.put("/documents/{doc_id}/deactivate")
async def deactivate_document(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """标记文档为废止"""
    doc = db.query(PolicyDocument).filter(PolicyDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    doc.is_active = "废止"
    db.commit()
    return {"message": "已标记为废止"}


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """删除文档（同时清理 Milvus 和本地文件）"""
    doc = db.query(PolicyDocument).filter(PolicyDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")

    # 清理 Milvus Lite
    try:
        from app.core.milvus_store import create_vector_store
        store = create_vector_store(settings.effective_milvus_uri)
        await store.delete_by_filter(
            settings.MILVUS_COLLECTION,
            f'filename == "{doc.filename}"',
        )
    except Exception as e:
        logger.warning(f"删除 Milvus 记录失败（可忽略）: {e}")

    # 删除本地文件
    try:
        if doc.file_path and os.path.exists(doc.file_path):
            os.remove(doc.file_path)
    except Exception as e:
        logger.warning(f"删除本地文件失败: {e}")

    # 删除数据库记录
    db.query(PolicyChunk).filter(PolicyChunk.document_id == doc_id).delete()
    db.delete(doc)
    db.commit()
    return {"message": "删除成功"}


@router.post("/documents/batch-delete")
async def batch_delete(
    doc_ids: List[int],
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """批量删除文档"""
    docs = db.query(PolicyDocument).filter(PolicyDocument.id.in_(doc_ids)).all()
    deleted = 0
    for doc in docs:
        try:
            from app.core.milvus_store import create_vector_store
            store = create_vector_store(settings.effective_milvus_uri)
            await store.delete_by_filter(
                settings.MILVUS_COLLECTION,
                f'filename == "{doc.filename}"',
            )
        except Exception as e:
            logger.warning(f"删除 Milvus 记录失败: {e}")
        try:
            if doc.file_path and os.path.exists(doc.file_path):
                os.remove(doc.file_path)
        except Exception:
            pass
        db.query(PolicyChunk).filter(PolicyChunk.document_id == doc.id).delete()
        db.delete(doc)
        deleted += 1

    db.commit()
    return {"message": f"已删除 {deleted} 个文档"}


@router.get("/documents/{doc_id}/chunks")
async def get_document_chunks(
    doc_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取文档切片列表"""
    doc = db.query(PolicyDocument).filter(PolicyDocument.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    chunks = db.query(PolicyChunk).filter(
        PolicyChunk.document_id == doc_id
    ).order_by(PolicyChunk.chunk_index).all()
    return {
        "document": _doc_to_dict(doc),
        "chunks": [
            {
                "id": c.id,
                "index": c.chunk_index,
                "title": c.title,
                "content": c.content[:200] + "..." if len(c.content) > 200 else c.content,
                "hierarchy": c.hierarchy,
            }
            for c in chunks
        ],
    }


# ─── 检索与统计接口 ─────────────────────────────────────────────────────────────

class PolicySearchRequest(BaseModel):
    query: str
    top_k: int = 5


@router.post("/search")
async def search_policy(
    req: PolicySearchRequest,
    current_user: User = Depends(get_current_user),
):
    """检索知识库"""
    results = await async_search_policy_chunks(req.query, top_k=req.top_k)
    return {
        "query": req.query,
        "count": len(results),
        "results": results,
    }


@router.get("/stats/hotwords")
async def get_hotwords(
    days: int = 7,
    limit: int = 10,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """热点问题统计"""
    from sqlalchemy import func
    from datetime import datetime, timedelta

    since = datetime.now() - timedelta(days=days)
    results = (
        db.query(QueryLog.query_text, func.count(QueryLog.id).label("count"))
        .filter(QueryLog.created_at >= since)
        .filter(QueryLog.query_type.in_(["policy_qa", "compliance_check"]))
        .group_by(QueryLog.query_text)
        .order_by(func.count(QueryLog.id).desc())
        .limit(limit)
        .all()
    )
    return {
        "period_days": days,
        "data": [{"query": r[0][:100], "count": r[1]} for r in results],
    }


@router.get("/stats/usage")
async def get_usage_stats(
    days: int = 7,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """功能使用统计"""
    from sqlalchemy import func
    from datetime import datetime, timedelta

    since = datetime.now() - timedelta(days=days)
    results = (
        db.query(QueryLog.query_type, func.count(QueryLog.id).label("count"))
        .filter(QueryLog.created_at >= since)
        .group_by(QueryLog.query_type)
        .all()
    )

    type_labels = {
        "template": "模板生成",
        "policy_qa": "政策咨询",
        "compliance_check": "合规判断",
        "file_diff": "文件对比",
    }

    return {
        "period_days": days,
        "data": [
            {"type": r[0], "label": type_labels.get(r[0], r[0]), "count": r[1]}
            for r in results
        ],
    }
