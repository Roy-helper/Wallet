"""账单导入器：自动识别微信/支付宝账单，银行流水走 generic 列映射。"""

from pathlib import Path

from ..models import save_txns
from . import alipay, generic, wechat

PARSERS = {
    "wechat": wechat.parse,
    "alipay": alipay.parse,
    "generic": generic.parse,
}


def read_text(path: str) -> str:
    """微信导出为 UTF-8，支付宝历史导出常为 GBK，逐个尝试。"""
    data = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"无法识别文件编码: {path}")


def detect_format(text: str) -> str | None:
    head = text[:2000]
    if "微信支付账单" in head or "微信昵称" in head:
        return "wechat"
    if "支付宝" in head:
        return "alipay"
    return None


def import_file(conn, path: str, fmt: str | None = None, bank: str | None = None) -> tuple[int, int]:
    """导入单个账单文件，返回 (新增, 跳过重复)。"""
    text = read_text(path)
    fmt = fmt or detect_format(text)
    if fmt is None:
        raise ValueError(
            f"无法自动识别账单格式: {path}\n"
            "银行流水请用 --format generic --bank <配置名>（见 config/banks.yaml）"
        )
    if fmt == "generic":
        txns = generic.parse(text, bank=bank)
    else:
        txns = PARSERS[fmt](text)
    return save_txns(conn, txns, source_file=Path(path).name)


def import_path(conn, path: str, fmt: str | None = None, bank: str | None = None):
    """支持单文件或目录（目录则导入其中所有 csv）。逐文件 yield 结果。"""
    p = Path(path)
    files = sorted(p.glob("*.csv")) if p.is_dir() else [p]
    for f in files:
        yield f.name, import_file(conn, str(f), fmt=fmt, bank=bank)
