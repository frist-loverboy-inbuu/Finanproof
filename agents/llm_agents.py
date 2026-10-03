import json
from pathlib import Path

from tools.checks import TYPE_NAMES

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"

ALLOWED_METRICS = {
    "营业收入", "营业总收入", "归母净利润", "扣非归母净利润", "归母净资产", "总资产",
    "经营现金流净额", "基本每股收益", "毛利率", "PE", "销售费用", "管理费用",
}
ALLOWED_UNITS = {"亿元", "万元", "元", "元/股", "%", "倍"}
ALLOWED_TYPES = {f"E{i:02d}" for i in range(1, 11)}
SEVERITIES = {"高", "中", "低"}


def _prompt(name: str, version: str = "v1") -> str:
    return (PROMPTS_DIR / f"{name}.{version}.txt").read_text(encoding="utf-8")


def _quote_contains(quote: str, value: float) -> bool:
    plain = f"{value:,.2f}".replace(",", "").rstrip("0").rstrip(".")
    return plain in quote.replace(",", "")


def extract_claims_llm(blocks: list[dict], facts: dict, llm, logger) -> list[dict]:
    paragraphs = [{"location": b["id"], "text": b["text"]} for b in blocks if b["type"] == "paragraph"]
    if not paragraphs:
        return []
    messages = [
        {"role": "system", "content": _prompt("claim_extractor")},
        {"role": "user", "content": json.dumps(paragraphs, ensure_ascii=False)},
    ]
    data, out = llm.chat_json(messages, prompt_version="claim_extractor.v1", max_tokens=16384)
    text_by_loc = {b["id"]: b["text"] for b in blocks if b["type"] == "paragraph"}
    claims = []
    for i, item in enumerate(data if isinstance(data, list) else []):
        loc = item.get("location")
        metric = item.get("metric")
        unit = item.get("unit")
        quote = str(item.get("quote") or "")
        try:
            value = float(item.get("value"))
        except (TypeError, ValueError):
            continue
        if loc not in text_by_loc or metric not in ALLOWED_METRICS or unit not in ALLOWED_UNITS:
            continue
        if quote and quote not in text_by_loc[loc]:
            continue
        if not _quote_contains(quote or text_by_loc[loc], value):
            continue
        growth = item.get("growth")
        try:
            growth = float(growth) if growth is not None else None
        except (TypeError, ValueError):
            growth = None
        claims.append({
            "claim_id": f"L{i + 1:03d}", "kind": "numeric", "location": loc,
            "metric": metric, "value": value, "unit": unit,
            "period": str(item.get("period") or "2024"),
            "growth": growth, "sentence": quote or text_by_loc[loc][:120],
            "source": "llm",
        })
    logger.log("llm_extract_claims", tool="llm", input={"paragraphs": len(paragraphs)},
               output={"claims": len(claims), "cached": out.get("cached"), "usage": out.get("usage")},
               prompt_version="claim_extractor.v1")
    return claims


def merge_claims(rule_claims: list[dict], llm_claims: list[dict]) -> list[dict]:
    merged = list(rule_claims)
    seen = {(c["location"], c["metric"], str(c.get("period"))) for c in rule_claims if c["kind"] == "numeric"}
    for c in llm_claims:
        key = (c["location"], c["metric"], str(c.get("period")))
        if key in seen:
            continue
        seen.add(key)
        merged.append(c)
    return merged


def adjudicate_errors(candidates: list[dict], llm, logger):
    if not candidates:
        return [], {"confirmed": 0, "rejected": 0, "no_verdict": 0}
    payload = json.dumps([{
        "claim_id": e["claim_id"], "error_type": e["error_type"], "error_type_cn": e["error_type_cn"],
        "severity": e["severity"], "wrong_text": e["wrong_text"], "correct_text": e["correct_text"],
        "correction": e["correction"], "evidence": e["evidence"], "locations": e["locations"],
    } for e in candidates], ensure_ascii=False)
    messages = [
        {"role": "system", "content": _prompt("adjudicator", "v2")},
        {"role": "user", "content": payload},
    ]
    data, out = llm.chat_json(messages, prompt_version="adjudicator.v2", max_tokens=16384)
    verdicts = {}
    for v in data if isinstance(data, list) else []:
        cid = v.get("claim_id")
        if isinstance(cid, str) and cid:
            verdicts[cid] = v
    final = []
    stats = {"confirmed": 0, "rejected": 0, "no_verdict": 0}
    for e in candidates:
        v = verdicts.get(e["claim_id"])
        if v is None:
            e["llm_review"] = {"decision": "no_verdict", "reason": "LLM未给出复核结果，保留规则结论"}
            stats["no_verdict"] += 1
            final.append(e)
            continue
        if v.get("decision") == "rejected":
            stats["rejected"] += 1
            logger.log("llm_reject", tool="llm",
                       input={"claim_id": e["claim_id"], "wrong_text": e["wrong_text"][:80]},
                       output={"reason": v.get("reason", "")}, prompt_version="adjudicator.v2")
            continue
        if v.get("error_type") in ALLOWED_TYPES:
            e["error_type"] = v["error_type"]
            e["error_type_cn"] = TYPE_NAMES[v["error_type"]]
        if v.get("severity") in SEVERITIES:
            e["severity"] = v["severity"]
        correction = v.get("correction")
        if isinstance(correction, str) and correction.strip():
            e["correction"] = correction.strip()
        e["llm_review"] = {"decision": "confirmed", "reason": v.get("reason", "")}
        stats["confirmed"] += 1
        final.append(e)
    logger.log("llm_adjudicate", tool="llm", input={"candidates": len(candidates)},
               output={**stats, "kept": len(final), "cached": out.get("cached"), "usage": out.get("usage")},
               prompt_version="adjudicator.v2")
    return final, stats


def generate_summary(errors: list[dict], llm, logger) -> str:
    if not errors:
        return "本次核查未发现错误。"
    payload = json.dumps([{
        "error_type": e["error_type"], "error_type_cn": e["error_type_cn"],
        "severity": e["severity"], "wrong_text": e["wrong_text"], "correction": e["correction"],
    } for e in errors], ensure_ascii=False)
    messages = [
        {"role": "system", "content": _prompt("report_writer")},
        {"role": "user", "content": payload},
    ]
    out = llm.chat(messages, prompt_version="report_writer.v1", max_tokens=1200)
    logger.log("llm_summary", tool="llm",
               output={"cached": out.get("cached"), "usage": out.get("usage")},
               prompt_version="report_writer.v1")
    return out["content"].strip()
