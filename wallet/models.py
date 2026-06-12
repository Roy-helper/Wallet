"""统一交易模型与去重指纹。"""

import hashlib
import json
from dataclasses import dataclass, field


@dataclass
class Txn:
    time: str                 # "2026-05-30 12:01:23"
    amount_cents: int         # 收入为正，支出为负
    direction: str            # income / expense / transfer
    counterparty: str = ""
    description: str = ""
    method: str = ""
    source: str = ""          # wechat / alipay / bank:xxx
    txn_id: str = ""          # 渠道交易单号（去重首选）
    raw: dict = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        # 渠道交易单号全局唯一，优先用它；没有则退化为内容指纹
        if self.txn_id:
            key = f"{self.source}|{self.txn_id}"
        else:
            key = f"{self.source}|{self.time}|{self.amount_cents}|{self.counterparty}|{self.description}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()


def parse_cents(text: str) -> int:
    """'¥23.50' / '23.5' / '1,234.00' -> 2350 / 2350 / 123400"""
    cleaned = text.strip().replace("¥", "").replace("￥", "").replace(",", "")
    if not cleaned:
        return 0
    negative = cleaned.startswith("-")
    cleaned = cleaned.lstrip("+-")
    whole, _, frac = cleaned.partition(".")
    cents = int(whole or 0) * 100 + int((frac + "00")[:2] or 0)
    return -cents if negative else cents


def save_txns(conn, txns, source_file: str = "") -> tuple[int, int]:
    """入库并按指纹去重，返回 (新增, 跳过)。"""
    added = skipped = 0
    for t in txns:
        try:
            conn.execute(
                "INSERT INTO transactions (fingerprint, time, amount_cents, direction,"
                " counterparty, description, method, source, source_file, raw)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (t.fingerprint, t.time, t.amount_cents, t.direction, t.counterparty,
                 t.description, t.method, t.source, source_file,
                 json.dumps(t.raw, ensure_ascii=False)),
            )
            added += 1
        except Exception as e:
            if "UNIQUE" in str(e):
                skipped += 1
            else:
                raise
    conn.commit()
    return added, skipped
