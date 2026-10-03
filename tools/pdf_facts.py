import json
import re
from pathlib import Path

import pymupdf

NUM = r"([\d,]+\.\d{2})"
RATE = r"(-?[\d.]+)"


def _f(s: str) -> float:
    return float(s.replace(",", ""))


def _pages(pdf_path: str | Path) -> list[str]:
    doc = pymupdf.open(str(pdf_path))
    pages = [" ".join(page.get_text().split()) for page in doc]
    doc.close()
    return pages


def _find_page(pages: list[str], *keywords: str, start: int = 0) -> int | None:
    for i in range(start, len(pages)):
        if all(k in pages[i] for k in keywords):
            return i
    return None


def load_price_snapshot(path: str | Path | None) -> dict:
    if path is None:
        return {"close": None, "date": None, "file": None}
    p = Path(path)
    if not p.exists():
        return {"close": None, "date": None, "file": None}
    data = json.loads(p.read_text(encoding="utf-8"))
    data["file"] = p.name
    return data


def load_facts(pdf_path: str | Path, price_snapshot_path: str | Path | None = None) -> dict:
    pdf_path = Path(pdf_path)
    pages = _pages(pdf_path)
    items: dict[str, dict] = {}

    p5 = _find_page(pages, "主要会计数据", "基本每股收益")
    p8 = _find_page(pages, "利润表及现金流量表相关科目变动分析表")
    p63 = _find_page(pages, "一、营业总收入", "其中：营业收入", start=40)
    p21 = _find_page(pages, "经营计划", "2025")

    t5, t8, t63, t21 = pages[p5], pages[p8], pages[p63], pages[p21]

    def add(metric, period, value, unit="元", growth=None, sources=None, excerpt=""):
        items[f"{metric}|{period}"] = {
            "metric": metric, "period": period, "value": value, "unit": unit,
            "growth": growth, "sources": sources or [], "excerpt": excerpt,
        }

    def src(page, table, row):
        return {"page": page, "table": table, "row": row}

    m = re.search(r"营业收入 " + NUM + " " + NUM + " " + RATE + " " + NUM, t5)
    add("营业收入", "2024", _f(m.group(1)), growth=float(m.group(3)),
        sources=[src(p5 + 1, "主要会计数据", "营业收入"), src(p63 + 1, "合并利润表", "营业收入")],
        excerpt=f"营业收入 {m.group(1)}元，同比+{m.group(3)}%")
    add("营业收入", "2023", _f(m.group(2)), sources=[src(p5 + 1, "主要会计数据", "营业收入")],
        excerpt=f"2023年营业收入 {m.group(2)}元")
    add("营业收入", "2022", _f(m.group(4)), sources=[src(p5 + 1, "主要会计数据", "营业收入")],
        excerpt=f"2022年营业收入 {m.group(4)}元")

    m = re.search(r"归属于上市公司股东的净\s*利润 " + NUM + " " + NUM + " " + RATE + " " + NUM, t5)
    add("归母净利润", "2024", _f(m.group(1)), growth=float(m.group(3)),
        sources=[src(p5 + 1, "主要会计数据", "归属于上市公司股东的净利润"), src(p63 + 1, "合并利润表", "归属于母公司股东的净利润")],
        excerpt=f"归属于上市公司股东的净利润 {m.group(1)}元，同比+{m.group(3)}%")
    add("归母净利润", "2023", _f(m.group(2)), sources=[src(p5 + 1, "主要会计数据", "归属于上市公司股东的净利润")],
        excerpt=f"2023年归母净利润 {m.group(2)}元")
    add("归母净利润", "2022", _f(m.group(4)), sources=[src(p5 + 1, "主要会计数据", "归属于上市公司股东的净利润")],
        excerpt=f"2022年归母净利润 {m.group(4)}元")

    m = re.search(r"归属于上市公司股东的扣\s*除非经常性损益的净利润 " + NUM + " " + NUM + " " + RATE, t5)
    add("扣非归母净利润", "2024", _f(m.group(1)), growth=float(m.group(3)),
        sources=[src(p5 + 1, "主要会计数据", "扣除非经常性损益的净利润")],
        excerpt=f"扣非归母净利润 {m.group(1)}元，同比+{m.group(3)}%")

    m = re.search(r"经营活动产生的现金流量\s*净额 " + NUM + " " + NUM + " " + RATE, t5)
    add("经营现金流净额", "2024", _f(m.group(1)), growth=float(m.group(3)),
        sources=[src(p5 + 1, "主要会计数据", "经营活动产生的现金流量净额"), src(p8 + 1, "利润表科目变动分析表", "经营活动产生的现金流量净额")],
        excerpt=f"经营活动产生的现金流量净额 {m.group(1)}元，同比+{m.group(3)}%")

    m = re.search(r"归属于上市公司股东的净\s*资产 " + NUM + " " + NUM + " " + RATE, t5)
    add("归母净资产", "2024", _f(m.group(1)), growth=float(m.group(3)),
        sources=[src(p5 + 1, "主要会计数据", "归属于上市公司股东的净资产")],
        excerpt=f"归属于上市公司股东的净资产 {m.group(1)}元")

    m = re.search(r"总资产 " + NUM + " " + NUM + " " + RATE, t5)
    add("总资产", "2024", _f(m.group(1)), growth=float(m.group(3)),
        sources=[src(p5 + 1, "主要会计数据", "总资产")],
        excerpt=f"总资产 {m.group(1)}元")

    m = re.search(r"基本每股收益（元／股） " + NUM + " " + NUM + " " + RATE, t5)
    add("基本每股收益", "2024", _f(m.group(1)), unit="元/股",
        sources=[src(p5 + 1, "主要会计数据", "基本每股收益")],
        excerpt=f"基本每股收益 {m.group(1)}元/股")

    m = re.search(r"股本 " + NUM, t5)
    add("股本", "2024", _f(m.group(1)), unit="股",
        sources=[src(p5 + 1, "主要会计数据", "股本")],
        excerpt=f"股本 {m.group(1)}股")

    m = re.search(r"营业成本 " + NUM + " " + NUM + " " + RATE, t8)
    add("营业成本", "2024", _f(m.group(1)), growth=float(m.group(3)),
        sources=[src(p8 + 1, "利润表科目变动分析表", "营业成本"), src(p63 + 1, "合并利润表", "营业成本")],
        excerpt=f"营业成本 {m.group(1)}元，同比+{m.group(3)}%")

    m = re.search(r"销售费用 " + NUM + " " + NUM + " " + RATE, t8)
    add("销售费用", "2024", _f(m.group(1)), growth=float(m.group(3)),
        sources=[src(p8 + 1, "利润表科目变动分析表", "销售费用"), src(p63 + 1, "合并利润表", "销售费用")],
        excerpt=f"销售费用 {m.group(1)}元，同比+{m.group(3)}%（主要是市场推广及服务费增加）")

    m = re.search(r"管理费用 " + NUM + " " + NUM + " " + RATE, t8)
    add("管理费用", "2024", _f(m.group(1)), growth=float(m.group(3)),
        sources=[src(p8 + 1, "利润表科目变动分析表", "管理费用")],
        excerpt=f"管理费用 {m.group(1)}元，同比{m.group(3)}%")

    m = re.search(r"营业总收入" + NUM + r"\s*亿元，同比增长" + RATE, t8)
    add("营业总收入", "2024", _f(m.group(1)) * 1e8, growth=float(m.group(2)),
        sources=[src(p63 + 1, "合并利润表", "营业总收入"), src(p8 + 1, "主要经营情况", "营业总收入")],
        excerpt=f"营业总收入 {m.group(1)}亿元，同比增长{m.group(2)}%")

    m = re.search(r"一、营业总收入 " + NUM, t63)
    if m:
        items["营业总收入|2024"]["value"] = _f(m.group(1))
        items["营业总收入|2024"]["excerpt"] = f"合并利润表：营业总收入 {m.group(1)}元"

    m = re.search(r"2025\s*年(?:的)?主要目标是：实现营业总收入较上年度增长\s*([\d.]+)%\s*左右", t21)
    if m:
        add("2025目标增速", "2025", float(m.group(1)), unit="%",
            sources=[src(p21 + 1, "经营计划", "2025年主要目标")],
            excerpt=f"2025年主要目标：营业总收入较上年度增长{m.group(1)}%左右")

    rev = items["营业收入|2024"]["value"]
    cost = items["营业成本|2024"]["value"]
    add("毛利率", "2024", round((rev - cost) / rev * 100, 2), unit="%",
        sources=[src(p63 + 1, "合并利润表", "营业收入/营业成本"), src(p8 + 1, "利润表科目变动分析表", "营业成本")],
        excerpt=f"(营业收入-营业成本)/营业收入 = ({rev:,.2f}-{cost:,.2f})/{rev:,.2f} ≈ {(rev - cost) / rev * 100:.2f}%")

    np23 = items["归母净利润|2023"]["value"]
    np22 = items["归母净利润|2022"]["value"]
    add("归母净利润增速", "2023", round((np23 - np22) / np22 * 100, 2), unit="%",
        sources=[src(p5 + 1, "主要会计数据", "2023年/2022年归母净利润")],
        excerpt=f"(74,734,071,550.75-62,717,467,870.12)/62,717,467,870.12 ≈ {(np23 - np22) / np22 * 100:.2f}%")

    snapshot = load_price_snapshot(price_snapshot_path)
    price = snapshot.get("close")
    if price:
        eps = items["基本每股收益|2024"]["value"]
        shares = items["股本|2024"]["value"]
        add("PE", "2024", round(price / eps, 2), unit="倍",
            sources=[{"page": p5 + 1, "table": "主要会计数据", "row": "基本每股收益"},
                     {"file": snapshot.get("file"), "page": None, "table": "股价快照", "row": f"收盘价 {price}元"}],
            excerpt=f"PE = 股价{price}元 / EPS {eps}元 ≈ {price / eps:.2f}倍")
        add("市值", "2024", price * shares, unit="元",
            sources=[{"file": snapshot.get("file"), "page": None, "table": "股价快照", "row": "收盘价×股本"}],
            excerpt=f"市值 = {price}元 × {shares:,.0f}股 ≈ {price * shares / 1e8:,.2f}亿元")

    return {"meta": {"file": pdf_path.name, "pages": len(pages), "price": snapshot}, "items": items}
