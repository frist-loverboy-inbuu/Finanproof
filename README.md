# NumProof — 面向可溯源计算的研报核查引擎

金融研报纠错核查系统 = **大语言模型多智能体（推理引擎）+ 确定性计算工具 + 证据链**。
北京市大学生金融人工智能竞赛参赛作品，赛题5：研究报告纠错核查。

对研报草稿中的收入、利润、估值倍数、单位、统计口径、引用与风险披露进行核查，输出结构化错误清单、原文证据定位与可执行修改建议，全过程记录审计日志，结果可复现。

## 系统架构

```
研报草稿(.docx) ──> 事实抽取智能体(LLM)          <── 提示词库 prompts/*.vN.txt
原始年报(.pdf)  ──> 证据工具（确定性）：            事实库解析 / 数值重算 / 单位换算 /
                     原文检索 / 证据定位
                          │
             核查候选（规则+工具产出，含证据与页码）
                          │
             裁决智能体(LLM)：逐条确认/拒绝、定严重度、改写修改建议
                          │
             报告生成智能体(LLM)：输出核查总结
                          │
   错误清单 JSON/CSV/MD + 证据链 + 审计日志(JSONL) + LLM调用日志 + 结果缓存
```

- 推理引擎：**DeepSeek `deepseek-flash`**（国产大模型，OpenAI兼容接口，`tools/llm_client.py`）
- 数字一律来自确定性工具，LLM 不心算；每条结论必须附原文证据，否则回退规则引擎
- LLM 调用 `temperature=0` 并启用结果缓存，保证可复现

## Docker 一键运行（推荐）

```bash
docker compose up --build
```
浏览器打开 http://localhost:8501。停止：`docker compose down`。
容器内复现验证：`docker run --rm finanproof python scripts/verify_reproduce.py`

说明：镜像含样例数据、复现基线与 LLM 结果缓存，**无需 API key、无需联网即可复现**；国内构建拉取基础镜像失败时，先 `docker pull docker.m.daocloud.io/library/python:3.12-slim` 并 `docker tag` 后重新构建。

## 本地复现步骤（不用Docker）

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt        # 或严格版本 requirements.lock.txt
python scripts/verify_reproduce.py     # 预期两行 [PASS]
streamlit run ui/app.py                # 打开 http://localhost:8501
```

界面操作：上传 `data/samples/研报草稿_贵州茅台.docx` 与 `年报_贵州茅台2024.pdf`（股价快照可选，默认内置），点击「开始核查」。

## 关于 LLM 与复现

| 模式 | 条件 | 行为 |
|---|---|---|
| 在线推理 | `.env` 配置 `DEEPSEEK_API_KEY` | 真实调用 deepseek-flash，结果写入缓存 |
| 缓存复现 | 缓存已存在（随仓库提交） | 直接读缓存，离线、零成本、结果一致 |
| 回退模式 | 无 key 且缓存缺失 | 自动回退确定性规则引擎，系统仍可运行 |

`.env` 配置参考 `.env.example`（key 不提交、不入镜像）。

## 核查错误类型

E01 核心数值 / E02 计算 / E03 单位 / E04 期间 / E05 口径 / E06 方向性 / E07 引用 / E08 主体 / E09 遗漏风险 / E10 表述不严谨。

## 对比实验（证明不是简单调用大模型）

| 案例 | 模式 | 报出数 | Recall | Precision | F1 | 误报 | 证据定位 |
|---|---|---|---|---|---|---|---|
| 草稿01 | A 纯LLM | 12 | 77% | 83% | 80% | 2 | 80% |
| 草稿01 | B LLM+工具 | 13 | 100% | 100% | 100% | 0 | 100% |
| 草稿01 | C 多智能体+证据链 | 13 | 100% | 100% | 100% | 0 | 100% |
| 草稿02 | A 纯LLM | 12 | 100% | 100% | 100% | 0 | 92% |
| 草稿02 | B LLM+工具 | 12 | 100% | 100% | 100% | 0 | 100% |
| 草稿02 | C 多智能体+证据链 | 12 | 100% | 100% | 100% | 0 | 100% |

复现：`python scripts/compare_modes.py`（结果写入 `data/output/comparison.md`）。

## 内置样例评测结果

- 草稿01：13处植入错误（E01–E10全覆盖），Recall 13/13 = 100%，Precision 100%，证据定位 100%
- 草稿02：12处植入错误 + 6条正确表述（误报控制测试），12/12 命中、0误报
- 一键验证输出两行 `[PASS]`

## 目录结构

- `agents/` 流水线编排 + LLM智能体（抽取/裁决/报告）
- `prompts/` 提示词库（版本化：claim_extractor / adjudicator / report_writer / 对比实验提示词）
- `tools/` LLM客户端(含缓存)、docx/PDF解析、事实库、确定性核查引擎、审计日志
- `evaluation/` 评测模块（支持 docx/JSON 标准答案）
- `ui/` Streamlit 可视化界面（`ui/assets/` 图标资源）
- `data/samples/` 可复现样例（草稿01/02、年报、股价快照）
- `data/benchmark/` 草稿02标准答案 JSON
- `data/expected/` 复现基线
- `data/cache/` LLM 结果缓存（随仓库提交，保证离线复现）
- `docs/` 5分钟视频脚本
- `test/` 草稿01标准答案与原始测试材料（仅评测使用，正式提交时需移除）
- `scripts/` CLI、评测、复现验证、对比实验、计划书生成

## 第三方清单（合规披露）

| 名称 | 版本 | 用途 | 许可/说明 |
|---|---|---|---|
| DeepSeek `deepseek-flash` | API服务 | 核心推理引擎 | 商业API，HTTPS `POST /chat/completions`，不提交模型权重 |
| PyMuPDF | 1.28.2 | PDF文本提取 | AGPL-3.0（双许可） |
| pdfplumber | 0.11.10 | PDF表格解析 | MIT |
| python-docx | 1.2.0 | 研报草稿解析 | MIT |
| pandas | 3.0.6 | 数据处理 | BSD-3-Clause |
| numpy | 2.5.3 | 数值计算 | BSD-3-Clause |
| streamlit | 1.64.0 | 可视化界面 | Apache-2.0 |
| requests | 2.34.2 | LLM API调用 | Apache-2.0 |
| python-dotenv | 1.2.4 | 环境变量加载 | BSD-3-Clause |

数据说明：样例年报为巨潮资讯网公开披露文件，仅用于竞赛评测；研报草稿与植入错误由参赛队自建。
