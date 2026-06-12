"""微信支付账单 CSV 解析。

导出路径：微信 -> 我 -> 服务 -> 钱包 -> 账单 -> 常见问题 -> 下载账单 -> 用于个人对账。
文件前若干行是元信息，表头行以"交易时间"开头，列：
交易时间,交易类型,交易对方,商品,收/支,金额(元),支付方式,当前状态,交易单号,商户单号,备注
"""

import csv
import io

from ..models import Txn, parse_cents


def _clean(s: str) -> str:
    # 微信在单号后面附加 \t 防止 Excel 科学计数
    return (s or "").strip().strip('"').strip("\t").strip()


def parse(text: str) -> list[Txn]:
    lines = text.splitlines()
    try:
        header_idx = next(i for i, l in enumerate(lines) if l.strip().strip('"').startswith("交易时间"))
    except StopIteration:
        raise ValueError("未找到微信账单表头行（应以'交易时间'开头）")

    reader = csv.DictReader(io.StringIO("\n".join(lines[header_idx:])))
    txns = []
    for row in reader:
        row = {_clean(k): _clean(v) for k, v in row.items() if k}
        if not row.get("交易时间"):
            continue
        flow = row.get("收/支", "")
        cents = parse_cents(row.get("金额(元)", "0"))
        if flow == "支出":
            direction, amount = "expense", -cents
        elif flow == "收入":
            direction, amount = "income", cents
        else:  # "/" —— 零钱提现、理财通转入等资金内部流转
            direction, amount = "transfer", cents
        txns.append(Txn(
            time=row["交易时间"],
            amount_cents=amount,
            direction=direction,
            counterparty=row.get("交易对方", ""),
            description=row.get("商品", "") or row.get("交易类型", ""),
            method=row.get("支付方式", ""),
            source="wechat",
            txn_id=row.get("交易单号", ""),
            raw=row,
        ))
    return txns
