"""数据初始化模块 — 首次部署时自动导入预置数据（模板等）
注意：政策知识库数据由总管理系统统一管理，不在本地初始化。
"""
import json
from pathlib import Path

from loguru import logger
from sqlalchemy.orm import Session

from app.models.database import SessionLocal
from app.models.template import Template


# init_data.json 的路径（与 backend/ 目录同级）
INIT_DATA_FILE = Path(__file__).parent.parent / "init_data.json"


def load_init_data() -> dict:
    """加载初始化数据文件"""
    if not INIT_DATA_FILE.exists():
        logger.info(f"未找到初始化数据文件: {INIT_DATA_FILE}，跳过数据导入")
        return {}
    with open(INIT_DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def init_templates(db: Session, templates_data: list):
    """导入模板数据（覆盖默认模板）"""
    if db.query(Template).count() > 0:
        logger.info("模板表已有数据，跳过导入")
        return
    count = 0
    for t in templates_data:
        template = Template(
            name=t.get("name"),
            category=t.get("category"),
            description=t.get("description"),
            required_fields=t.get("required_fields"),
            optional_fields=t.get("optional_fields"),
            body_skeleton=t.get("body_skeleton"),
            is_active=t.get("is_active", True),
        )
        db.add(template)
        count += 1
    db.commit()
    logger.info(f"✅ 已导入 {count} 个文档模板")


def run_data_init():
    """
    执行数据初始化（启动时调用）。
    仅在数据库为空时导入，已有数据则跳过。
    政策知识库数据由总管理系统统一管理，不在本地初始化。
    """
    data = load_init_data()
    if not data:
        return

    db = SessionLocal()
    try:
        # 导入模板（先于默认模板，避免重复）
        if data.get("templates"):
            init_templates(db, data["templates"])
    except Exception as e:
        logger.error(f"数据初始化失败: {e}")
        db.rollback()
    finally:
        db.close()
