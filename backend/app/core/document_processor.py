"""文档处理模块 - 读取文档内容并切片"""
import os
import re
import json
from typing import List, Dict, Tuple


def extract_text_from_file(file_path: str) -> str:
    """从文件中提取纯文本，支持 pdf / docx / doc / txt"""
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        return _read_pdf(file_path)
    elif ext in (".docx",):
        return _read_docx(file_path)
    elif ext in (".doc", ".wps"):
        return _read_doc_fallback(file_path)
    else:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()


def _read_pdf(path: str) -> str:
    try:
        import pdfplumber
        text_parts = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    text_parts.append(t)
        return "\n".join(text_parts)
    except ImportError:
        pass
    try:
        import PyPDF2
        text_parts = []
        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                t = page.extract_text()
                if t:
                    text_parts.append(t)
        return "\n".join(text_parts)
    except Exception:
        return ""


def _read_docx(path: str) -> str:
    try:
        from docx import Document
        doc = Document(path)
        return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    except Exception:
        return ""


def _read_doc_fallback(path: str) -> str:
    """尝试用 antiword 或 python-docx 读取旧版 doc"""
    try:
        import subprocess
        result = subprocess.run(["antiword", path], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return result.stdout
    except Exception:
        pass
    return _read_docx(path)


# ─── 切片逻辑 ─────────────────────────────────────────────────────────────────

_HEADING_RE = re.compile(
    r"^(?:"
    r"第[一二三四五六七八九十百]+[章节条款部分]"      # 第一章、第二节
    r"|[一二三四五六七八九十百]+[、]"             # 一、 二、
    r")"
)

_MAX_CHUNK = 800   # 单个切片最大字符数
_MIN_CHUNK = 50    # 低于此长度的段落合并到上一段


def split_into_chunks(text: str, filename: str, department: str = "") -> List[Dict]:
    """
    将文本切分为带标题层级的切片列表。

    返回格式：
    [{"text": ..., "filename": ..., "department": ..., "metadata": json_str}, ...]
    """
    lines = [l.rstrip() for l in text.splitlines()]
    chunks: List[Dict] = []

    current_heading = ""
    current_lines: List[str] = []

    def flush(heading: str, lines_buf: List[str]):
        content = "\n".join(lines_buf).strip()
        if not content or len(content) < _MIN_CHUNK:
            return
        # 若内容过长，按句子进一步切分
        for sub in _split_long_text(content, _MAX_CHUNK):
            # 【重要修复】必须将上下文(标题)拼接到正文头部，防止嵌入(Embedding)时发生语义丢失
            chunk_text = f"{heading}\n{sub}" if heading else sub
            meta = json.dumps({"title": heading, "hierarchy": heading}, ensure_ascii=False)
            chunks.append({
                "text": chunk_text,
                "filename": filename,
                "department": department,
                "metadata": meta,
            })

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _HEADING_RE.match(stripped) and len(stripped) <= 60:
            flush(current_heading, current_lines)
            current_heading = stripped
            current_lines = []
        else:
            current_lines.append(stripped)

    flush(current_heading, current_lines)

    # 如果没有识别到任何标题（纯段落文档），按段落切
    if not chunks:
        for sub in _split_long_text(text.strip(), _MAX_CHUNK):
            if len(sub) < _MIN_CHUNK:
                continue
            meta = json.dumps({"title": filename, "hierarchy": ""}, ensure_ascii=False)
            chunks.append({
                "text": sub,
                "filename": filename,
                "department": department,
                "metadata": meta,
            })

    return chunks


def _split_long_text(text: str, max_len: int, overlap_len: int = 150) -> List[str]:
    """把超长段落按句子边界切分，支持滑动窗口重叠(Overlap)"""
    if len(text) <= max_len:
        return [text]
    # 清理分词产生的空字符串
    sentences = [s for s in re.split(r"(?<=[。！？；\n])", text) if s]
    parts: List[str] = []
    
    buf = []
    current_length = 0
    
    for sent in sentences:
        if current_length + len(sent) > max_len and buf:
            parts.append("".join(buf).strip())
            
            # 建立 Overlap
            overlap_buf = []
            curr_overlap = 0
            for prev_sent in reversed(buf):
                # 防止重叠内容导致新块直接超过 max_len
                if curr_overlap + len(prev_sent) > overlap_len or curr_overlap + len(prev_sent) + len(sent) > max_len:
                    break
                overlap_buf.insert(0, prev_sent)
                curr_overlap += len(prev_sent)
                
            buf = overlap_buf + [sent]
            current_length = curr_overlap + len(sent)
        else:
            buf.append(sent)
            current_length += len(sent)
            
    if buf:
        parts.append("".join(buf).strip())
        
    return parts or [text[:max_len]]
