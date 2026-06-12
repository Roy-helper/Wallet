# Wallet 个人财务系统

这是一个本地个人财务系统。当用户在会话里讨论记账、账单、消费、资产配置时，
优先通过 `wallet` CLI 操作结构化数据，不要凭空估算。

## 常用命令

```bash
wallet import inbox/              # 导入用户丢进 inbox/ 的账单（自动识别微信/支付宝）
wallet categorize --json          # 查看规则未识别的商户清单（JSON）
wallet categorize --llm           # 用 Claude API 给未识别商户分类（需 ANTHROPIC_API_KEY）
wallet report 2026-06 --json      # 月度数据（JSON），不带 --json 则生成 Markdown 到 reports/
wallet snapshot add <账户> <类别> <市值>   # 类别: cash/deposit/fund/stock/bond/gold/insurance/real_estate/crypto/other
wallet snapshot list --json
wallet advise --dry-run           # 输出财务数据摘要（资产配置+现金流），适合直接读取后给建议
wallet web                        # 本地仪表盘 http://127.0.0.1:8016
```

## 给建议时的约定

- 回答资产配置/消费分析问题前，先运行 `wallet advise --dry-run` 拿真实数据。
- 用户报告新的账户余额时，用 `wallet snapshot add` 记录下来。
- 帮用户修正分类时，把规律写进 `config/rules.yaml`（手写规则优先于
  `config/rules.learned.yaml` 中 LLM 学到的规则）。
- 不推荐具体个股/基金产品，只谈资产类别与比例；结尾注明不构成投资建议。

## 开发

- Python 3.10+，金额一律以"分"为单位的整数（`amount_cents`）存储。
- 测试：`python -m pytest tests/ -q`，新解析器必须带样例账单 fixture。
- 去重靠 `Txn.fingerprint`（优先渠道交易单号），改导入器时别破坏指纹稳定性。
- `data/` 和 `inbox/` 含敏感数据且已 gitignore，绝不提交。
