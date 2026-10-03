# Finanproof

金融研报纠错核查智能体。北京市大学生金融人工智能竞赛参赛作品，赛题5：研究报告纠错核查。

## 目录

- `spikes/` 技术验证脚本
- `schema/` 数据结构契约
- `tools/` 解析、计算、检索工具
- `agents/` 智能体编排
- `prompts/` 提示词
- `data/raw` 原始材料（年报、研报）
- `data/benchmark` 错误注入测试集
- `data/output` 核查输出
- `evaluation/` 评测代码
- `ui/` 演示界面
- `logs/` 运行日志

## 环境

```
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

## 运行

```
.venv\Scripts\python spikes/parse_spike.py data/raw/xxx.pdf
.venv\Scripts\python tools/logger.py
```
