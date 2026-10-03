import json
import re
import sys
import time
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.llm_agents import adjudicate_errors
from agents.pipeline import run_check
from evaluation.eval_against_key import evaluate, load_key_items
from tools.checks import TYPE_NAMES, extract_claims, run_checks_from_claims
from tools.docx_reader import read_draft
from tools.llm_client import LLMClient
from tools.logger import AuditLogger
from tools.pdf_facts import load_facts

PROMPTS_DIR = ROOT / "prompts"
PDF = ROOT / "data" / "samples" / "年报_贵州茅台2024.pdf"
PRICE = ROOT / "data" / "samples" / "price_snapshot.json"
OUT = ROOT / "data" / "output"
CMP_DIR = OUT / "comparison"

CASES = [
    {
        "name": "草稿01",
        "draft": ROOT / "data" / "samples" / "研报草稿_贵州茅台.docx",
        "key": ROOT / "test" / "02_错误注入答案标注册_评测用.docx",
    },
    {
        "name": "草稿02",
        "draft": ROOT / "data" / "samples" / "研报草稿_贵州茅台_变体.docx",
        "key": ROOT / "data" / "benchmark" / "draft_02_key.json",
    },
]

TYPE_BY_KEYWORD = [
    ("数值", "E01"), ("计算", "E02"), ("单位", "E03"), ("期间", "E04"), ("口径", "E05"),
    ("方向", "E06"), ("引用", "E07"), ("主体", "E08"), ("遗漏", "E09"), ("表述", "E10"), ("严谨", "E10"),
]

TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "get_fact",
            "description": "查询公司年报中的财务事实（数值、单位、同比、来源页码与表名）",
            "parameters": {
                "type": "object",
                "properties": {
                    "metric": {"type": "string", "description": "指标名，如 营业收入/营业总收入/归母净利润/扣非归母净利润/总资产/管理费用/销售费用/基本每股收益/PE"},
                    "period": {"type": "string", "description": "期间，如 2024/2023/2025"},
                },
                "required": ["metric"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calc",
            "description": "执行确定性算术计算（同比增速、毛利率、市盈率等）",
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string", "description": "纯数字表达式，如 (1342/68.64)"}},
                "required": ["expression"],
            },
        },
    },
]


def _prompt(name: str, version: str = "v1") -> str:
    return (PROMPTS_DIR / f"{name}.{version}.txt").read_text(encoding="utf-8")


def _page_texts(pdf_path: Path) -> list[str]:
    doc = pymupdf.open(str(pdf_path))
    texts = [" ".join(page.get_text().split()) for page in doc]
    doc.close()
    return texts


def _draft_text(draft_path: Path) -> str:
    blocks = read_draft(draft_path)
    return "\n".join(f'[{b["id"]}] {b["text"]}' for b in blocks if b["type"] == "paragraph")


def _normalize(raw) -> list[dict]:
    errors = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        et = str(item.get("error_type") or "").strip().upper()
        code = et if re.fullmatch(r"E\d{2}", et) else None
        if code is None and "/" in et:
            first = et.split("/")[0].strip()
            if re.fullmatch(r"E\d{2}", first):
                code = first
        if code is None:
            for kw, c in TYPE_BY_KEYWORD:
                if kw in et or kw in str(item.get("error_type") or ""):
                    code = c
                    break
        if code not in TYPE_NAMES:
            continue
        wrong = str(item.get("wrong_text") or item.get("wrong") or "")
        correct = str(item.get("correct_text") or item.get("correct") or "")
        correction = str(item.get("correction") or (f"修改为：{correct}" if correct else "按年报数据修改"))
        evidence = str(item.get("evidence") or "")
        page = None
        m = re.search(r"第\s*(\d+)\s*页|P\s*(\d+)", evidence)
        if m:
            page = int(m.group(1) or m.group(2))
        loc = str(item.get("location") or item.get("claim") or "LLM")
        errors.append({
            "claim_id": "",
            "error_type": code,
            "error_type_cn": TYPE_NAMES[code],
            "severity": item.get("severity") if item.get("severity") in ("高", "中", "低") else "中",
            "location": loc,
            "locations": [loc],
            "wrong_text": wrong,
            "correct_text": correct,
            "correction": correction,
            "evidence": evidence,
            "source_reference": {"file": PDF.name, "page": page, "table": "", "row": ""},
            "confidence": 0.6,
        })
    for i, e in enumerate(errors, 1):
        e["claim_id"] = f"M{i:03d}"
    return errors


def mode_a_pure_llm(draft_path: Path, llm: LLMClient, logger: AuditLogger) -> list[dict]:
    pages = _page_texts(PDF)
    annual = {str(p): pages[p - 1][:3500] for p in (5, 8, 21, 63)}
    payload = json.dumps({"draft": _draft_text(draft_path), "annual_report_pages": annual}, ensure_ascii=False)
    messages = [
        {"role": "system", "content": _prompt("mode_a_pure_llm")},
        {"role": "user", "content": payload},
    ]
    data, out = llm.chat_json(messages, prompt_version="mode_a_pure_llm.v1", max_tokens=16384)
    logger.log("mode_a_pure_llm", tool="llm", input={"draft": draft_path.name},
               output={"errors_raw": len(data) if isinstance(data, list) else 0,
                       "cached": out.get("cached"), "usage": out.get("usage")},
               prompt_version="mode_a_pure_llm.v1")
    return _normalize(data)


def _execute_tool(name: str, args: dict, facts: dict) -> dict:
    if name == "get_fact":
        metric = str(args.get("metric") or "")
        period = str(args.get("period") or "2024")
        fact = facts["items"].get(f"{metric}|{period}") or facts["items"].get(f"{metric}|2024")
        if not fact:
            return {"error": f"未找到指标 {metric} 期间 {period}"}
        return {
            "metric": fact["metric"], "period": fact["period"], "value": fact["value"],
            "unit": fact["unit"], "growth": fact.get("growth"),
            "sources": fact.get("sources", [])[:2], "excerpt": fact.get("excerpt", "")[:160],
        }
    if name == "calc":
        expr = str(args.get("expression") or "").strip()
        if not re.fullmatch(r"[0-9+\-*/(). %]+", expr):
            return {"error": "表达式包含不允许的字符"}
        try:
            return {"expression": expr, "result": eval(expr, {"__builtins__": {}}, {})}
        except Exception as exc:
            return {"error": str(exc)}
    return {"error": f"未知工具 {name}"}


def mode_b_llm_tools(draft_path: Path, llm: LLMClient, logger: AuditLogger, facts: dict) -> list[dict]:
    metrics = sorted({k.split("|")[0] for k in facts["items"]})
    payload = json.dumps({"draft": _draft_text(draft_path), "available_metrics": metrics}, ensure_ascii=False)
    messages = [
        {"role": "system", "content": _prompt("mode_b_tools")},
        {"role": "user", "content": payload},
    ]
    tool_rounds = 0
    for _ in range(6):
        out = llm.chat(messages, tools=TOOL_SPECS, max_tokens=8192, prompt_version="mode_b_llm_tools.v1")
        calls = out.get("tool_calls")
        if not calls:
            break
        tool_rounds += 1
        messages.append({"role": "assistant", "content": out.get("content") or "", "tool_calls": calls})
        for tc in calls:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            result = _execute_tool(name, args, facts)
            messages.append({"role": "tool", "tool_call_id": tc.get("id", ""),
                             "content": json.dumps(result, ensure_ascii=False)})
    messages.append({"role": "user", "content": "请基于以上核查过程输出最终 JSON 错误数组（location/error_type/wrong_text/correct_text/evidence/correction），只输出JSON。"})
    data, out = llm.chat_json(messages, prompt_version="mode_b_llm_tools.v1", max_tokens=16384)
    logger.log("mode_b_llm_tools", tool="llm", input={"draft": draft_path.name},
               output={"errors_raw": len(data) if isinstance(data, list) else 0, "tool_rounds": tool_rounds,
                       "cached": out.get("cached"), "usage": out.get("usage")},
               prompt_version="mode_b_llm_tools.v1")
    return _normalize(data)


def _delta(before: dict, after: dict) -> dict:
    return {k: after.get(k, 0) - before.get(k, 0) for k in ("calls", "cache_hits", "prompt_tokens", "completion_tokens")}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    CMP_DIR.mkdir(parents=True, exist_ok=True)
    llm = LLMClient()
    logger = AuditLogger()
    results = []

    for case in CASES:
        if not Path(case["key"]).exists():
            print(f"[SKIP] {case['name']}：未提供标准答案 {Path(case['key']).name}，跳过该案例")
            continue
        facts = load_facts(PDF, PRICE)
        key_items = load_key_items(case["key"])
        runs = []

        before = dict(llm.stats)
        t0 = time.time()
        try:
            errors = mode_a_pure_llm(case["draft"], llm, logger)
            status = "OK"
        except Exception as exc:
            errors, status = [], f"FAIL: {exc}"
        runs.append({"mode": "A 纯LLM", "errors": errors, "duration": round(time.time() - t0, 1),
                     "usage": _delta(before, llm.stats), "status": status})

        before = dict(llm.stats)
        t0 = time.time()
        try:
            blocks = read_draft(case["draft"])
            candidates = run_checks_from_claims(extract_claims(blocks), blocks, facts)
            errors_b, _ = adjudicate_errors(candidates, llm, logger)
            status = "OK"
        except Exception as exc:
            errors_b, status = [], f"FAIL: {exc}"
        runs.append({"mode": "B LLM+工具", "errors": errors_b, "duration": round(time.time() - t0, 1),
                     "usage": _delta(before, llm.stats), "status": status})

        t0 = time.time()
        out_c = CMP_DIR / f"{case['name']}_modeC"
        try:
            res = run_check(case["draft"], PDF, PRICE, out_c)
            errors_c = res["errors"]
            status = "OK"
            usage_c = dict(res["llm"].get("stats", {}))
        except Exception as exc:
            errors_c, status, usage_c = [], f"FAIL: {exc}", {}
        runs.append({"mode": "C 多智能体+证据链", "errors": errors_c, "duration": round(time.time() - t0, 1),
                     "usage": usage_c, "status": status})

        for run in runs:
            metrics = evaluate(run["errors"], key_items)
            run["metrics"] = metrics
            run["missed"] = [i["id"] + " " + i["type_cn"] for i in metrics["items"] if not i["matched"]]
            (CMP_DIR / f"{case['name']}_{run['mode'][0]}.json").write_text(
                json.dumps({"mode": run["mode"], "status": run["status"], "errors": run["errors"]},
                           ensure_ascii=False, indent=2), encoding="utf-8")
            results.append({"case": case["name"], "mode": run["mode"], "duration": run["duration"],
                            "usage": run["usage"], "status": run["status"], "metrics": metrics,
                            "missed": run["missed"]})

    lines = [
        "# 对比实验：纯LLM vs LLM+工具 vs 多智能体+证据链", "",
        f"- 推理引擎：{llm.model}（temperature=0，结果缓存）",
        "- 测试材料：草稿01（13处植入错误）、草稿02（12处植入错误），均对照标准答案评测",
        "",
        "| 案例 | 模式 | 报出数 | Recall | Precision | F1 | 误报 | 证据定位 | 耗时(s) | 状态 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        m = r["metrics"]
        lines.append(
            f"| {r['case']} | {r['mode']} | {m['system_errors']} | {m['recall']:.0%} | {m['precision']:.0%} | "
            f"{m['f1']:.0%} | {m['fp']} | {m['evidence_accuracy']:.0%} | {r['duration']} | {r['status']} |"
        )
    lines += ["", "## 未命中明细", ""]
    for r in results:
        detail = "全部命中" if not r["missed"] else "漏检 " + "、".join(r["missed"])
        lines.append(f"- {r['case']} / {r['mode']}：{detail}")
    md = "\n".join(lines)
    (OUT / "comparison.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"\n输出目录：{CMP_DIR}")


if __name__ == "__main__":
    main()
