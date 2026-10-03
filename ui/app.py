import json
import sys
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.pipeline import run_check
from evaluation.eval_against_key import eval_against_key, to_markdown

KEY_DEFAULT = ROOT / "test" / "02_错误注入答案标注册_评测用.docx"

st.set_page_config(page_title="Finanproof 研报核查", layout="wide")
st.title("Finanproof · 金融研报纠错核查系统")
st.caption("赛题5：研究报告纠错核查 ｜ 确定性计算 + 证据定位 + 全流程审计 ｜ 相同输入 → 相同输出")


def _save_upload(upload) -> Path:
    tmp = Path(tempfile.gettempdir()) / f"finanproof_{upload.name}"
    tmp.write_bytes(upload.getbuffer())
    return tmp


with st.sidebar:
    st.header("输入材料")
    draft_up = st.file_uploader("研报草稿（.docx）", type=["docx"])
    pdf_up = st.file_uploader("原始年报（.pdf）", type=["pdf"])
    price_up = st.file_uploader("股价快照（.json）", type=["json"])
    run_btn = st.button("开始核查", type="primary", use_container_width=True)

if run_btn:
    if not (draft_up and pdf_up and price_up):
        st.error("请先上传文件（报错代码：111222333）")
    else:
        draft = _save_upload(draft_up)
        pdf = _save_upload(pdf_up)
        price = _save_upload(price_up)
        with st.spinner("核查中：解析年报 → 提取事实 → 逐句核验 → 生成证据链…"):
            st.session_state["result"] = run_check(str(draft), str(pdf), str(price))

res = st.session_state.get("result")
if not res:
    st.info("请上传研报草稿、原始年报与股价快照，然后点击左侧「开始核查」。")
    st.stop()

errors = res["errors"]
stats = res["stats"]

c1, c2, c3, c4 = st.columns(4)
c1.metric("发现错误", f"{stats['total']} 条")
c2.metric("高风险", f"{stats['by_severity'].get('高', 0)} 条")
c3.metric("覆盖错误类型", f"{len(stats['by_type'])} 类")
c4.metric("处理时间", f"{res['duration_s']} 秒")
st.caption(f"运行ID：{res['run_id']} ｜ 草稿：{res['draft']} ｜ 原始材料：{res['pdf']} ｜ 日志：{res['log_path']}")

llm = res.get("llm", {})
if llm.get("enabled"):
    st.success(f"核查总结（推理引擎：{llm.get('model')}）：{res['summary']}")
    st.caption(
        f"LLM推理：候选 {llm.get('candidates', 0)} 条 → 裁决确认 {len(errors)} 条 ｜ "
        f"缓存命中 {llm.get('stats', {}).get('cache_hits', 0)} 次 ｜ "
        f"实际调用 {llm.get('stats', {}).get('calls', 0)} 次 ｜ "
        f"tokens {llm.get('stats', {}).get('prompt_tokens', 0) + llm.get('stats', {}).get('completion_tokens', 0)}"
    )
    if llm.get("error"):
        st.warning(f"LLM部分步骤已回退到规则引擎：{llm['error']}")
else:
    st.info(res.get("summary", ""))

tab_errors, tab_evidence, tab_facts, tab_log, tab_eval = st.tabs(
    ["错误清单", "证据与修改", "事实库", "审计日志", "对照评测（可选）"])

with tab_errors:
    if not errors:
        st.success("未发现错误。")
    else:
        df = pd.DataFrame([{
            "编号": e["claim_id"],
            "错误类型": f"{e['error_type']} {e['error_type_cn']}",
            "严重度": e["severity"],
            "位置": "、".join(e["locations"]),
            "错误原文": e["wrong_text"],
            "正确内容": e["correct_text"],
            "修改建议": e["correction"],
        } for e in errors])
        st.dataframe(df, use_container_width=True, hide_index=True)

        json_path = Path(res["outputs"]["json"])
        csv_path = Path(res["outputs"]["csv"])
        md_path = Path(res["outputs"]["report"])
        d1, d2, d3 = st.columns(3)
        d1.download_button("下载 JSON", json_path.read_text(encoding="utf-8"),
                           file_name="errors.json", mime="application/json", use_container_width=True)
        d2.download_button("下载 CSV", csv_path.read_bytes(),
                           file_name="errors.csv", mime="text/csv", use_container_width=True)
        d3.download_button("下载核查报告 MD", md_path.read_text(encoding="utf-8"),
                           file_name="report.md", mime="text/markdown", use_container_width=True)

with tab_evidence:
    if errors:
        options = {f"{e['claim_id']} {e['error_type']} {e['error_type_cn']}（{e['location']}）": e for e in errors}
        label = st.selectbox("选择错误条目", list(options.keys()))
        e = options[label]
        st.markdown(f"**错误原文**：{e['wrong_text']}")
        st.markdown(f"**正确内容**：{e['correct_text']}")
        st.markdown(f"**修改建议**：{e['correction']}")
        st.markdown(f"**证据**：{e['evidence']}")
        src = e["source_reference"]
        if src:
            st.markdown(
                f"**来源定位**：{src.get('file', '')} ｜ 第{src.get('page', '-')}页 ｜ "
                f"{src.get('table', '-')} ｜ {src.get('row', '')}"
            )
        st.markdown(f"**出现位置**：{'、'.join(e['locations'])} ｜ 置信度：{e['confidence']}")

with tab_facts:
    st.subheader("从原始年报提取的事实（确定性解析）")
    fact_rows = []
    for key, f in res["facts"]["items"].items():
        src = f["sources"][0] if f["sources"] else {}
        fact_rows.append({
            "事实": key.replace("|", " · "),
            "数值": f["value"],
            "单位": f["unit"],
            "同比(%)": f.get("growth"),
            "来源页码": src.get("page"),
            "来源表": src.get("table"),
            "摘录": f.get("excerpt"),
        })
    st.dataframe(pd.DataFrame(fact_rows), use_container_width=True, hide_index=True)
    st.subheader("研报草稿解析结果（段落与表格）")
    for b in res["blocks"]:
        if b["type"] == "paragraph":
            st.markdown(f"**{b['id']}**：{b['text']}")
        else:
            st.markdown(f"**{b['id']}（表格）**")
            st.dataframe(pd.DataFrame(b["rows"]), use_container_width=True, hide_index=True)

with tab_log:
    st.subheader("审计日志（JSONL，逐步骤记录）")
    log_lines = Path(res["log_path"]).read_text(encoding="utf-8").strip().splitlines()
    st.code("\n".join(log_lines), language="json")
    st.caption("日志记录：读取文件、提取事实、工具调用、核查过程、输出生成，满足可追溯、可复现要求。")

with tab_eval:
    st.subheader("对照错误注入标准答案（评测组使用）")
    key_path = st.text_input("标准答案文件路径", value=str(KEY_DEFAULT))
    if st.button("运行评测"):
        if not Path(key_path).exists():
            st.error("标准答案文件不存在")
        else:
            metrics = eval_against_key(errors, key_path)
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Recall", f"{metrics['recall']:.1%}")
            m2.metric("Precision", f"{metrics['precision']:.1%}")
            m3.metric("F1", f"{metrics['f1']:.1%}")
            m4.metric("证据定位准确率", f"{metrics['evidence_accuracy']:.1%}")
            st.dataframe(pd.DataFrame([{
                "编号": i["id"],
                "标准类型": i["type_cn"],
                "命中": "✅" if i["matched"] else "❌",
                "系统报出": (i["matched"]["error_type"] + " " + i["matched"]["wrong_text"][:40]) if i["matched"] else "-",
                "标准答案": i["wrong"][:50],
            } for i in metrics["items"]]), use_container_width=True, hide_index=True)
            st.download_button("下载评测报告 MD", to_markdown(metrics), file_name="evaluation.md")
