"""智慧党建助手 - 主应用入口"""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.config import settings
from app.models.database import engine, Base, SessionLocal
from app.models.user import User
from app.models.conversation import Conversation, Message
from app.models.template import Template, GeneratedDocument
from app.models.policy import QueryLog
from app.models.system_config import SystemConfig
# get_password_hash 保留用于init_default_admin（确保至少有一个管理员兜底）
from app.core.auth import get_password_hash

# API路由
from app.api.auth import router as auth_router
from app.api.chat_agent import router as chat_router
from app.api.template import router as template_router
from app.api.policy import router as policy_router
from app.api.settings import router as settings_router
from app.api.export import router as export_router
from app.api.diff import router as diff_router


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="面向党务工作的AI智能助手",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # 生产环境应限制
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 注册路由
    app.include_router(auth_router)
    app.include_router(chat_router)
    app.include_router(template_router)
    app.include_router(policy_router)
    app.include_router(settings_router)
    app.include_router(export_router)
    app.include_router(diff_router)

    @app.on_event("startup")
    async def startup():
        logger.info(f"🚀 {settings.APP_NAME} v{settings.APP_VERSION} 启动中...")

        # 创建上传和导出目录
        os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
        os.makedirs(settings.EXPORT_DIR, exist_ok=True)

        # 创建数据库表
        Base.metadata.create_all(bind=engine)
        logger.info("✅ 数据库表已就绪")

        # 初始化默认管理员账户
        init_default_admin()

        # 导入预置数据（党员、模板、政策切片等，仅空库时执行）
        from app.init_data import run_data_init
        run_data_init()

        # 如果 init_data 未导入模板，则初始化默认示例模板
        init_default_templates()

        # 从数据库加载运行时配置（持久化的配置覆盖默认值）
        from app.api.settings import load_runtime_config_from_db
        load_runtime_config_from_db()

        logger.info(f"Embedding运行时配置: {settings.embedding_runtime_info}")
        logger.info(f"Milvus运行时配置: {settings.milvus_runtime_info}")

        logger.info(f"✅ {settings.APP_NAME} 启动完成")
        logger.info(f"📖 API文档: http://{settings.HOST}:{settings.PORT}/docs")

    @app.get("/")
    async def root():
        return {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "status": "running",
        }

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


def init_default_admin():
    """初始化默认管理员"""
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            admin = User(
                username="admin",
                hashed_password=get_password_hash("admin123"),
                real_name="系统管理员",
                role="admin",
            )
            db.add(admin)
            db.commit()
            logger.info("✅ 已创建默认管理员: admin / admin123")
    finally:
        db.close()


def init_default_templates():
    """初始化示例模板"""
    db = SessionLocal()
    try:
        import json
        count = db.query(Template).count()
        if count > 0:
            return

        templates = [
            {
                "name": "年度工作计划",
                "category": "计划",
                "description": "年度工作计划模板，包含工作目标、重点任务、时间安排等",
                "required_fields": json.dumps(["年度", "部门名称", "工作目标"], ensure_ascii=False),
                "optional_fields": json.dumps(["重点任务数量", "特殊要求"], ensure_ascii=False),
                "body_skeleton": (
                    "一、总体思路\n"
                    "二、工作目标\n"
                    "三、重点任务\n"
                    "  （一）任务一\n  （二）任务二\n  （三）任务三\n"
                    "四、时间安排\n"
                    "  第一季度：\n  第二季度：\n  第三季度：\n  第四季度：\n"
                    "五、保障措施\n"
                    "六、组织领导"
                ),
            },
            {
                "name": "活动策划方案",
                "category": "方案",
                "description": "各类党建活动策划方案模板",
                "required_fields": json.dumps(["活动主题", "活动时间", "活动地点", "参与人数"], ensure_ascii=False),
                "optional_fields": json.dumps(["活动预算", "特殊要求"], ensure_ascii=False),
                "body_skeleton": (
                    "一、活动背景\n"
                    "二、活动主题\n"
                    "三、活动时间与地点\n"
                    "四、参加人员\n"
                    "五、活动议程\n"
                    "六、工作分工\n"
                    "七、经费预算\n"
                    "八、注意事项"
                ),
            },
            {
                "name": "季度工作总结",
                "category": "总结",
                "description": "季度工作总结报告模板",
                "required_fields": json.dumps(["季度", "部门名称"], ensure_ascii=False),
                "optional_fields": json.dumps(["主要成绩", "存在问题"], ensure_ascii=False),
                "body_skeleton": (
                    "一、本季度工作概述\n"
                    "二、主要工作成绩\n"
                    "  （一）\n  （二）\n  （三）\n"
                    "三、存在的问题和不足\n"
                    "四、下季度工作计划\n"
                    "五、意见和建议"
                ),
            },
            {
                "name": "会议纪要",
                "category": "记录",
                "description": "各类会议纪要模板",
                "required_fields": json.dumps(["会议名称", "会议时间", "会议地点", "主持人"], ensure_ascii=False),
                "optional_fields": json.dumps(["参会人员", "列席人员"], ensure_ascii=False),
                "body_skeleton": (
                    "会议名称：\n"
                    "会议时间：\n"
                    "会议地点：\n"
                    "主 持 人：\n"
                    "参会人员：\n"
                    "记 录 人：\n\n"
                    "一、会议议题\n"
                    "二、会议内容\n"
                    "三、会议决议\n"
                    "四、工作要求"
                ),
            },
            {
                "name": "党员发展方案",
                "category": "方案",
                "description": "年度党员发展工作方案模板",
                "required_fields": json.dumps(["年度", "发展计划人数"], ensure_ascii=False),
                "optional_fields": json.dumps(["重点发展对象", "培养措施"], ensure_ascii=False),
                "body_skeleton": (
                    "一、指导思想\n"
                    "二、发展原则\n"
                    "三、发展计划\n"
                    "四、工作步骤\n"
                    "  （一）入党积极分子培养\n"
                    "  （二）发展对象确定\n"
                    "  （三）预备党员接收\n"
                    "  （四）预备党员转正\n"
                    "五、工作要求\n"
                    "六、组织保障"
                ),
            },
            {
                "name": "述职报告",
                "category": "报告",
                "description": "党员/干部述职报告模板",
                "required_fields": json.dumps(["述职人姓名", "职务", "述职年度"], ensure_ascii=False),
                "optional_fields": json.dumps(["主要业绩", "存在不足"], ensure_ascii=False),
                "body_skeleton": (
                    "一、基本情况\n"
                    "二、履职情况\n"
                    "  （一）政治学习\n"
                    "  （二）业务工作\n"
                    "  （三）廉洁自律\n"
                    "三、主要成绩\n"
                    "四、存在不足\n"
                    "五、改进方向"
                ),
            },
        ]

        for t_data in templates:
            template = Template(**t_data, is_active=True)
            db.add(template)

        db.commit()
        logger.info(f"✅ 已初始化 {len(templates)} 个默认模板")
    finally:
        db.close()


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
