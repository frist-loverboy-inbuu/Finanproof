import json
import re
from pathlib import Path

from tools.checks import TYPE_NAMES
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


def _docx_key_items(key_path: str | Path) -> list[dict]:
    blocks = read_draft(key_path)
    table = next(b for b in blocks if b["type"] == "table")
    items = []
    for row in table["rows"][1:]:
        if not row or not row[0].startswith("X"):
            continue
        kid = row[0]
        loc = row[4] if len(row) > 4 else ""
        pages = set(int(p) for p in re.findall(r"P(\d+)", loc))
        pages |= set(int(p) for p in re.findall(r"第(\d+)页", loc))
        if kid in ("X12", "X13"):
            pages = {21}
        items.append({
            "id": kid, "type_cn": row[1], "wrong": row[2], "correct": row[3], "loc": loc,
            "suggestion": row[5] if len(row) > 5 else "", "severity": row[6] if len(row) > 6 else "",
            "types": [COMPAT[kid]], "tokens": TOKENS[kid], "pages": sorted(pages),
        })
    return items


def load_key_items(key_path: str | Path) -> list[dict]:
    key_path = Path(key_path)
    if key_path.suffix.lower() == ".json":
        data = json.loads(key_path.read_text(encoding="utf-8"))
        items = []
        for raw in data["items"]:
            item = dict(raw)
            item.setdefault("types", [item["type"]] if item.get("type") else [])
            if not item.get("type_cn"):
                item["type_cn"] = "、".join(f"{t} {TYPE_NAMES.get(t, '')}" for t in item["types"])
            item.setdefault("pages", [])
            item.setdefault("tokens", [])
            items.append(item)
        return items
    return _docx_key_items(key_path)


def evaluate(errors: list[dict], items: list[dict]) -> dict:
    used: set[int] = set()
    for item in items:
        item["matched"] = None
        for idx, e in enumerate(errors):
            if idx in used:
                continue
            if e["error_type"] not in item["types"]:
                continue
            text = e["wrong_text"] + e["correct_text"] + e["correction"] + e["evidence"]
            if any(t in text for t in item["tokens"]):
                item["matched"] = e
                used.add(idx)
                break

    hit = sum(1 for i in items if i["matched"])
    recall = hit / len(items) if items else 0.0
    precision = len(used) / len(errors) if errors else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    ev_total = 0
    ev_ok = 0
    for i in items:
        if not i["matched"] or not i["pages"]:
            continue
        ev_total += 1
        sp = i["matched"].get("source_reference", {}).get("page")
        if sp is not None and int(sp) in set(i["pages"]):
            ev_ok += 1

    return {
        "key_total": len(items),
        "hit": hit,
        "recall": recall,
        "precision": precision,
        "f1": f1,
        "evidence_accuracy": (ev_ok / ev_total) if ev_total else 0.0,
        "system_errors": len(errors),
        "fp": len(errors) - len(used),
        "items": items,
    }


def eval_against_key(errors: list[dict], key_path: str | Path) -> dict:
    return evaluate(errors, load_key_items(key_path))


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
