from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph


def read_draft(path: str | Path) -> list[dict]:
    doc = Document(str(path))
    blocks: list[dict] = []
    pi = 0
    ti = 0
    for item in doc.iter_inner_content():
        if isinstance(item, Paragraph):
            text = item.text.strip()
            if text:
                blocks.append({"id": f"P{pi}", "type": "paragraph", "text": text})
            pi += 1
        elif isinstance(item, Table):
            rows = [[c.text.strip() for c in row.cells] for row in item.rows]
            blocks.append({"id": f"T{ti}", "type": "table", "rows": rows})
            ti += 1
    return blocks
