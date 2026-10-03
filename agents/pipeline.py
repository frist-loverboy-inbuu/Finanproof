import csv
import json
import time
from pathlib import Path

from agents.llm_agents import adjudicate_errors, extract_claims_llm, generate_summary, merge_claims
from tools.checks import extract_claims, run_checks_from_claims
from tools.docx_reader import read_draft
from tools.llm_client import CACHE_PATH, LLMClient
from tools.logger import AuditLogger
from tools.pdf_facts import load_facts

ROOT = Path(__file__).resolve().parents[1]

CSV_FIELDS = ["claim_id", "error_type", "error_type_cn", "severity", "location",
              "wrong_text", "correct_text", "correction", "evidence", "source_page", "source_table", "confidence"]


def _stats(errors: list[dict]) -> dict:
    by_sev = {"高": 0, "中": 0, "低": 0}
    by_type: dict[str, int] = {}
    for e in errors:
        by_sev[e["severity"]] = by_sev.get(e["severity"], 0) + 1
        by_type[e["error_type"]] = by_type.get(e["error_type"], 0) + 1
    return {"total": len(errors), "by_severity": by_sev, "by_type": by_type}


def _template_summary(errors: list[dict], stats: dict) -> str:
    if not errors:
        return "本次核查未发现错误。"
    highs = stats["by_severity"].get("高", 0)
    mids = stats["by_severity"].get("中", 0)
    types = "、".join(f"{k} {v}条" for k, v in sorted(stats["by_type"].items()))
    return (f"本次核查共发现 {len(errors)} 条问题（高风险 {highs} 条、中风险 {mids} 条），"
            f"涉及类型：{types}。建议按错误清单逐条修改并复核后发布。")


def run_check(draft_path, pdf_path, price_path=None, out_dir=None, log_dir=None, use_llm: bool = True) -> dict:
    t0 = time.time()
    draft_path = Path(draft_path)
    pdf_path = Path(pdf_path)
    out_dir = Path(out_dir) if out_dir else ROOT / "data" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    logger = AuditLogger(log_dir or ROOT / "logs")
    logger.log("start", tool="pipeline",
               input={"draft": draft_path.name, "pdf": pdf_path.name, "price": str(price_path), "use_llm": use_llm},
               tool_version="v2.0")

    blocks = read_draft(draft_path)
    logger.log("read_draft", tool="docx_reader",
               output={"blocks": len(blocks),
                       "paragraphs": sum(1 for b in blocks if b["type"] == "paragraph"),
                       "tables": sum(1 for b in blocks if b["type"] == "table")},
               tool_version="v1.0")

    facts = load_facts(pdf_path, price_path)
    logger.log("extract_facts", tool="pdf_facts",
               output={"facts": len(facts["items"]), "pages": facts["meta"]["pages"]},
               tool_version="v1.0")

    llm = LLMClient() if use_llm else None
    llm_enabled = bool(llm and (llm.available or CACHE_PATH.exists()))
    llm_error = None
    if llm:
        logger.log("llm_mode", tool="llm",
                   output={"enabled": llm_enabled, "model": llm.model, "api_available": llm.available,
                           "cache_exists": CACHE_PATH.exists()},
                   tool_version="v1.0")

    rule_claims = extract_claims(blocks)
    llm_claims: list[dict] = []
    if llm_enabled:
        try:
            llm_claims = extract_claims_llm(blocks, facts, llm, logger)
        except Exception as exc:
            llm_error = f"claim_extractor: {exc}"
            logger.log("llm_extract_claims_failed", tool="llm", output={"error": str(exc)})
    claims = merge_claims(rule_claims, llm_claims)
    logger.log("extract_claims", tool="checks",
               output={"rule": len(rule_claims), "llm": len(llm_claims), "merged": len(claims)},
               tool_version="v1.0")

    candidates = run_checks_from_claims(claims, blocks, facts)
    logger.log("run_checks", tool="checks", output={"candidates": len(candidates)}, tool_version="v1.0")

    adj_stats = {"confirmed": 0, "rejected": 0, "no_verdict": 0}
    if llm_enabled and candidates:
        try:
            errors, adj_stats = adjudicate_errors(candidates, llm, logger)
        except Exception as exc:
            llm_error = (llm_error + "; " if llm_error else "") + f"adjudicator: {exc}"
            errors = candidates
            logger.log("llm_adjudicate_failed", tool="llm", output={"error": str(exc)})
    else:
        errors = candidates

    for i, e in enumerate(errors, 1):
        e["claim_id"] = f"F{i:03d}"
        e.pop("dedupe_key", None)

    stats = _stats(errors)

    summary = ""
    if llm_enabled and errors:
        try:
            summary = generate_summary(errors, llm, logger)
        except Exception as exc:
            llm_error = (llm_error + "; " if llm_error else "") + f"summary: {exc}"
            logger.log("llm_summary_failed", tool="llm", output={"error": str(exc)})
    if not summary:
        summary = _template_summary(errors, stats)

    duration = round(time.time() - t0, 2)
    llm_info = {
        "enabled": llm_enabled,
        "model": llm.model if llm else None,
        "stats": llm.stats if llm else {},
        "candidates": len(candidates),
        "adjudication": adj_stats,
        "error": llm_error,
        "cache_path": str(CACHE_PATH),
    }
    result = {
        "run_id": logger.run_id,
        "duration_s": duration,
        "draft": draft_path.name,
        "pdf": pdf_path.name,
        "stats": stats,
        "summary": summary,
        "llm": llm_info,
        "errors": errors,
        "facts": facts,
        "blocks": blocks,
        "log_path": str(logger.path),
        "outputs": {},
    }

    errors_json = out_dir / "errors.json"
    errors_json.write_text(json.dumps(
        {"run_id": result["run_id"], "draft": result["draft"], "pdf": result["pdf"],
         "stats": stats, "summary": summary, "llm": llm_info, "errors": errors},
        ensure_ascii=False, indent=2), encoding="utf-8")

    errors_csv = out_dir / "errors.csv"
    with errors_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for e in errors:
            row = dict(e)
            row["source_page"] = e["source_reference"].get("page")
            row["source_table"] = e["source_reference"].get("table")
            writer.writerow(row)

    report_md = out_dir / "report.md"
    lines = [
        "# Finanproof 核查报告", "",
        "## 核查总结", "", summary, "",
        f"- 运行ID：{result['run_id']}",
        f"- 研报草稿：{result['draft']}",
        f"- 原始材料：{result['pdf']}",
        f"- 处理时间：{duration} 秒",
        f"- 发现错误：{stats['total']} 条（高 {stats['by_severity'].get('高', 0)} / 中 {stats['by_severity'].get('中', 0)} / 低 {stats['by_severity'].get('低', 0)}）",
        f"- 推理引擎：{llm_info['model'] or '未启用'}（候选 {llm_info['candidates']} 条 → 确认 {stats['total']} 条）",
        "",
        "## 错误清单", "",
        "| 编号 | 类型 | 严重度 | 位置 | 错误原文 | 正确值 | 修改建议 | 证据来源 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for e in errors:
        src = e["source_reference"]
        loc = f"第{src['page']}页{src.get('table', '')}" if src.get("page") else e["evidence"][:40]
        row = [e["claim_id"], f"{e['error_type']} {e['error_type_cn']}", e["severity"],
               "、".join(e["locations"]), e["wrong_text"], e["correct_text"], e["correction"], loc]
        lines.append("| " + " | ".join(str(c).replace("|", "｜") for c in row) + " |")
    lines += ["", "## 审计日志", "", f"完整运行日志：`{result['log_path']}`"]
    report_md.write_text("\n".join(lines), encoding="utf-8")

    result["outputs"] = {"json": str(errors_json), "csv": str(errors_csv), "report": str(report_md)}
    logger.log("write_outputs", tool="pipeline", output=result["outputs"], tool_version="v2.0")
    return result
