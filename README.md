# Wallet — 个人财务系统

把微信支付 / 支付宝 / 银行卡账单导入本地 SQLite，自动分类整理，生成月报和资产配置建议。

核心设计：**确定性的事交给代码，模糊的事交给 LLM，且 LLM 的判断沉淀为规则。**
解析、去重、入账、报表全部本地确定性完成；只有规则库没见过的商户才会问 Claude，
分类结果回写规则库（`config/rules.learned.yaml`），系统越用越准、LLM 成本趋零。

## 安装

```bash
pip install -e .          # 基础功能（导入/分类/报表/仪表盘）
pip install -e ".[llm]"   # 加上 LLM 分类兜底和资产配置建议
```

## 日常使用

```bash
# 1. 导出账单，丢进 inbox/
#    微信: 我 -> 服务 -> 钱包 -> 账单 -> 常见问题 -> 下载账单（用于个人对账）
#    支付宝: App -> 我的 -> 账单 -> 右上角 -> 开具交易流水证明
wallet import inbox/                  # 自动识别格式、去重入库、跑规则分类

# 2. 规则没认出来的商户，让 Claude 兜底（需 ANTHROPIC_API_KEY）
wallet categorize --llm

# 3. 生成月报（Markdown，存到 reports/）
wallet report 2026-06

# 4. 本地仪表盘：收支趋势、分类占比、净资产曲线
wallet web                            # http://127.0.0.1:8016
```

银行流水格式各异，在 `config/banks.yaml` 配好列映射后：
`wallet import 流水.csv --format generic --bank cmb_debit`

## 资产配置建议

先定期记录各账户市值（建议每月一次）：

```bash
wallet snapshot add 招行储蓄 cash 52000
wallet snapshot add 蛋卷基金 fund 30000
wallet snapshot add 余额宝 cash 8000
```

然后：

```bash
wallet advise             # 调用 Claude，基于真实资产结构+现金流给建议，存 reports/
wallet advise --dry-run   # 只输出数据摘要，可贴给任何 agent 分析
```

## 隐私

- 所有数据存本地 `data/wallet.db`，仪表盘只监听 127.0.0.1。
- `inbox/`（原始账单）和 `data/` 默认在 `.gitignore` 中，不会被提交。
- LLM 分类兜底只发送**商户名和商品描述**，不发送金额、时间、单号。
- `wallet advise` 会把资产配置和现金流汇总数据发给 Claude API；不想发就用 `--dry-run`。

## Agent 接入

所有查询类命令支持 `--json` 输出，Web 端有同构 JSON API（`/api/trend`、`/api/month/<ym>`、
`/api/networth`、`/api/transactions`），可直接给 agent 调用。在 Claude Code 里打开本仓库
即可对话式记账和咨询（见 `CLAUDE.md`）。后续计划：MCP server 封装、飞书 bot 收发。

## 项目结构

```
wallet/
  importers/      # 微信 / 支付宝 / 通用银行 CSV 解析，指纹去重
  categorize.py   # 规则引擎 + Claude 分类兜底（结果固化为规则）
  report.py       # 月报：收支、分类占比、环比、大额交易
  advisor.py      # 数据摘要 + Claude 资产配置建议
  web.py          # Flask 仪表盘（Chart.js）
  cli.py          # 命令行入口
config/
  rules.yaml          # 手写分类规则（优先级最高）
  rules.learned.yaml  # LLM 学到的规则（自动生成）
  banks.yaml          # 银行流水列映射
```
