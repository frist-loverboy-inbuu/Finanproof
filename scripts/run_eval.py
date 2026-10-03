import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evaluation.eval_against_key import eval_against_key, to_markdown


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Finanproof 评测：对照错误注入标准答案")
    ap.add_argument("--errors", default=str(ROOT / "data" / "output" / "errors.json"))
    ap.add_argument("--key", default=str(ROOT / "test" / "02_错误注入答案标注册_评测用.docx"))
    ap.add_argument("--out", default=str(ROOT / "data" / "output" / "evaluation.md"))
    args = ap.parse_args()

    data = json.loads(Path(args.errors).read_text(encoding="utf-8"))
    metrics = eval_against_key(data["errors"], args.key)
    md = to_markdown(metrics)
    Path(args.out).write_text(md, encoding="utf-8")
    print(md)
    print(f"\n评测报告已保存: {args.out}")


if __name__ == "__main__":
    main()
