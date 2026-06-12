"""通用银行流水导入：各银行导出格式不一，用 config/banks.yaml 里的列映射配置驱动。

配置示例（config/banks.yaml）::

    cmb_debit:                      # wallet import 流水.csv --format generic --bank cmb_debit
      header_starts_with: 交易日期    # 表头行的起始文字（之前的行全部跳过）
      columns:
        time: 交易日期               # 必填
        amount: 交易金额             # 必填；正=收入 负=支出。若收支分列，用 income/expense 两项
        counterparty: 对方户名
        description: 摘要
        method: 交易渠道
        txn_id: 流水号
      time_format: "%Y%m%d"         # 可选，默认按原样保存
"""

import csv
import io
from datetime import datetime
from pathlib import Path

import yaml

from ..models import Txn, parse_cents

BANKS_CONFIG = "config/banks.yaml"


def load_bank_profiles(path: str = BANKS_CONFIG) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def parse(text: str, bank: str | None = None) -> list[Txn]:
    profiles = load_bank_profiles()
    if not bank or bank not in profiles:
        available = ", ".join(profiles) or "（空，请先在 config/banks.yaml 中添加）"
        raise ValueError(f"请用 --bank 指定银行配置，可用配置: {available}")
    prof = profiles[bank]
    cols = prof["columns"]

    lines = text.splitlines()
    marker = prof.get("header_starts_with", cols["time"])
    try:
        header_idx = next(i for i, l in enumerate(lines) if l.strip().strip('"').startswith(marker))
    except StopIteration:
        raise ValueError(f"未找到表头行（应以'{marker}'开头）")

    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))
    txns = []
    for row in reader:
        row = {(k or "").strip(): (v or "").strip() for k, v in row.items() if k}
        time_raw = row.get(cols["time"], "")
        if not time_raw:
            continue
        time_str = time_raw
        if prof.get("time_format"):
            time_str = datetime.strptime(time_raw, prof["time_format"]).strftime("%Y-%m-%d %H:%M:%S")

        if "amount" in cols:  # 单列正负金额
            amount = parse_cents(row.get(cols["amount"], "0"))
        else:                 # 收入/支出分列
            amount = parse_cents(row.get(cols.get("income", ""), "0")) \
                     - parse_cents(row.get(cols.get("expense", ""), "0"))
        if amount == 0:
            continue
        txns.append(Txn(
            time=time_str,
            amount_cents=amount,
            direction="income" if amount > 0 else "expense",
            counterparty=row.get(cols.get("counterparty", ""), ""),
            description=row.get(cols.get("description", ""), ""),
            method=row.get(cols.get("method", ""), ""),
            source=f"bank:{bank}",
            txn_id=row.get(cols.get("txn_id", ""), ""),
            raw=row,
        ))
    return txns
