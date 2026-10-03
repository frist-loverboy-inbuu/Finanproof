# Finanproof

金融研报纠错核查系统 = **大语言模型多智能体（推理引擎）+ 确定性计算工具 + 证据链**。
北京市大学生金融人工智能竞赛参赛作品，赛题5：研究报告纠错核查。

对研报草稿中的收入、利润、估值倍数、单位、统计口径、引用与风险披露进行核查，输出结构化错误清单、原文证据定位与可执行修改建议，全过程记录审计日志，结果可复现。

## 系统架构

```
研报草稿(.docx) ──> 事实抽取智能体(LLM)          <── 提示词库 prompts/*.v1.txt
原始年报(.pdf)  ──> 证据工具（确定性）：            事实库解析 / 数值重算 / 单位换算 /
                     原文检索 / 证据定位
                          │
             核查候选（规则+工具产出，共13条，含证据与页码）
                          │
             裁决智能体(LLM)：逐条确认/拒绝、定错误类型与严重度、改写修改建议
                          │
             报告生成智能体(LLM)：输出核查总结
                          │
   错误清单 JSON/CSV/MD + 证据链 + 审计日志(JSONL) + LLM调用日志 + 结果缓存
```

- 推理引擎：**DeepSeek `deepseek-flash`**（国产大模型，OpenAI兼容接口，通过 `tools/llm_client.py` 调用）
- 数字一律来自确定性工具，LLM 不心算；每条结论必须附原文证据，否则回退规则引擎
- LLM 调用 `temperature=0` 并启用结果缓存，保证可复现

## Docker 一键运行（推荐）

```bash
docker compose up --build
```
浏览器打开 http://localhost:8501。停止：`docker compose down`。

容器内复现验证：
```bash
docker run --rm finanproof python scripts/verify_reproduce.py
```

说明：
- 镜像含样例数据、复现基线与 LLM 结果缓存，**无需 API key、无需联网即可复现**
- 国内构建若拉取基础镜像失败：先 `docker pull docker.m.daocloud.io/library/python:3.12-slim` 与 `docker tag docker.m.daocloud.io/library/python:3.12-slim python:3.12-slim`，再重新构建

## 本地复现步骤（不用Docker）

**0. 环境**：Python 3.10+（推荐3.12），Windows / macOS / Linux。

**1. 安装依赖**
```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate
pip install -r requirements.txt
# 国内网络可加：-i https://mirrors.aliyun.com/pypi/simple/
```
严格固定版本：`pip install -r requirements.lock.txt`。

**2. 一键复现验证**（无需上传文件、无需 API key、无需联网）
```bash
python scripts/verify_reproduce.py
```
预期输出：
```
[PASS] 复现成功：核查输出与基线完全一致（13 条错误）
[PASS] 对照标准答案：Recall 13/13，Precision 100%，F1 100%，证据定位 100%
```

**3. 可视化复现**
```bash
streamlit run ui/app.py
```
浏览器打开 http://localhost:8501，在左侧上传 `data/samples/` 下的三个文件：
- `研报草稿_贵州茅台.docx`（含13处植入错误）
- `年报_贵州茅台2024.pdf`（公开披露年报）
- `price_snapshot.json`（股价快照，用于估值倍数核查）

点击「开始核查」，查看核查总结、错误清单、证据与修改、事实库、审计日志；「对照评测」标签页可复算指标。

## 关于 LLM 与复现

| 模式 | 条件 | 行为 |
|---|---|---|
| 在线推理 | `.env` 配置 `DEEPSEEK_API_KEY` | 真实调用 deepseek-flash，结果写入缓存 |
| 缓存复现 | 缓存已存在（随仓库提交） | 直接读缓存，**离线、零成本、结果一致** |
| 回退模式 | 无 key 且缓存缺失 | 自动回退确定性规则引擎，系统仍可运行 |

`.env` 配置参考 `.env.example`（key 不提交、不入镜像）。

## 其他运行方式

```bash
python scripts/run_cli.py      # 命令行核查
python scripts/run_eval.py     # 对照标准答案评测（需要 test/ 答案文件）
```

## 核查错误类型

E01 核心数值 / E02 计算 / E03 单位 / E04 期间 / E05 口径 / E06 方向性 / E07 引用 / E08 主体 / E09 遗漏风险 / E10 表述不严谨。

## 目录结构

- `agents/` 流水线编排 + LLM智能体（事实抽取/裁决/报告）
- `prompts/` 提示词库（带版本号）
- `tools/` LLM客户端(含缓存)、docx/PDF解析、事实库、确定性核查引擎、审计日志
- `evaluation/` 对照错误注入答案的评测（Recall/Precision/F1/证据定位）
- `ui/` Streamlit 可视化界面
- `data/samples/` 可复现样例
- `data/expected/` 复现基线
- `data/cache/` LLM 结果缓存（随仓库提交，保证离线复现）
- `test/` 标准答案与原始测试材料（仅评测使用，正式提交时需移除）

## 内置样例评测结果（贵州茅台2024）

- 标准答案 13 条错误（E01–E10 全覆盖）
- Recall 13/13 = 100%，Precision 100%（0 误报），F1 100%，证据定位 100%
- 4 条正确表述（经营现金流 +38.85%、净资产 2,331.06亿、管理费用 -4.25%、2023年归母 747.34亿）零误报
- LLM 裁决：候选 13 条全部确认，0 拒绝，0 回退

## 第三方清单（合规披露）

| 名称 | 版本 | 用途 | 许可/说明 |
|---|---|---|---|
| DeepSeek `deepseek-flash` | API服务 | 核心推理引擎（含事实抽取/裁决/报告生成） | 商业API，调用方式：HTTPS `POST /chat/completions`，不提交模型权重 |
| PyMuPDF | 1.28.2 | PDF文本提取 | AGPL-3.0（双许可） |
| pdfplumber | 0.11.10 | PDF表格解析 | MIT |
| python-docx | 1.2.0 | 研报草稿解析 | MIT |
| pandas | 3.0.6 | 数据处理 | BSD-3-Clause |
| numpy | 2.5.3 | 数值计算 | BSD-3-Clause |
| streamlit | 1.64.0 | 可视化界面 | Apache-2.0 |
| requests | 2.34.2 | LLM API调用 | Apache-2.0 |
| python-dotenv | 1.2.4 | 环境变量加载 | BSD-3-Clause |

数据说明：样例年报为巨潮资讯网公开披露文件（仅用于竞赛评测）；股价快照为评测样例数据；研报草稿与植入错误由参赛队自建。
