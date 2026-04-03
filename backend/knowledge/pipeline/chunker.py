"""文档切片器 - 将文档切分为语义块"""
import re
from typing import List, Dict

def chunk_document(text: str, doc_title: str = "") -> List[Dict[str, str]]:
    """
    将文档文本切分为语义块
    
    Args:
        text: 文档文本
        doc_title: 文档标题
        
    Returns:
        切片列表，每个切片包含 title, content, hierarchy
    """
    if not text.strip():
        return []
    
    chunks = []
    
    # 按段落分割
    paragraphs = [p.strip() for p in text.split('\n\n') if p.strip()]
    
    # 检测标题层级
    current_section = doc_title or "文档内容"
    current_hierarchy = ""
    
    for para in paragraphs:
        # 检测是否为标题（一、二、三 或 1. 2. 3. 或 第一章、第二节等）
        title_match = re.match(r'^([一二三四五六七八九十]+[、.]|第[一二三四五六七八九十]+[章节条款]|[\d]+[、.])\s*(.+)$', para)
        
        if title_match:
            # 这是一个标题
            current_section = para
            current_hierarchy = title_match.group(1).strip('、.')
        elif len(para) > 20:  # 只保留有实质内容的段落
            # 这是内容段落
            chunks.append({
                'title': current_section,
                'content': para,
                'hierarchy': current_hierarchy
            })
    
    # 如果没有检测到任何结构，按固定长度切分
    if not chunks:
        chunk_size = 500
        for i in range(0, len(text), chunk_size):
            chunk_text = text[i:i+chunk_size]
            if chunk_text.strip():
                chunks.append({
                    'title': doc_title or f"片段{i//chunk_size + 1}",
                    'content': chunk_text.strip(),
                    'hierarchy': str(i//chunk_size + 1)
                })
    
    return chunks
