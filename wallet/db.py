"""SQLite 数据层：交易表 + 资产快照表。金额以"分"为单位的整数存储，避免浮点误差。"""

import os
import sqlite3
from pathlib import Path

DEFAULT_DB = "data/wallet.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id           INTEGER PRIMARY KEY,
    fingerprint  TEXT UNIQUE NOT NULL,
    time         TEXT NOT NULL,            -- ISO8601: 2026-05-30 12:01:23
    amount_cents INTEGER NOT NULL,         -- 收入为正，支出为负，单位：分
    direction    TEXT NOT NULL,            -- income / expense / transfer
    counterparty TEXT DEFAULT '',
    description  TEXT DEFAULT '',
    method       TEXT DEFAULT '',          -- 支付方式
    category     TEXT,                     -- NULL = 未分类
    source       TEXT NOT NULL,            -- wechat / alipay / bank:xxx
    source_file  TEXT DEFAULT '',
    raw          TEXT DEFAULT '',          -- 原始行 JSON，便于追溯
    created_at   TEXT DEFAULT (datetime('now', 'localtime'))
);
CREATE INDEX IF NOT EXISTS idx_txn_time ON transactions(time);
CREATE INDEX IF NOT EXISTS idx_txn_category ON transactions(category);

CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY,
    date        TEXT NOT NULL,             -- YYYY-MM-DD
    account     TEXT NOT NULL,             -- 账户名，如 招行储蓄 / 蛋卷基金
    asset_class TEXT NOT NULL,             -- cash/deposit/fund/stock/bond/gold/insurance/real_estate/crypto/other
    value_cents INTEGER NOT NULL,          -- 市值，单位：分（负债记负数）
    note        TEXT DEFAULT '',
    UNIQUE(date, account)
);
CREATE INDEX IF NOT EXISTS idx_snap_date ON snapshots(date);
"""


def get_db(path: str | None = None) -> sqlite3.Connection:
    path = path or os.environ.get("WALLET_DB", DEFAULT_DB)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def fmt_yuan(cents: int) -> str:
    return f"{cents / 100:,.2f}"
