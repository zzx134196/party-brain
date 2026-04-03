"""NL2SQL模块 - 自然语言转SQL查询"""
import re
from typing import Dict, Any, List, Optional

from loguru import logger
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.llm import llm_service


# 党员表Schema描述
MEMBER_SCHEMA = """
数据库表名：members
字段列表：
- id: INT, 主键
- name: VARCHAR(50), 姓名
- gender: VARCHAR(10), 性别（男/女）
- birth_date: DATE, 出生日期
- department: VARCHAR(100), 所属部门/支部
- position: VARCHAR(100), 职务
- education: VARCHAR(50), 学历（博士/硕士/本科/大专/高中等）
- phone: VARCHAR(20), 联系电话
- join_party_date: DATE, 入党日期
- become_full_date: DATE, 转正日期（预备党员此字段为NULL）
- status: VARCHAR(20), 党员状态（正式/预备/转出）
- ethnicity: VARCHAR(20), 民族
- remark: VARCHAR(500), 备注
"""

NL2SQL_PROMPT = """你是一个SQL生成助手。根据用户的自然语言查询，生成对应的SQLite SQL语句。

{schema}

规则：
1. 只能生成SELECT语句，禁止INSERT/UPDATE/DELETE
2. 年龄计算使用SQLite语法: CAST((julianday('now') - julianday(birth_date)) / 365.25 AS INTEGER)
3. 当前日期使用: date('now')
4. 查询电话号码时不需要脱敏，脱敏由应用层处理
5. 如果用户查询涉及"预备党员"，条件为 status='预备'
6. 如果用户查询涉及"转正"，需要看 become_full_date 字段
7. 模糊查询姓名时使用LIKE
8. 统计分析时尽量用中文别名（AS）方便展示

请只输出JSON格式：
{{"sql": "SELECT ...", "description": "查询描述", "is_stats": false}}

is_stats为true表示这是一个统计分析类查询（含GROUP BY / COUNT / SUM等聚合函数）

用户查询：{query}"""


def validate_sql(sql: str) -> bool:
    """SQL安全校验 - 只允许SELECT"""
    sql_upper = sql.strip().upper()
    # 禁止危险关键词
    forbidden = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE", "TRUNCATE", "EXEC", "EXECUTE"]
    for keyword in forbidden:
        if re.search(rf'\b{keyword}\b', sql_upper):
            logger.warning(f"SQL安全校验失败，包含禁止关键词: {keyword}")
            return False
    # 必须以SELECT开头
    if not sql_upper.startswith("SELECT"):
        logger.warning(f"SQL安全校验失败，非SELECT语句")
        return False
    return True


def desensitize_phone(phone: str) -> str:
    """手机号脱敏"""
    if phone and len(phone) >= 7:
        return phone[:3] + "****" + phone[-4:]
    return phone or ""


async def natural_language_to_sql(query: str) -> Dict[str, Any]:
    """自然语言转SQL"""
    messages = [
        {"role": "system", "content": "你是一个精确的SQL生成助手，只输出JSON。"},
        {"role": "user", "content": NL2SQL_PROMPT.format(schema=MEMBER_SCHEMA, query=query)},
    ]
    result = await llm_service.chat_json(messages, temperature=0.1)

    if "error" in result:
        return {"success": False, "error": "SQL生成失败", "raw": result.get("raw", "")}

    sql = result.get("sql", "")
    if not validate_sql(sql):
        return {"success": False, "error": "生成的SQL未通过安全校验"}

    return {
        "success": True,
        "sql": sql,
        "description": result.get("description", ""),
        "is_stats": result.get("is_stats", False),
    }


def execute_query(db: Session, sql: str, desensitize: bool = True) -> Dict[str, Any]:
    """执行SQL查询并返回结果"""
    try:
        result = db.execute(text(sql))
        columns = list(result.keys())
        rows = [dict(zip(columns, row)) for row in result.fetchall()]

        # 脱敏处理
        if desensitize:
            for row in rows:
                if "phone" in row and row["phone"]:
                    row["phone"] = desensitize_phone(str(row["phone"]))
                if "id_card" in row and row["id_card"]:
                    row["id_card"] = row["id_card"][:6] + "********" + row["id_card"][-4:] if len(str(row["id_card"])) > 14 else "***"

        return {"success": True, "columns": columns, "rows": rows, "count": len(rows)}
    except Exception as e:
        logger.error(f"SQL执行失败: {e}")
        return {"success": False, "error": f"查询执行失败: {str(e)}"}
