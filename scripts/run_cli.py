import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.pipeline import run_check


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Finanproof 研报核查（命令行）")
    ap.add_argument("--draft", default=str(ROOT / "data" / "samples" / "研报草稿_贵州茅台.docx"))
    ap.add_argument("--pdf", default=str(ROOT / "data" / "samples" / "年报_贵州茅台2024.pdf"))
    ap.add_argument("--price", default=str(ROOT / "data" / "samples" / "price_snapshot.json"))
    ap.add_argument("--out", default=str(ROOT / "data" / "output"))
    args = ap.parse_args()

    result = run_check(args.draft, args.pdf, args.price, args.out)
    print(f"运行ID: {result['run_id']}")
    print(f"处理时间: {result['duration_s']} 秒")
    print(f"发现错误: {result['stats']['total']} 条 "
          f"(高 {result['stats']['by_severity'].get('高', 0)} / 中 {result['stats']['by_severity'].get('中', 0)})")
    print("-" * 100)
    for e in result["errors"]:
        src = e["source_reference"]
        src_txt = f"第{src['page']}页{src.get('table', '')}" if src.get("page") else "-"
        print(f"[{e['claim_id']}] {e['error_type']} {e['error_type_cn']} | {e['severity']} | {'、'.join(e['locations'])} | {src_txt}")
        print(f"    原文: {e['wrong_text'][:80]}")
        print(f"    修改: {e['correction'][:100]}")
    print("-" * 100)
    for name, path in result["outputs"].items():
        print(f"{name}: {path}")
    print(f"日志: {result['log_path']}")


if __name__ == "__main__":
    main()
