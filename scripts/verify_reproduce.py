import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.pipeline import run_check
from evaluation.eval_against_key import eval_against_key


def _sig(e: dict) -> tuple:
    nums = tuple(sorted(re.findall(r"\d+(?:\.\d+)?", e["correct_text"])))
    return (e["error_type"], nums, tuple(sorted(e["locations"])))


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    result = run_check(
        ROOT / "data" / "samples" / "研报草稿_贵州茅台.docx",
        ROOT / "data" / "samples" / "年报_贵州茅台2024.pdf",
        ROOT / "data" / "samples" / "price_snapshot.json",
        ROOT / "data" / "output",
    )

    expected = json.loads((ROOT / "data" / "expected" / "errors_expected.json").read_text(encoding="utf-8"))
    exp_sigs = [_sig(e) for e in expected["errors"]]
    act_sigs = [_sig(e) for e in result["errors"]]
    if exp_sigs != act_sigs:
        print(f"[FAIL] 输出与基线不一致：基线 {len(exp_sigs)} 条，本次 {len(act_sigs)} 条")
        for s in act_sigs:
            if s not in exp_sigs:
                print("  多余/变化:", s[0], s[1])
        for s in exp_sigs:
            if s not in act_sigs:
                print("  缺失/变化:", s[0], s[1])
        sys.exit(1)
    print(f"[PASS] 复现成功：核查输出与基线完全一致（{len(act_sigs)} 条错误）")

    key = ROOT / "test" / "02_错误注入答案标注册_评测用.docx"
    if key.exists():
        metrics = eval_against_key(result["errors"], key)
        print(
            f"[PASS] 对照标准答案：Recall {metrics['hit']}/{metrics['key_total']}，"
            f"Precision {metrics['precision']:.0%}，F1 {metrics['f1']:.0%}，"
            f"证据定位 {metrics['evidence_accuracy']:.0%}"
        )
        if metrics["recall"] < 1.0 or metrics["precision"] < 1.0:
            print("[FAIL] 指标未达标")
            sys.exit(1)
    print(f"复现验证完成。运行ID：{result['run_id']}；输出：data/output；日志：{result['log_path']}")


if __name__ == "__main__":
    main()
