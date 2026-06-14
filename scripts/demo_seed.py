"""生成演示数据，便于第一次启动仪表盘时直接看到效果。

用法: python scripts/demo_seed.py [db_path]
所有数据均为虚构，仅用于演示图表与报表。不会污染真实库（默认写到 data/demo.db）。
"""

import random
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, ".")
from wallet.categorize import apply_rules
from wallet.db import get_db
from wallet.models import Txn, save_txns

random.seed(42)

# (商户, 描述, 金额区间元, 平均每月笔数, source)
MERCHANTS = [
    ("美团平台商户", "外卖订单", (15, 55), 12, "wechat"),
    ("饿了么", "午餐外卖", (18, 48), 8, "alipay"),
    ("瑞幸咖啡", "生椰拿铁", (10, 35), 10, "alipay"),
    ("滴滴出行", "滴滴快车", (12, 60), 6, "wechat"),
    ("中国石化", "加油", (200, 400), 1, "wechat"),
    ("京东商城平台商户", "日用品订单", (50, 600), 3, "wechat"),
    ("永辉超市", "生鲜商品", (60, 280), 4, "wechat"),
    ("盒马鲜生", "生鲜订单", (80, 320), 3, "alipay"),
    ("优衣库", "服饰", (99, 499), 1, "alipay"),
    ("猫眼电影", "电影票", (40, 120), 2, "wechat"),
    ("携程旅行", "酒店预订", (400, 1200), 1, "alipay"),
    ("国家电网", "电费", (80, 200), 1, "wechat"),
    ("中国移动", "话费充值", (50, 100), 1, "alipay"),
    ("某某诊所", "挂号问诊", (50, 300), 1, "wechat"),
    ("当当网", "图书订单", (40, 150), 1, "alipay"),
]


def seed(db_path: str = "data/demo.db"):
    conn = get_db(db_path)
    conn.execute("DELETE FROM transactions")
    conn.execute("DELETE FROM snapshots")
    conn.commit()

    today = date.today()
    txns = []
    for months_ago in range(7, -1, -1):  # 近 8 个月
        y, m = today.year, today.month - months_ago
        while m <= 0:
            m += 12
            y -= 1
        # 工资
        txns.append(Txn(time=f"{y}-{m:02d}-05 09:30:00", amount_cents=random.randint(18000, 22000) * 100,
                        direction="income", counterparty="某某公司", description="工资",
                        source="wechat", txn_id=f"salary-{y}{m:02d}"))
        # 偶尔的额外收入
        if random.random() < 0.3:
            txns.append(Txn(time=f"{y}-{m:02d}-18 14:00:00", amount_cents=random.randint(800, 3000) * 100,
                            direction="income", counterparty="某平台", description="兼职报酬",
                            source="alipay", txn_id=f"bonus-{y}{m:02d}"))
        # 各类支出
        for name, desc, (lo, hi), freq, source in MERCHANTS:
            for i in range(max(0, freq + random.randint(-2, 2))):
                day = random.randint(1, 27)
                yuan = random.randint(lo, hi)
                txns.append(Txn(
                    time=f"{y}-{m:02d}-{day:02d} {random.randint(8,21):02d}:{random.randint(0,59):02d}:00",
                    amount_cents=-yuan * 100, direction="expense",
                    counterparty=name, description=desc, source=source,
                    txn_id=f"{name}-{y}{m:02d}{day:02d}-{i}-{random.randint(1000,9999)}"))

    added, _ = save_txns(conn, txns)
    n = apply_rules(conn)
    print(f"已生成 {added} 笔交易，{n} 笔完成分类。")

    # 资产快照：现金随结余增长，基金有波动
    cash, fund, gold = 80000, 60000, 20000
    for months_ago in range(7, -1, -1):
        d = (today.replace(day=1) - timedelta(days=months_ago * 30)).replace(day=1)
        cash += random.randint(8000, 14000)
        fund = int(fund * random.uniform(0.97, 1.06)) + random.randint(2000, 5000)
        gold = int(gold * random.uniform(0.98, 1.04))
        for acct, cls, val in [("招行储蓄", "cash", cash), ("蛋卷基金", "fund", fund),
                               ("黄金积存", "gold", gold), ("信用卡欠款", "other", -random.randint(2000, 8000))]:
            conn.execute(
                "INSERT INTO snapshots (date, account, asset_class, value_cents) VALUES (?,?,?,?)"
                " ON CONFLICT(date,account) DO UPDATE SET value_cents=excluded.value_cents",
                (d.isoformat(), acct, cls, val * 100))
    conn.commit()
    total = conn.execute("SELECT SUM(value_cents) s FROM snapshots WHERE date=(SELECT MAX(date) FROM snapshots)").fetchone()["s"]
    print(f"已生成 8 个月资产快照，最新净资产 ¥{total/100:,.2f}。")
    print(f"\n启动仪表盘:  WALLET_DB={db_path} wallet web")


if __name__ == "__main__":
    seed(sys.argv[1] if len(sys.argv) > 1 else "data/demo.db")
