import os
import sqlite3
from pathlib import Path

import pytest

from wallet.categorize import apply_rules, match_category, load_rules
from wallet.db import SCHEMA
from wallet.importers import detect_format, read_text
from wallet.importers.alipay import parse as parse_alipay
from wallet.importers.wechat import parse as parse_wechat
from wallet.models import parse_cents, save_txns
from wallet.report import month_data, monthly_series, render_markdown

DATA = Path(__file__).parent / "data"


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def test_parse_cents():
    assert parse_cents("¥23.50") == 2350
    assert parse_cents("1,234.00") == 123400
    assert parse_cents("-18.8") == -1880
    assert parse_cents("8000") == 800000
    assert parse_cents("") == 0


def test_detect_format():
    assert detect_format(read_text(str(DATA / "sample_wechat.csv"))) == "wechat"
    assert detect_format(read_text(str(DATA / "sample_alipay.csv"))) == "alipay"


def test_wechat_parse():
    txns = parse_wechat(read_text(str(DATA / "sample_wechat.csv")))
    assert len(txns) == 8
    expense = [t for t in txns if t.direction == "expense"]
    income = [t for t in txns if t.direction == "income"]
    transfer = [t for t in txns if t.direction == "transfer"]
    assert len(expense) == 5 and len(income) == 2 and len(transfer) == 1
    assert sum(-t.amount_cents for t in expense) == 49230  # 712.30 减去... 检查实际和
    assert sum(t.amount_cents for t in income) == 808800
    meituan = next(t for t in txns if "美团" in t.counterparty)
    assert meituan.amount_cents == -2350
    assert meituan.txn_id == "4200001234202605301111111111"  # \t 已被清理


def test_alipay_parse():
    txns = parse_alipay(read_text(str(DATA / "sample_alipay.csv")))
    # 7 行里有 1 行"交易关闭"被跳过
    assert len(txns) == 6
    assert next(t for t in txns if "饿了么" in t.counterparty).amount_cents == -3200
    assert next(t for t in txns if "余额宝" in t.counterparty).direction == "transfer"
    refund = next(t for t in txns if t.direction == "income")
    assert refund.amount_cents == 9900


def test_dedup(conn):
    txns = parse_wechat(read_text(str(DATA / "sample_wechat.csv")))
    added, skipped = save_txns(conn, txns)
    assert (added, skipped) == (8, 0)
    added, skipped = save_txns(conn, txns)  # 重复导入
    assert (added, skipped) == (0, 8)


def test_categorize_rules(conn, monkeypatch):
    monkeypatch.chdir(Path(__file__).parent.parent)  # 让 config/rules.yaml 可见
    txns = parse_wechat(read_text(str(DATA / "sample_wechat.csv")))
    txns += parse_alipay(read_text(str(DATA / "sample_alipay.csv")))
    save_txns(conn, txns)
    apply_rules(conn)
    cats = {r["counterparty"]: r["category"] for r in conn.execute(
        "SELECT counterparty, category FROM transactions")}
    assert cats["美团平台商户"] == "餐饮"
    assert cats["滴滴出行"] == "交通"
    assert cats["余额宝"] == "转账"  # transfer 方向直接标记
    assert cats["某某公司"] == "工资收入"


def test_report(conn, monkeypatch):
    monkeypatch.chdir(Path(__file__).parent.parent)
    txns = parse_wechat(read_text(str(DATA / "sample_wechat.csv")))
    save_txns(conn, txns)
    apply_rules(conn)
    data = month_data(conn, "2026-05")
    assert data["income_cents"] == 808800
    assert data["expense_cents"] == 49230
    assert data["balance_cents"] == 808800 - 49230
    # 转账（零钱提现）不计入收支
    md = render_markdown(conn, "2026-05")
    assert "月度财务报告" in md and "餐饮" in md
    series = monthly_series(conn, 12)
    assert series[-1]["ym"] == "2026-05"


def test_match_category_priority(monkeypatch):
    monkeypatch.chdir(Path(__file__).parent.parent)
    _, rules = load_rules()
    assert match_category("美团平台商户 外卖订单", rules) == "餐饮"
    assert match_category("未知商户XYZ 不知道是啥", rules) is None
