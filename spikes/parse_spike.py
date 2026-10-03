import sys
from pathlib import Path

import fitz
import pdfplumber

KEYWORDS = ["合并利润表", "合并资产负债表", "合并现金流量表"]


def locate_statements(pdf_path: Path) -> None:
    doc = fitz.open(pdf_path)
    print(f"[PyMuPDF] {pdf_path.name} 共 {len(doc)} 页")
    for kw in KEYWORDS:
        for i, page in enumerate(doc):
            if kw in page.get_text():
                print(f"[定位] {kw} -> 第 {i + 1} 页")
                break
        else:
            print(f"[定位] {kw} 未找到")
    doc.close()


def dump_tables(pdf_path: Path, max_tables: int = 3) -> None:
    with pdfplumber.open(pdf_path) as pdf:
        found = 0
        for i, page in enumerate(pdf.pages):
            tables = page.extract_tables()
            if not tables:
                continue
            print(f"\n[pdfplumber] 第 {i + 1} 页 发现 {len(tables)} 张表")
            for table in tables:
                n_cols = len(table[0]) if table else 0
                print(f"  行数={len(table)} 列数={n_cols}")
                for row in table[:6]:
                    print("  ", row)
                found += 1
            if found >= max_tables:
                break


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: .venv\\Scripts\\python spikes/parse_spike.py data/raw/xxx.pdf")
        raise SystemExit(1)
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"文件不存在: {path}")
        raise SystemExit(1)
    locate_statements(path)
    dump_tables(path)
