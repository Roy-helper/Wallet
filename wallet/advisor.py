"""资产配置顾问：基于真实快照 + 现金流数据生成数据摘要，再交给 Claude 给建议。

设计原则：摘要（digest）本身就是独立产物 —— `wallet advise --dry-run` 输出纯数据摘要，
可以直接喂给任何 agent（比如在 Claude Code 会话里讨论）；配好 ANTHROPIC_API_KEY 后
`wallet advise` 则直接调用 Claude 生成建议报告。
"""

from datetime import datetime

from .db import fmt_yuan
from .report import monthly_series

ASSET_CLASS_NAMES = {
    "cash": "现金/活期", "deposit": "定期存款", "fund": "基金", "stock": "股票",
    "bond": "债券", "gold": "黄金", "insurance": "保险", "real_estate": "房产",
    "crypto": "加密资产", "other": "其他",
}

SYSTEM_PROMPT = """你是一位谨慎的个人财务顾问，服务中国大陆的个人用户。
基于用户提供的真实资产快照和现金流数据，给出资产配置分析与建议。要求：
1. 先用一两句话总结当前财务状况的核心特征。
2. 分析当前资产配置的结构性问题：流动性（应急资金是否够 3-6 个月支出）、集中度风险、与现金流的匹配度。
3. 给出 2-4 条具体、可执行的调整建议，每条说明理由和大致幅度，避免空话。
4. 基于储蓄率和支出结构，指出 1-2 个最值得优化的支出方向（如果有）。
5. 语气克制，不夸大收益，不推荐具体的个股或具体基金产品，只谈资产类别和比例。
6. 结尾注明：以上为基于数据的一般性分析，不构成投资建议。"""


def build_digest(conn, months: int = 6) -> str:
    """把数据库浓缩成一页纸的数据摘要（Markdown）。"""
    lines = [f"# 财务数据摘要（生成于 {datetime.now():%Y-%m-%d}）", ""]

    snap_date = conn.execute("SELECT MAX(date) d FROM snapshots").fetchone()["d"]
    if snap_date:
        rows = conn.execute(
            """SELECT asset_class, SUM(value_cents) cents FROM snapshots
               WHERE date=? GROUP BY asset_class ORDER BY cents DESC""", (snap_date,)
        ).fetchall()
        total = sum(r["cents"] for r in rows) or 1
        lines += [f"## 资产配置（{snap_date} 快照）", "",
                  f"净资产合计: ¥{fmt_yuan(total)}", "",
                  "| 资产类别 | 市值 | 占比 |", "|---|---:|---:|"]
        for r in rows:
            name = ASSET_CLASS_NAMES.get(r["asset_class"], r["asset_class"])
            lines.append(f"| {name} | ¥{fmt_yuan(r['cents'])} | {r['cents'] / total * 100:.1f}% |")
        accounts = conn.execute(
            "SELECT account, asset_class, value_cents FROM snapshots WHERE date=? ORDER BY value_cents DESC",
            (snap_date,),
        ).fetchall()
        lines += ["", "明细账户: " + "；".join(
            f"{a['account']}({ASSET_CLASS_NAMES.get(a['asset_class'], a['asset_class'])}) ¥{fmt_yuan(a['value_cents'])}"
            for a in accounts)]
    else:
        lines += ["## 资产配置", "", "（尚无资产快照，请先 `wallet snapshot add` 录入各账户市值）"]

    series = monthly_series(conn, months)
    if series:
        lines += ["", f"## 近 {len(series)} 个月现金流", "",
                  "| 月份 | 收入 | 支出 | 结余 | 储蓄率 |", "|---|---:|---:|---:|---:|"]
        for s in series:
            balance = s["income"] - s["expense"]
            rate = f"{balance / s['income'] * 100:.0f}%" if s["income"] > 0 else "—"
            lines.append(f"| {s['ym']} | ¥{fmt_yuan(s['income'])} | ¥{fmt_yuan(s['expense'])} "
                         f"| ¥{fmt_yuan(balance)} | {rate} |")
        avg_expense = sum(s["expense"] for s in series) / len(series)
        lines += ["", f"月均支出: ¥{fmt_yuan(int(avg_expense))}"]

        cat_rows = conn.execute(
            """SELECT COALESCE(category,'未分类') category, -SUM(amount_cents) cents
               FROM transactions WHERE direction='expense' AND substr(time,1,7) >= ?
               GROUP BY category ORDER BY cents DESC LIMIT 10""",
            (series[0]["ym"],),
        ).fetchall()
        if cat_rows:
            lines += ["", "## 同期支出结构 Top 10", "", "| 分类 | 金额 |", "|---|---:|"]
            lines += [f"| {r['category']} | ¥{fmt_yuan(r['cents'])} |" for r in cat_rows]
    else:
        lines += ["", "## 现金流", "", "（尚无交易数据，请先 `wallet import` 导入账单）"]

    return "\n".join(lines) + "\n"


def advise(conn, months: int = 6, model: str = "claude-opus-4-8") -> str:
    """调用 Claude 基于数据摘要生成配置建议。需要 ANTHROPIC_API_KEY。"""
    import anthropic

    digest = build_digest(conn, months)
    client = anthropic.Anthropic()
    # 建议属于长输出，按官方推荐走流式；adaptive thinking 让模型自行决定思考深度
    with client.messages.stream(
        model=model,
        max_tokens=64000,
        thinking={"type": "adaptive"},
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"这是我的财务数据，请给出分析和资产配置建议：\n\n{digest}"}],
    ) as stream:
        message = stream.get_final_message()

    advice = "".join(block.text for block in message.content if block.type == "text")
    return (f"# 资产配置建议（{datetime.now():%Y-%m-%d}）\n\n"
            f"{advice}\n\n---\n\n## 附：本次分析所用数据\n\n{digest}")
