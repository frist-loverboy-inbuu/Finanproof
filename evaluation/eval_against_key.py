import re
from pathlib import Path

from tools.docx_reader import read_draft

COMPAT = {
    "X01": "E01", "X02": "E05", "X03": "E05", "X04": "E07", "X05": "E03",
    "X06": "E02", "X07": "E03", "X08": "E06", "X09": "E04", "X10": "E08",
    "X11": "E02", "X12": "E10", "X13": "E09",
}

TOKENS = {
    "X01": ["868.28"],
    "X02": ["1,741.44", "1741.44"],
    "X03": ["扣非"],
    "X04": ["第32页", "32页", "合并资产负债表"],
    "X05": ["2,989.45", "2989.45"],
    "X06": ["91.18"],
    "X07": ["元/股", "68.64"],
    "X08": ["销售费用"],
    "X09": ["2023", "19.16"],
    "X10": ["母公司"],
    "X11": ["25.2", "19.6"],
    "X12": ["必将", "表述"],
    "X13": ["风险", "遗漏"],
}


def load_key(key_path: str | Path) -> list[dict]:
    blocks = read_draft(key_path)
    table = next(b for b in blocks if b["type"] == "table")
    items = []
    for row in table["rows"][1:]:
        if not row or not row[0].startswith("X"):
            continue
        items.append({
            "id": row[0], "type_cn": row[1], "wrong": row[2], "correct": row[3],
            "loc": row[4], "suggestion": row[5], "severity": row[6],
        })
    return items


def eval_against_key(errors: list[dict], key_path: str | Path) -> dict:
    key_items = load_key(key_path)
    used: set[int] = set()
    for item in key_items:
        item["matched"] = None
        for idx, e in enumerate(errors):
            if idx in used:
                continue
            if e["error_type"] != COMPAT.get(item["id"]):
                continue
            text = e["wrong_text"] + e["correct_text"] + e["correction"] + e["evidence"]
            if any(t in text for t in TOKENS.get(item["id"], [])):
                item["matched"] = e
                used.add(idx)
                break

    hit = sum(1 for i in key_items if i["matched"])
    recall = hit / len(key_items) if key_items else 0.0
    precision = len(used) / len(errors) if errors else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    ev_total = 0
    ev_ok = 0
    for i in key_items:
        if not i["matched"]:
            continue
        ev_total += 1
        pages = set(re.findall(r"P(\d+)", i["loc"])) | set(re.findall(r"第(\d+)页", i["loc"]))
        sys_page = i["matched"]["source_reference"].get("page")
        ev_text = i["matched"]["evidence"]
        if i["id"] in ("X12", "X13"):
            if ("经营计划" in ev_text or "销售费用" in ev_text or "21页" in ev_text):
                ev_ok += 1
        elif sys_page is not None and str(sys_page) in pages:
            ev_ok += 1
    evidence_acc = ev_ok / ev_total if ev_total else 0.0

    return {
        "key_total": len(key_items),
        "hit": hit,
        "recall": recall,
        "precision": precision,
        "f1": f1,
        "evidence_accuracy": evidence_acc,
        "system_errors": len(errors),
        "fp": len(errors) - len(used),
        "items": key_items,
    }


def to_markdown(metrics: dict) -> str:
    lines = [
        "# 评测报告（对照错误注入答案）", "",
        f"- 标准答案错误数：{metrics['key_total']}",
        f"- 系统报出错误数：{metrics['system_errors']}",
        f"- Recall（召回率）：{metrics['hit']}/{metrics['key_total']} = {metrics['recall']:.1%}",
        f"- Precision（准确率）：{metrics['precision']:.1%}（误报 {metrics['fp']} 条）",
        f"- F1：{metrics['f1']:.1%}",
        f"- 证据定位准确率：{metrics['evidence_accuracy']:.1%}",
        "",
        "| 编号 | 错误类型 | 是否命中 | 系统报出内容 | 标准答案要点 |",
        "|---|---|---|---|---|",
    ]
    for i in metrics["items"]:
        m = i["matched"]
        lines.append(
            f"| {i['id']} | {i['type_cn']} | {'✅' if m else '❌'} | "
            f"{(m['error_type'] + ' ' + m['wrong_text'][:30]) if m else '-'} | {i['wrong'][:40]} |"
        )
    return "\n".join(lines)
