"""按标题层级切块的 markdown 解析器。"""

from __future__ import annotations

import re
from pathlib import Path

from app.domain.knowledge_models import KnowledgeChunk


HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.*)$")
KEYWORD_PATTERN = re.compile(r"[A-Za-z0-9_+\-]{2,}|[\u4e00-\u9fff]{2,}")


def chunk_markdown(markdown_path: Path) -> list[KnowledgeChunk]:
    """把 markdown 切成保留标题路径的知识块。"""
    lines = markdown_path.read_text(encoding="utf-8").splitlines()
    chunks: list[KnowledgeChunk] = []
    heading_stack: list[tuple[int, str]] = []
    buffer: list[str] = []
    buffer_start = 1
    chunk_index = 1

    def flush(end_line: int) -> None:
        """把当前缓冲区内容收束成一个 chunk。"""
        nonlocal buffer, buffer_start, chunk_index
        text = "\n".join(buffer).strip()
        if not text:
            buffer = []
            return
        heading_path = [item[1] for item in heading_stack] or ["Overview"]
        keywords = sorted({match.group(0).lower() for match in KEYWORD_PATTERN.finditer(" ".join(heading_path) + "\n" + text)})
        chunks.append(
            KnowledgeChunk(
                chunk_id=f"chunk-{chunk_index:04d}",
                source_file=str(markdown_path),
                heading_path=heading_path,
                text=text,
                keywords=keywords,
                start_line=buffer_start,
                end_line=end_line,
            )
        )
        chunk_index += 1
        buffer = []

    for line_number, line in enumerate(lines, start=1):
        heading_match = HEADING_PATTERN.match(line)
        if heading_match:
            flush(line_number - 1)
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, title))
            buffer_start = line_number
            continue

        if not buffer and line.strip():
            buffer_start = line_number
        buffer.append(line)

    flush(len(lines))
    return chunks
