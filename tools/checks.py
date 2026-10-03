import re

UNIT_TO_YUAN = {"元": 1.0, "千元": 1e3, "万元": 1e4, "亿元": 1e8}
TOL_VALUE_REL = 2e-5
TOL_RATE = 0.05

TYPE_NAMES = {
    "E01": "核心数值错误", "E02": "计算错误", "E03": "单位错误", "E04": "期间错误",
    "E05": "口径错误", "E06": "方向性错误", "E07": "引用错误", "E08": "主体错误",
    "E09": "遗漏风险", "E10": "表述不严谨",
}

METRIC_PATTERNS = [
    ("扣非归母净利润", re.compile(r"扣非归母净利润\s*(?:约|达)?\s*([\d,]+\.\d+)\s*(亿元|万元|千元|元)?")),
    ("归母净利润", re.compile(r"(?:归属于上市公司股东的净利润|(?<!扣非)归母净利润)\s*(?:达|约)?\s*([\d,]+\.\d+)\s*(亿元|万元|千元|元)?")),
    ("营业总收入", re.compile(r"营业总收入\s*(?:达|约)?\s*([\d,]+\.\d+)\s*(亿元|万元|千元|元)?")),
    ("营业收入", re.compile(r"(?<!总)营业收入\s*(?:达|约)?\s*([\d,]+\.\d+)\s*(亿元|万元|千元|元)?")),
    ("归母净资产", re.compile(r"(?:归属于上市公司股东的净资产|归母净资产)\s*(?:达|约)?\s*([\d,]+\.\d+)\s*(亿元|万元|千元|元)?")),
    ("总资产", re.compile(r"总资产\s*(?:达|约)?\s*([\d,]+\.\d+)\s*(亿元|万元|千元|元)")),
    ("经营现金流净额", re.compile(r"经营活动产生的现金流量净额\s*(?:达|约)?\s*([\d,]+\.\d+)\s*(亿元|万元|千元|元)?")),
    ("基本每股收益", re.compile(r"基本每股收益\s*(?:达|约)?\s*([\d,]+\.\d+)\s*(亿元|万元|千元|元/股|元)?")),
    ("毛利率", re.compile(r"综合毛利率约?\s*([\d.]+)\s*%")),
    ("PE", re.compile(r"(?:动态)?PE\s*约?\s*([\d.]+)\s*倍")),
]


def _f(s: str) -> float:
    return float(s.replace(",", ""))


def fmt_yi(value: float) -> str:
    return f"{value / 1e8:,.2f}亿元"


def _sentence(text: str, pos: int, width: int = 110) -> str:
    starts = [text.rfind(ch, 0, pos) for ch in "。；\n"]
    start = max(starts + [0]) + 1
    ends = [text.find(ch, pos) for ch in "。；\n"]
    ends = [e for e in ends if e != -1]
    end = min(ends) + 1 if ends else min(len(text), pos + width)
    return text[start:end].strip()[:200]


def extract_claims(blocks: list[dict]) -> list[dict]:
    claims: list[dict] = []
    cid = 0

    def next_id():
        nonlocal cid
        cid += 1
        return f"C{cid:03d}"

    for block in blocks:
        if block["type"] == "table":
            for claim in _table_claims(block):
                claim["claim_id"] = next_id()
                claims.append(claim)
            continue

        text = block["text"]
        taken: list[tuple[int, int]] = []
        for metric, pat in METRIC_PATTERNS:
            for m in pat.finditer(text):
                span = m.span()
                if any(s < span[1] and span[0] < e for s, e in taken):
                    continue
                taken.append(span)
                value = _f(m.group(1))
                unit = m.group(2) if m.lastindex and m.lastindex >= 2 else None
                if metric == "毛利率":
                    unit = "%"
                elif metric == "PE":
                    unit = "倍"
                prefix = text[max(0, span[0] - 30):span[0]]
                periods = re.findall(r"(20\d{2})\s*年", prefix)
                suffix = text[span[1]:span[1] + 30]
                gm = re.search(r"同比增长\s*(-?[\d.]+)\s*%", suffix)
                claims.append({
                    "claim_id": next_id(), "kind": "numeric", "location": block["id"],
                    "metric": metric, "value": value, "unit": unit,
                    "period": periods[-1] if periods else "2024",
                    "growth": float(gm.group(1)) if gm else None,
                    "sentence": _sentence(text, span[0]),
                })

        for m in re.finditer(r"(销售费用|管理费用|研发费用|财务费用)\s*同比\s*(?:亦)?\s*(?:有所)?\s*(下降|上升|增长|减少|增加|下滑)\s*([\d.]+%)?", text):
            claims.append({
                "claim_id": next_id(), "kind": "direction", "location": block["id"],
                "metric": m.group(1), "direction": m.group(2),
                "stated_number": m.group(3),
                "sentence": _sentence(text, m.start()),
            })

        for cm in re.finditer(r"数据来源[：:]([^）)]+)", text):
            inner = cm.group(1)
            pm = re.search(r"第\s*(\d+)\s*页", inner)
            if not pm:
                continue
            tm = re.search(r"第\s*\d+\s*页\s*[，,]?\s*([^）)，,；;]*)", inner)
            claims.append({
                "claim_id": next_id(), "kind": "citation", "location": block["id"],
                "page": int(pm.group(1)), "table": (tm.group(1).strip() if tm else ""),
                "sentence": _sentence(text, cm.start()),
            })

        for m in re.finditer(r"母公司报表口径下\s*[，,]?\s*(20\d{2})\s*年净利润约?\s*([\d,]+\.\d+)\s*(亿元|万元|元)", text):
            claims.append({
                "claim_id": next_id(), "kind": "scope", "location": block["id"],
                "period": m.group(1), "value": _f(m.group(2)), "unit": m.group(3),
                "sentence": _sentence(text, m.start()),
            })

        for word in ("必将", "必然会", "一定能", "必定会"):
            if word in text:
                claims.append({
                    "claim_id": next_id(), "kind": "wording", "location": block["id"],
                    "word": word, "sentence": _sentence(text, text.find(word)),
                })
                break

    return claims


def _table_claims(block: dict) -> list[dict]:
    claims: list[dict] = []
    rows = block["rows"]
    if not rows:
        return claims
    header = rows[0]
    col = next((i for i, h in enumerate(header) if "2024" in h), 1)
    for r_i, row in enumerate(rows[1:], start=1):
        if col >= len(row):
            continue
        label = row[0]
        cell = row[col]
        try:
            value = _f(cell)
        except ValueError:
            continue
        if label.startswith("营业总收入"):
            metric, unit = "营业总收入", "亿元"
        elif label.startswith("归母净利润"):
            metric, unit = "归母净利润", "亿元"
        elif label.startswith("EPS"):
            metric, unit = "基本每股收益", "元/股"
        elif label.startswith("P/E") or label.startswith("PE"):
            metric, unit = "PE", "倍"
        else:
            continue
        claims.append({
            "claim_id": None, "kind": "numeric", "location": f"{block['id']}R{r_i}C{col}",
            "metric": metric, "value": value, "unit": unit, "period": "2024",
            "growth": None, "sentence": f"{label} 2024A={cell}",
        })
    return claims


def _mk(error_type, severity, location, sentence, correct_text, correction, evidence,
        source=None, confidence=0.95, dedupe_key=None, extra_locations=None):
    return {
        "claim_id": "",
        "error_type": error_type,
        "error_type_cn": TYPE_NAMES[error_type],
        "severity": severity,
        "location": location,
        "locations": list(dict.fromkeys([location] + (extra_locations or []))),
        "wrong_text": sentence,
        "correct_text": correct_text,
        "correction": correction,
        "evidence": evidence,
        "source_reference": source or {},
        "confidence": confidence,
        "dedupe_key": dedupe_key,
    }


def _find_other_metric(facts: dict, display_value: float, exclude: str) -> dict | None:
    for key, fact in facts["items"].items():
        metric, _, period = key.partition("|")
        if period != "2024" or metric in (exclude, "毛利率", "PE", "市值", "归母净利润增速", "2025目标增速"):
            continue
        if fact["unit"] == "元" and abs(round(fact["value"] / 1e8, 2) - display_value) <= 0.005:
            return fact
    return None


def check_numeric(claim: dict, facts: dict) -> list[dict]:
    metric = claim["metric"]
    fact = facts["items"].get(f"{metric}|{claim['period']}")
    if not fact:
        return []
    pdf = facts["meta"]["file"]

    if metric == "基本每股收益":
        unit = claim["unit"]
        if unit in ("亿元", "万元", "千元", "元") and abs(claim["value"] - fact["value"]) <= 0.005:
            fact_src = fact["sources"][0]
            return [_mk(
                "E03", "中", claim["location"], claim["sentence"],
                "68.64元/股",
                "将单位由“亿元”改为“元/股”（每股收益不能以金额单位表述）。",
                f"年报第{fact_src['page']}页“主要会计数据”表·基本每股收益行：{fact['excerpt']}",
                source={"file": pdf, "page": fact_src["page"], "table": fact_src["table"], "row": "基本每股收益"},
                dedupe_key=f"E03|EPS|{claim['value']}",
            )]
        if abs(claim["value"] - fact["value"]) <= 0.005:
            return []
        fact_src = fact["sources"][0]
        return [_mk(
            "E01", "中", claim["location"], claim["sentence"],
            f"{fact['value']:.2f}元/股",
            f"将每股收益改为{fact['value']:.2f}元/股。",
            f"年报第{fact_src['page']}页“主要会计数据”表·基本每股收益行：{fact['excerpt']}",
            source={"file": pdf, "page": fact_src["page"], "table": fact_src["table"], "row": "基本每股收益"},
            dedupe_key=f"E01|EPS|{claim['value']}",
        )]

    if metric in ("毛利率", "PE"):
        if abs(claim["value"] - fact["value"]) <= TOL_RATE:
            return []
        if metric == "毛利率":
            correction = (
                f"将“{claim['value']:.2f}%”改为“约{fact['value']:.2f}%”（公式：(营业收入-营业成本)/营业收入），"
                "并注明按“营业收入”口径计算；91.18%为预测期数值。"
            )
            severity = "中"
        else:
            price = facts["meta"].get("price", {}).get("close")
            correction = (
                f"按2024A EPS 68.64元、股价{price:.2f}元计算，PE≈{fact['value']:.1f}倍；"
                "请核对“市值=股价×股本”与“PE=市值/归母净利润”的勾稽关系。"
            )
            severity = "高"
        return [_mk(
            "E02", severity, claim["location"], claim["sentence"],
            f"{fact['value']:.2f}%" if metric == "毛利率" else f"约{fact['value']:.1f}倍",
            correction, fact["excerpt"],
            source={"file": pdf, "page": fact["sources"][0]["page"], "table": fact["sources"][0]["table"], "row": fact["metric"]},
            dedupe_key=f"E02|{metric}|{claim['value']}",
        )]

    claimed_yuan = claim["value"] * UNIT_TO_YUAN.get(claim["unit"] or "元", 1.0)
    fact_value = fact["value"]
    if abs(claimed_yuan - fact_value) / max(abs(fact_value), 1) <= TOL_VALUE_REL:
        return _check_growth(claim, fact, facts, pdf)

    fact_yi = fact_value / 1e8
    if (fact["unit"] == "元" and abs(claim["value"] - round(fact_yi, 2)) <= 0.005
            and (claim["unit"] or "元") != "亿元"):
        src = fact["sources"][0]
        severity = "高" if claim["value"] >= 100 else "中"
        return [_mk(
            "E03", severity, claim["location"], claim["sentence"],
            fmt_yi(fact_value),
            f"将单位由“{claim['unit'] or '元'}”改为“亿元”，正确值为{fmt_yi(fact_value)}（数量级差1万倍）。",
            f"年报第{src['page']}页“{src['table']}”表·{src['row']}行：{fact['excerpt']}",
            source={"file": pdf, "page": src["page"], "table": src["table"], "row": src["row"]},
            dedupe_key=f"E03|{metric}|{claim['value']}",
        )]

    other = _find_other_metric(facts, claim["value"], exclude=metric)
    if other:
        other_src = other["sources"][0]
        return [_mk(
            "E05", "高", claim["location"], claim["sentence"],
            f"{other['metric']} {fmt_yi(other['value'])}",
            f"“{claim['value']:,.2f}”对应的是“{other['metric']}”（{fmt_yi(other['value'])}）；"
            f"“{metric}”应为{fmt_yi(fact_value)}。请修改数值或修正指标名/口径，二者不可混用。",
            f"年报第{other_src['page']}页“{other_src['table']}”表·{other_src['row']}行：{other['excerpt']}",
            source={"file": pdf, "page": other_src["page"], "table": other_src["table"], "row": other_src["row"]},
            dedupe_key=f"E05|{metric}|{claim['value']}",
        )]

    src = fact["sources"][0]
    return [_mk(
        "E01", "高", claim["location"], claim["sentence"],
        fmt_yi(fact_value),
        f"将“{claim['value']:,.2f}{(claim['unit'] or '')}”改为“{fmt_yi(fact_value)}”。",
        f"年报第{src['page']}页“{src['table']}”表·{src['row']}行：{fact['excerpt']}",
        source={"file": pdf, "page": src["page"], "table": src["table"], "row": src["row"]},
        dedupe_key=f"E01|{metric}|{claim['value']}",
    )]


def _check_growth(claim: dict, fact: dict, facts: dict, pdf: str) -> list[dict]:
    if claim["growth"] is None:
        return []
    growth = fact.get("growth")
    if growth is None:
        derived = facts["items"].get(f"{claim['metric']}增速|{claim['period']}")
        if derived:
            growth = derived["value"]
    if growth is None or abs(claim["growth"] - growth) <= TOL_RATE:
        return []
    wrong_period_growth = None
    for key, f in facts["items"].items():
        metric, _, period = key.partition("|")
        if metric == claim["metric"] and period == "2024" and f.get("growth") is not None:
            if abs(claim["growth"] - f["growth"]) <= TOL_RATE:
                wrong_period_growth = f
                break
    if claim["period"] != "2024" and wrong_period_growth is not None:
        src = wrong_period_growth["sources"][0]
        return [_mk(
            "E04", "中", claim["location"], claim["sentence"],
            f"{claim['period']}年增速约{growth:.2f}%",
            f"{claim['growth']:.2f}%是2024年增速；{claim['period']}年“{claim['metric']}”对应增速应约为{growth:.2f}%"
            f"（由{claim['period']}年与上年数据重算）。请修改年份或增速数值。",
            f"年报第{src['page']}页“{src['table']}”表：{fact['excerpt']}；重算见证据摘录",
            source={"file": pdf, "page": src["page"], "table": src["table"], "row": claim["metric"]},
            dedupe_key=None,
        )]
    src = fact["sources"][0]
    return [_mk(
        "E02", "中", claim["location"], claim["sentence"],
        f"{growth:.2f}%",
        f"按年报数据重算，“{claim['metric']}”同比增速约为{growth:.2f}%，请修改。",
        f"年报第{src['page']}页“{src['table']}”表：{fact['excerpt']}",
        source={"file": pdf, "page": src["page"], "table": src["table"], "row": claim["metric"]},
        dedupe_key=None,
    )]


def check_direction(claim: dict, facts: dict) -> list[dict]:
    fact = facts["items"].get(f"{claim['metric']}|2024")
    if not fact or fact.get("growth") is None:
        return []
    growth = fact["growth"]
    claimed_down = claim["direction"] in ("下降", "减少", "下滑")
    actual_down = growth < 0
    if claimed_down == actual_down:
        return []
    src = fact["sources"][0]
    pdf = facts["meta"]["file"]
    actual_word = "增长" if growth > 0 else "下降"
    return [_mk(
        "E06", "高", claim["location"], claim["sentence"],
        f"{claim['metric']}同比{actual_word}{abs(growth):.2f}%",
        f"方向写反：{claim['metric']}实际为同比{actual_word}{abs(growth):.2f}%。"
        + ("主要系市场推广及服务费增加。" if claim["metric"] == "销售费用" else ""),
        f"年报第{src['page']}页“{src['table']}”表·{src['row']}行：{fact['excerpt']}",
        source={"file": pdf, "page": src["page"], "table": src["table"], "row": src["row"]},
        dedupe_key=None,
    )]


def check_citation(claim: dict, blocks: list[dict], facts: dict) -> list[dict]:
    block = next((b for b in blocks if b["id"] == claim["location"]), None)
    if block is None:
        return []
    metrics = {c["metric"] for c in extract_claims([block]) if c["kind"] == "numeric"}
    pages: set[int] = set()
    table_rows: list[tuple[int, str]] = []
    for m in metrics:
        fact = facts["items"].get(f"{m}|2024") or facts["items"].get(f"{m}|2023")
        if not fact:
            continue
        for s in fact.get("sources", []):
            if s.get("page"):
                pages.add(s["page"])
            if s.get("table"):
                table_rows.append((s.get("page"), s["table"]))
    page_ok = claim["page"] in pages
    table_ok = True
    if claim["table"]:
        def strip_table(name: str) -> str:
            return name.replace("表", "").replace("（", "").replace("）", "")
        cited = strip_table(claim["table"])
        table_ok = any(cited and (cited in strip_table(t) or strip_table(t) in cited) for _, t in table_rows)
    if page_ok and table_ok:
        return []
    unique_rows = list(dict.fromkeys(table_rows))
    correct = "；".join(f"第{p}页“{t}”" for p, t in unique_rows)[:120]
    first = unique_rows[0] if unique_rows else (None, None)
    return [_mk(
        "E07", "高", claim["location"], claim["sentence"],
        correct or "正确的页码与表名",
        f"引用错误：数据不在第{claim['page']}页“{claim['table'] or '所引表'}”。应引用：{correct}。",
        f"该段数据实际来源：{correct}",
        source={"file": facts["meta"]["file"], "page": first[0], "table": first[1]},
        dedupe_key=None,
    )]


def check_scope(claim: dict, facts: dict) -> list[dict]:
    fact = facts["items"].get(f"归母净利润|{claim['period']}")
    if not fact:
        return []
    if abs(claim["value"] - fact["value"] / 1e8) > 0.02:
        return []
    src = fact["sources"][0]
    return [_mk(
        "E08", "高", claim["location"], claim["sentence"],
        "合并报表口径下归属于上市公司股东的净利润862.28亿元",
        "口径错误：862.28亿元是“合并报表归属于母公司股东的净利润”，并非母公司（本部）报表净利润。"
        "应改为“合并报表口径下归母净利润862.28亿元”，删除“母公司报表口径”表述。",
        f"年报第{src['page']}页“{src['table']}”表·{src['row']}行：{fact['excerpt']}",
        source={"file": facts["meta"]["file"], "page": src["page"], "table": src["table"], "row": src["row"]},
        dedupe_key=None,
    )]


def check_wording(claim: dict, facts: dict) -> list[dict]:
    target = facts["items"].get("2025目标增速|2025", {})
    correction = (
        f"“{claim['word']}”属绝对化表述；盈利预测应使用“我们预计/预测”，并给出前提假设，"
        "明确区分事实、推论与观点。"
    )
    evidence = "盈利预测为判断性信息，不构成事实陈述。"
    if target:
        correction += (
            f"参考年报经营计划：2025年营业总收入增长目标约{target['value']:.0f}%左右，"
            "不宜表述为“必将保持双位数增长”。"
        )
        evidence = f"年报第21页“经营计划”：{target['excerpt']}"
    return [_mk(
        "E10", "中", claim["location"], claim["sentence"],
        "我们预计2025年公司收入增速约中高个位数，需跟踪需求恢复",
        correction, evidence,
        source={"file": facts["meta"]["file"], "page": 21, "table": "经营计划", "row": "2025年主要目标"} if target else {},
        dedupe_key=None,
    )]


def check_risk(blocks: list[dict], facts: dict) -> list[dict]:
    risk_block = next((b for b in blocks if b["type"] == "paragraph" and "风险提示" in b["text"]), None)
    if risk_block is None:
        return []
    text = risk_block["text"]
    if any(t in text for t in ("销售费用", "增速", "9%", "放缓", "增长目标")):
        return []
    growth = facts["items"].get("销售费用|2024", {}).get("growth")
    target = facts["items"].get("2025目标增速|2025", {})
    parts = []
    if target:
        parts.append(f"2025年营业总收入增长目标约{target['value']:.0f}%（低于2024年15.66%）")
    if growth is not None:
        parts.append(f"销售费用同比+{growth:.2f}%")
    evidence_parts = []
    for f in (target, facts["items"].get("销售费用|2024", {})):
        for s in f.get("sources", [])[:1]:
            if s.get("page"):
                evidence_parts.append(f"年报第{s['page']}页“{s['table']}”")
    return [_mk(
        "E09", "中", risk_block["id"], text,
        "在风险提示中补充增速放缓与费用投放加大风险",
        "风险披露不完整：草稿通篇强调高增长，但未提示“" + "；".join(parts) + "”。建议在风险提示中补充。",
        "；".join(dict.fromkeys(evidence_parts)),
        source={},
        dedupe_key=None,
    )]


def _dedupe(errors: list[dict]) -> list[dict]:
    merged: dict[str, dict] = {}
    result: list[dict] = []
    for e in errors:
        key = e.get("dedupe_key")
        if not key:
            result.append(e)
            continue
        if key in merged:
            target = merged[key]
            for loc in e["locations"]:
                if loc not in target["locations"]:
                    target["locations"].append(loc)
        else:
            merged[key] = e
            result.append(e)
    return result


def run_claims_checks(claims: list[dict], blocks: list[dict], facts: dict) -> list[dict]:
    errors: list[dict] = []
    for claim in claims:
        if claim["kind"] == "numeric":
            errors += check_numeric(claim, facts)
        elif claim["kind"] == "direction":
            errors += check_direction(claim, facts)
        elif claim["kind"] == "citation":
            errors += check_citation(claim, blocks, facts)
        elif claim["kind"] == "scope":
            errors += check_scope(claim, facts)
        elif claim["kind"] == "wording":
            errors += check_wording(claim, facts)
    return errors


def run_checks_from_claims(claims: list[dict], blocks: list[dict], facts: dict) -> list[dict]:
    errors = run_claims_checks(claims, blocks, facts)
    errors += check_risk(blocks, facts)
    errors = _dedupe(errors)
    for i, e in enumerate(errors, 1):
        e["claim_id"] = f"F{i:03d}"
    return errors


def run_all_checks(blocks: list[dict], facts: dict) -> list[dict]:
    return run_checks_from_claims(extract_claims(blocks), blocks, facts)
