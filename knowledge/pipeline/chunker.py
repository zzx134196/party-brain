"""文档切片模块 - 按章节/条款级别切片"""
import re
from typing import List, Dict
from loguru import logger


# 常见的章节/条款标题模式
SECTION_PATTERNS = [
    r'^第[一二三四五六七八九十百]+章\s',     # 第一章
    r'^第[一二三四五六七八九十百]+节\s',     # 第一节
    r'^第[一二三四五六七八九十百\d]+条\s',   # 第一条 / 第1条
    r'^[一二三四五六七八九十]+[、．.]\s*',   # 一、/ 二、
    r'^（[一二三四五六七八九十]+）',          # （一）
    r'^\d+[、．.]\s',                        # 1、/ 1.
    r'^第[一二三四五六七八九十\d]+款\s',     # 第一款
]


def chunk_document(text: str, doc_title: str = "", max_chunk_size: int = 800, overlap: int = 100) -> List[Dict]:
    """
    将文档文本切分为语义完整的切片

    策略：
    1. 先按章节/条款标题分割
    2. 如果某个切片过长，再按段落分割
    3. 保留层级关系信息
    """
    if not text.strip():
        return []

    lines = text.split("\n")
    chunks = []
    current_chunk = []
    current_hierarchy = []
    current_title = ""

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current_chunk:
                current_chunk.append("")
            continue

        # 检查是否是章节标题
        is_section_title = False
        for pattern in SECTION_PATTERNS:
            if re.match(pattern, stripped):
                is_section_title = True
                break

        if is_section_title:
            # 保存之前的切片
            if current_chunk:
                chunk_text = "\n".join(current_chunk).strip()
                if chunk_text:
                    chunks.append({
                        "title": current_title,
                        "content": chunk_text,
                        "hierarchy": " > ".join(current_hierarchy) if current_hierarchy else "",
                        "source": doc_title,
                    })

            # 更新层级
            current_hierarchy = update_hierarchy(current_hierarchy, stripped)
            current_title = stripped
            current_chunk = [stripped]
        else:
            current_chunk.append(stripped)

    # 保存最后一个切片
    if current_chunk:
        chunk_text = "\n".join(current_chunk).strip()
        if chunk_text:
            chunks.append({
                "title": current_title,
                "content": chunk_text,
                "hierarchy": " > ".join(current_hierarchy) if current_hierarchy else "",
                "source": doc_title,
            })

    # 对过长的切片进行二次分割
    final_chunks = []
    for chunk in chunks:
        if len(chunk["content"]) > max_chunk_size:
            sub_chunks = split_long_chunk(chunk, max_chunk_size, overlap)
            final_chunks.extend(sub_chunks)
        else:
            final_chunks.append(chunk)

    # 如果没有识别到任何章节标题，按固定长度切片
    if not final_chunks and text.strip():
        final_chunks = fixed_size_chunk(text, doc_title, max_chunk_size, overlap)

    logger.info(f"文档切片完成: '{doc_title}', 共{len(final_chunks)}个切片")
    return final_chunks


def update_hierarchy(hierarchy: list, title: str) -> list:
    """更新层级路径"""
    # 判断标题级别
    level = get_title_level(title)
    # 截断到当前级别
    new_hierarchy = hierarchy[:level]
    new_hierarchy.append(title.strip()[:50])
    return new_hierarchy


def get_title_level(title: str) -> int:
    """判断标题级别"""
    if re.match(r'^第[一二三四五六七八九十百]+章', title):
        return 0
    if re.match(r'^第[一二三四五六七八九十百]+节', title):
        return 1
    if re.match(r'^第[一二三四五六七八九十百\d]+条', title):
        return 2
    if re.match(r'^[一二三四五六七八九十]+[、．.]', title):
        return 1
    if re.match(r'^（[一二三四五六七八九十]+）', title):
        return 2
    if re.match(r'^\d+[、．.]', title):
        return 2
    return 3


def split_long_chunk(chunk: Dict, max_size: int, overlap: int) -> List[Dict]:
    """将过长切片按段落分割"""
    text = chunk["content"]
    paragraphs = text.split("\n\n")

    sub_chunks = []
    current_text = ""

    for para in paragraphs:
        if len(current_text) + len(para) > max_size and current_text:
            sub_chunks.append({
                **chunk,
                "content": current_text.strip(),
                "title": chunk["title"] + f"(续{len(sub_chunks) + 1})" if sub_chunks else chunk["title"],
            })
            # 保留overlap
            current_text = current_text[-overlap:] + "\n\n" + para if overlap else para
        else:
            current_text += ("\n\n" if current_text else "") + para

    if current_text.strip():
        sub_chunks.append({
            **chunk,
            "content": current_text.strip(),
            "title": chunk["title"] + f"(续{len(sub_chunks) + 1})" if sub_chunks else chunk["title"],
        })

    return sub_chunks


def fixed_size_chunk(text: str, doc_title: str, max_size: int, overlap: int) -> List[Dict]:
    """固定长度切片（回退策略）"""
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + max_size, len(text))
        chunk_text = text[start:end]

        # 尽量在句号处断开
        if end < len(text):
            last_period = chunk_text.rfind("。")
            if last_period > max_size // 2:
                end = start + last_period + 1
                chunk_text = text[start:end]

        chunks.append({
            "title": f"片段{len(chunks) + 1}",
            "content": chunk_text.strip(),
            "hierarchy": "",
            "source": doc_title,
        })
        start = end - overlap

    return chunks
