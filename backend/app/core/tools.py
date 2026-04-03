"""Agent工具实现 — 8个Tool Handler，封装现有业务逻辑供Agent调用"""
import json
from typing import Dict, Any, List, Optional

from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.agent import ToolResult, ToolRegistry
from app.core.llm import llm_service
from app.core.search import async_search_policy_chunks
from app.core.rag import answer_policy_question, check_compliance as rag_check_compliance, preview_clauses
from app.core.template_gen import generate_outline, generate_full_document, modify_document
from app.core.diff_engine import analyze_diff_with_llm, compute_similarity
from app.models.database import SessionLocal
from app.models.template import Template
from app.models.policy import QueryLog
from app.config import settings


# ========== Tool 1: search_policy ==========

async def handle_search_policy(query: str, top_k: int = 5, **kwargs) -> ToolResult:
    """检索政策知识库"""
    clauses = await async_search_policy_chunks(query, top_k=top_k)

    if not clauses:
        return ToolResult(
            success=True,
            summary="未检索到相关政策条款，知识库可能为空或未匹配到内容",
            data={"type": "policy_search", "clauses": [], "count": 0}
        )

    _log_query("policy_qa", query, f"检索到{len(clauses)}条条款")

    # 提取去重后的来源文件名列表
    sources = []
    seen = set()
    for c in clauses:
        src = c.get("source", "")
        if src and src not in seen:
            seen.add(src)
            sources.append(src)

    return ToolResult(
        success=True,
        summary=f"检索到{len(clauses)}条相关政策条款",
        data={
            "type": "policy_search",
            "clauses": clauses,
            "count": len(clauses),
            "sources": sources,
        }
    )


# ========== Tool 2: check_compliance ==========

async def handle_check_compliance(person_info: str, requirement: str, **kwargs) -> ToolResult:
    """合规条件判断"""
    # 1. 检索相关条款
    search_query = f"{person_info} {requirement}"
    clauses = await async_search_policy_chunks(search_query, top_k=8)

    # 2. 条款预览
    clause_preview = {}
    if clauses:
        try:
            clause_preview = await preview_clauses(search_query, clauses)
        except Exception as e:
            logger.warning(f"条款预览失败: {e}")

    # 3. 执行判断
    try:
        check_result = await rag_check_compliance(
            person_info=person_info,
            requirement=requirement,
            retrieved_clauses=clauses,
        )
    except Exception as e:
        logger.warning(f"合规判断LLM调用失败: {e}")
        return ToolResult(
            success=False,
            summary="合规判断需要AI模型支持，当前模型未连接",
            data={"error": str(e)}
        )

    confidence = check_result.get("confidence", 0.5)
    overall = check_result.get("overall_result", "未知")

    _log_query("compliance_check", f"{person_info} | {requirement}", f"{overall}, 置信度{int(confidence*100)}%")

    return ToolResult(
        success=True,
        summary=f"合规判断完成，结论：{overall}，置信度{int(confidence * 100)}%",
        data={
            "type": "compliance_result",
            "result": {
                "clause_preview": clause_preview,
                "check_result": check_result,
                "confidence": confidence,
                "needs_human_review": confidence < 0.8,
            }
        }
    )


# ========== Tool 3: list_templates ==========

async def handle_list_templates(**kwargs) -> ToolResult:
    """查看可用模板列表"""
    db = SessionLocal()
    try:
        templates = db.query(Template).filter(Template.is_active == True).all()
        template_list = []
        for t in templates:
            required = json.loads(t.required_fields) if t.required_fields else []
            optional = json.loads(t.optional_fields) if t.optional_fields else []
            template_list.append({
                "id": t.id,
                "name": t.name,
                "category": t.category,
                "description": t.description or "",
                "required_fields": required,
                "optional_fields": optional,
            })

        return ToolResult(
            success=True,
            summary=f"当前共有{len(template_list)}个可用模板",
            data={"type": "template_list", "templates": template_list}
        )
    finally:
        db.close()


# ========== Tool 4: generate_document ==========

async def handle_generate_document(
    template_id: int,
    fields: dict = None,
    stage: str = "outline",
    modification_request: str = None,
    original_content: str = None,
    reference_docs: str = "",
    reference_sources: list = None,
    **kwargs,
) -> ToolResult:
    """生成公文文档"""
    fields = fields or {}
    db = SessionLocal()
    try:
        # modify 阶段不依赖模板查找，可以跳过
        if stage == "modify":
            if not original_content or not modification_request:
                return ToolResult(success=False, summary="修改文档需要提供原始内容和修改要求")
            # 尝试获取模板名称（可选）
            tpl_name = "文档"
            if template_id:
                tpl = db.query(Template).filter(Template.id == template_id).first()
                if tpl:
                    tpl_name = tpl.name
            try:
                content = await modify_document(original_content, modification_request)
                # 自动保存文件并生成下载链接
                from app.api.export import auto_save_document
                links = auto_save_document(tpl_name, content)
                return ToolResult(
                    success=True,
                    summary=f"已根据要求修改【{tpl_name}】",
                    data={"type": "document", "content": content, "template_name": tpl_name, "template_id": template_id, **links}
                )
            except Exception as e:
                return ToolResult(success=False, summary=f"文档修改失败: {e}")

        template = db.query(Template).filter(Template.id == template_id).first()
        if not template:
            return ToolResult(success=False, summary=f"模板ID {template_id} 不存在", data={"error": "模板不存在"})

        template_name = template.name
        body_skeleton = template.body_skeleton or ""

        if stage == "full":
            try:
                content = await generate_full_document(
                    template_name=template_name,
                    body_skeleton=body_skeleton,
                    user_fields=fields,
                    reference_docs=reference_docs,
                )
                # 自动保存文件并生成下载链接
                from app.api.export import auto_save_document
                links = auto_save_document(template_name, content)
                return ToolResult(
                    success=True,
                    summary=f"已生成完整文档【{template_name}】",
                    data={"type": "document", "content": content, "template_name": template_name, "template_id": template_id, "reference_sources": reference_sources or [], **links}
                )
            except Exception as e:
                return ToolResult(success=False, summary=f"文档生成失败: {e}")

        _log_query("template", f"生成文档: {template_name}", f"stage={stage}")

        # 默认：outline
        try:
            outline = await generate_outline(
                template_name=template_name,
                body_skeleton=body_skeleton,
                user_fields=fields,
                reference_docs=reference_docs,
            )
            return ToolResult(
                success=True,
                summary=f"已生成【{template_name}】大纲，请确认后生成全文。\n\n💡 如需生成完整文档，请回复「确认」；如需重新生成，请回复「重新生成大纲」。",
                data={
                    "type": "template_outline",
                    "outline": outline,
                    "template_name": template_name,
                    "template_id": template_id,
                    "fields": fields,
                    "reference_sources": reference_sources or [],
                }
            )
        except Exception as e:
            return ToolResult(success=False, summary=f"大纲生成失败: {e}")
    finally:
        db.close()


# ========== Tool 5: export_file ==========

async def handle_export_file(
    format: str,
    title: str,
    content: str = None,
    columns: list = None,
    rows: list = None,
    **kwargs,
) -> ToolResult:
    """导出文件（返回导出标记，由前端触发实际下载）"""
    export_data = {"type": "export_ready", "format": format, "title": title}

    if format in ("word", "pdf") and content:
        export_data["content"] = content
    elif format == "excel" and columns and rows:
        export_data["columns"] = columns
        export_data["rows"] = rows
    else:
        return ToolResult(
            success=False,
            summary=f"导出{format}缺少必要内容",
            data={"error": f"导出{format}需要提供{'content' if format != 'excel' else 'columns和rows'}"}
        )

    return ToolResult(
        success=True,
        summary=f"已准备好{format.upper()}文件导出，前端将自动触发下载",
        data=export_data
    )


# ========== Tool 9: compare_texts ==========

async def handle_compare_texts(
    text1: str,
    text2: str,
    name1: str = "文本1",
    name2: str = "文本2",
    **kwargs,
) -> ToolResult:
    """对比两段文本的差异"""
    if not text1.strip() or not text2.strip():
        return ToolResult(success=False, summary="两段文本均不能为空")

    try:
        result = await analyze_diff_with_llm(
            file1_name=name1,
            file2_name=name2,
            text1=text1,
            text2=text2,
        )
        result["file1"] = name1
        result["file2"] = name2

        total = result.get("total_diffs", 0)
        similarity = result.get("similarity", 0)
        _log_query("file_diff", f"对比 {name1} vs {name2}", f"{total}处差异, 相似度{similarity}%")

        return ToolResult(
            success=True,
            summary=f"对比完成，发现{total}处差异，相似度{similarity}%",
            data={"type": "diff_report", "report": result}
        )
    except Exception as e:
        logger.error(f"文本对比失败: {e}")
        return ToolResult(success=False, summary=f"文本对比失败: {str(e)}")


# ========== QueryLog 记录工具 ==========

def _log_query(query_type: str, query_text: str, result_summary: str = "", user_id: int = None):
    """记录查询日志到QueryLog表，供热点统计使用"""
    try:
        db = SessionLocal()
        log = QueryLog(
            user_id=user_id,
            query_type=query_type,
            query_text=query_text[:500],
            result_summary=result_summary[:500] if result_summary else None,
        )
        db.add(log)
        db.commit()
        db.close()
    except Exception as e:
        logger.debug(f"QueryLog写入失败(非致命): {e}")


# ========== 注册所有工具 ==========

def create_tool_registry() -> ToolRegistry:
    """创建并注册所有工具"""
    registry = ToolRegistry()
    registry.register("search_policy", handle_search_policy)
    registry.register("check_compliance", handle_check_compliance)
    registry.register("list_templates", handle_list_templates)
    registry.register("generate_document", handle_generate_document)
    registry.register("export_file", handle_export_file)
    registry.register("compare_texts", handle_compare_texts)
    logger.info(f"✅ 已注册 {len(registry.tool_names)} 个Agent工具: {registry.tool_names}")
    return registry
