"""月报：收支结构、分类占比、环比、大额交易、净资产。输出 Markdown 或 JSON。"""

from datetime import datetime

from .categorize import TRANSFER_CATEGORY
from .db import fmt_yuan

BIG_TXN_CENTS = 50000  # 大额交易阈值：500 元


def _month_range(ym: str) -> tuple[str, str]:
    y, m = map(int, ym.split("-"))
    nxt = f"{y + 1}-01" if m == 12 else f"{y}-{m + 1:02d}"
    return f"{ym}-01 00:00:00", f"{nxt}-01 00:00:00"


def _prev_month(ym: str) -> str:
    y, m = map(int, ym.split("-"))
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


def month_data(conn, ym: str) -> dict:
    start, end = _month_range(ym)

    def q(sql, *args):
        return conn.execute(sql, (start, end, *args)).fetchall()

    income = q("SELECT COALESCE(SUM(amount_cents),0) s FROM transactions"
               " WHERE time>=? AND time<? AND direction='income'")[0]["s"]
    expense = -q("SELECT COALESCE(SUM(amount_cents),0) s FROM transactions"
                 " WHERE time>=? AND time<? AND direction='expense'")[0]["s"]
    by_category = [dict(r) for r in q(
        """SELECT COALESCE(category,'未分类') category, -SUM(amount_cents) cents, COUNT(*) n
           FROM transactions WHERE time>=? AND time<? AND direction='expense'
           GROUP BY category ORDER BY cents DESC""")]
    top_merchants = [dict(r) for r in q(
        """SELECT counterparty, -SUM(amount_cents) cents, COUNT(*) n
           FROM transactions WHERE time>=? AND time<? AND direction='expense' AND counterparty != ''
           GROUP BY counterparty ORDER BY cents DESC LIMIT 10""")]
    big_txns = [dict(r) for r in q(
        """SELECT time, counterparty, description, -amount_cents cents,
                  COALESCE(category,'未分类') category
           FROM transactions WHERE time>=? AND time<? AND direction='expense' AND amount_cents<=?
           ORDER BY amount_cents ASC LIMIT 20""", -BIG_TXN_CENTS)]
    uncategorized = q("SELECT COUNT(*) n FROM transactions"
                      " WHERE time>=? AND time<? AND category IS NULL")[0]["n"]

    # 最近一次资产快照（截至本月末）
    snap_date = conn.execute(
        "SELECT MAX(date) d FROM snapshots WHERE date < ?", (end[:10],)
    ).fetchone()["d"]
    net_worth = None
    if snap_date:
        net_worth = conn.execute(
            "SELECT COALESCE(SUM(value_cents),0) s FROM snapshots WHERE date=?", (snap_date,)
        ).fetchone()["s"]

    return {
        "month": ym,
        "income_cents": income,
        "expense_cents": expense,
        "balance_cents": income - expense,
        "savings_rate": round((income - expense) / income, 4) if income > 0 else None,
        "by_category": by_category,
        "top_merchants": top_merchants,
        "big_transactions": big_txns,
        "uncategorized_count": uncategorized,
        "net_worth_cents": net_worth,
        "net_worth_date": snap_date,
    }


def render_markdown(conn, ym: str) -> str:
    cur = month_data(conn, ym)
    prev = month_data(conn, _prev_month(ym))
    prev_by_cat = {c["category"]: c["cents"] for c in prev["by_category"]}

    def mom(now: int, before: int) -> str:
        if before <= 0:
            return "—"
        pct = (now - before) / before * 100
        return f"{'+' if pct >= 0 else ''}{pct:.0f}%"

    lines = [
        f"# {cur['month']} 月度财务报告",
        "",
        f"*生成时间: {datetime.now():%Y-%m-%d %H:%M}*",
        "",
        "## 总览",
        "",
        "| 指标 | 本月 | 环比 |",
        "|---|---:|---:|",
        f"| 收入 | ¥{fmt_yuan(cur['income_cents'])} | {mom(cur['income_cents'], prev['income_cents'])} |",
        f"| 支出 | ¥{fmt_yuan(cur['expense_cents'])} | {mom(cur['expense_cents'], prev['expense_cents'])} |",
        f"| 结余 | ¥{fmt_yuan(cur['balance_cents'])} | |",
    ]
    if cur["savings_rate"] is not None:
        lines.append(f"| 储蓄率 | {cur['savings_rate'] * 100:.1f}% | |")
    if cur["net_worth_cents"] is not None:
        lines.append(f"| 净资产（{cur['net_worth_date']} 快照） | ¥{fmt_yuan(cur['net_worth_cents'])} | |")

    lines += ["", "## 支出分类", "", "| 分类 | 金额 | 占比 | 笔数 | 环比 |", "|---|---:|---:|---:|---:|"]
    total = cur["expense_cents"] or 1
    for c in cur["by_category"]:
        lines.append(
            f"| {c['category']} | ¥{fmt_yuan(c['cents'])} | {c['cents'] / total * 100:.1f}% "
            f"| {c['n']} | {mom(c['cents'], prev_by_cat.get(c['category'], 0))} |"
        )

    if cur["top_merchants"]:
        lines += ["", "## 消费最多的商户 Top 10", "", "| 商户 | 金额 | 笔数 |", "|---|---:|---:|"]
        lines += [f"| {m['counterparty']} | ¥{fmt_yuan(m['cents'])} | {m['n']} |" for m in cur["top_merchants"]]

    if cur["big_transactions"]:
        lines += ["", f"## 大额支出（≥ ¥{BIG_TXN_CENTS // 100}）", "",
                  "| 时间 | 对方 | 描述 | 分类 | 金额 |", "|---|---|---|---|---:|"]
        lines += [
            f"| {t['time'][:10]} | {t['counterparty']} | {t['description'][:20]} "
            f"| {t['category']} | ¥{fmt_yuan(t['cents'])} |"
            for t in cur["big_transactions"]
        ]

    if cur["uncategorized_count"]:
        lines += ["", f"> ⚠️ 本月还有 **{cur['uncategorized_count']}** 笔交易未分类，"
                      "运行 `wallet categorize`（或加 `--llm`）后重新生成报告。"]
    return "\n".join(lines) + "\n"


def monthly_series(conn, months: int = 12) -> list[dict]:
    """近 N 个月收支序列，供趋势图与顾问使用。"""
    rows = conn.execute(
        f"""SELECT substr(time,1,7) ym,
              SUM(CASE WHEN direction='income' THEN amount_cents ELSE 0 END) income,
              -SUM(CASE WHEN direction='expense' THEN amount_cents ELSE 0 END) expense
            FROM transactions WHERE direction IN ('income','expense')
            GROUP BY ym ORDER BY ym DESC LIMIT {int(months)}"""
    ).fetchall()
    return [dict(r) for r in reversed(rows)]
