"""支付宝交易明细 CSV 解析。

导出路径：支付宝 App -> 我的 -> 账单 -> ... -> 开具交易流水证明 / 网页版下载。
文件前若干行是元信息，表头行以"交易时间"开头，列（新版个人账单）：
交易时间,交易分类,交易对方,对方账号,商品说明,收/支,金额,收/付款方式,交易状态,交易订单号,商家订单号,备注
"""

import csv
import io

from ..models import Txn, parse_cents


def _clean(s: str) -> str:
    return (s or "").strip().strip('"').strip("\t").strip()


def parse(text: str) -> list[Txn]:
    lines = text.splitlines()
    try:
        header_idx = next(i for i, l in enumerate(lines) if l.strip().strip('"').startswith("交易时间"))
    except StopIteration:
        raise ValueError("未找到支付宝账单表头行（应以'交易时间'开头）")

    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))
    txns = []
    for row in reader:
        row = {_clean(k): _clean(v) for k, v in row.items() if k}
        if not row.get("交易时间"):
            continue
        status = row.get("交易状态", "")
        if status and ("关闭" in status or "失败" in status):
            continue
        flow = row.get("收/支", "")
        cents = parse_cents(row.get("金额", "0"))
        if flow == "支出":
            direction, amount = "expense", -cents
        elif flow == "收入":
            direction, amount = "income", cents
        else:  # 不计收支：余额宝转入转出等
            direction, amount = "transfer", cents
        txns.append(Txn(
            time=row["交易时间"],
            amount_cents=amount,
            direction=direction,
            counterparty=row.get("交易对方", ""),
            description=row.get("商品说明", "") or row.get("交易分类", ""),
            method=row.get("收/付款方式", ""),
            source="alipay",
            txn_id=row.get("交易订单号", "") or row.get("商家订单号", ""),
            raw=row,
        ))
    return txns
