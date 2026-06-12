"""wallet 命令行入口。所有子命令均支持把数据输出为 JSON（便于 agent 调用）。"""

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

from .db import fmt_yuan, get_db


def cmd_import(args):
    from .importers import import_path

    conn = get_db(args.db)
    total_added = total_skipped = 0
    for name, (added, skipped) in import_path(conn, args.path, fmt=args.format, bank=args.bank):
        print(f"  {name}: 新增 {added} 笔，跳过重复 {skipped} 笔")
        total_added += added
        total_skipped += skipped
    print(f"导入完成：共新增 {total_added} 笔。")

    from .categorize import apply_rules, uncategorized_merchants
    n = apply_rules(conn)
    remaining = len(uncategorized_merchants(conn))
    print(f"规则分类：{n} 笔已分类。", end=" ")
    if remaining:
        print(f"还有 {remaining} 类商户未识别，运行 `wallet categorize --llm` 让 Claude 兜底。")
    else:
        print("全部交易已分类 ✓")


def cmd_categorize(args):
    from .categorize import apply_rules, llm_categorize, uncategorized_merchants

    conn = get_db(args.db)
    n = apply_rules(conn)
    print(f"规则分类：{n} 笔。")
    merchants = uncategorized_merchants(conn)
    if not merchants:
        print("全部交易已分类 ✓")
        return
    if args.llm:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            sys.exit("未设置 ANTHROPIC_API_KEY，无法调用 LLM 兜底。")
        updated, learned = llm_categorize(conn)
        print(f"LLM 分类：{updated} 笔，学到 {learned} 条新规则（已写入 config/rules.learned.yaml）。")
        remaining = uncategorized_merchants(conn)
        if remaining:
            print(f"仍有 {len(remaining)} 类商户未能分类，可手动补充 config/rules.yaml。")
    else:
        if args.json:
            print(json.dumps(merchants, ensure_ascii=False, indent=2))
        else:
            print(f"\n未识别商户（共 {len(merchants)} 类，按笔数排序）：")
            for m in merchants[:30]:
                print(f"  {m['n']:>3} 笔  {m['counterparty'] or '(空)'}  | {m['description'][:30]}")
            print("\n选项：1) 在 config/rules.yaml 加规则后重跑  2) wallet categorize --llm")


def cmd_report(args):
    from .report import month_data, render_markdown

    conn = get_db(args.db)
    if args.json:
        print(json.dumps(month_data(conn, args.month), ensure_ascii=False, indent=2))
        return
    md = render_markdown(conn, args.month)
    out = Path(args.output or f"reports/{args.month}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(md)
    print(f"已保存到 {out}")


def cmd_snapshot(args):
    conn = get_db(args.db)
    if args.snapshot_cmd == "add":
        from .models import parse_cents
        d = args.date or date.today().isoformat()
        conn.execute(
            "INSERT INTO snapshots (date, account, asset_class, value_cents, note)"
            " VALUES (?,?,?,?,?) ON CONFLICT(date, account) DO UPDATE SET"
            " asset_class=excluded.asset_class, value_cents=excluded.value_cents, note=excluded.note",
            (d, args.account, args.asset_class, parse_cents(args.value), args.note or ""),
        )
        conn.commit()
        print(f"已记录 {d} {args.account}({args.asset_class}) = ¥{args.value}")
    else:  # list
        rows = conn.execute(
            "SELECT date, account, asset_class, value_cents, note FROM snapshots"
            " ORDER BY date DESC, value_cents DESC LIMIT 100").fetchall()
        if args.json:
            print(json.dumps([dict(r) for r in rows], ensure_ascii=False, indent=2))
            return
        last_date = None
        for r in rows:
            if r["date"] != last_date:
                print(f"\n{r['date']}")
                last_date = r["date"]
            print(f"  {r['account']:<16} {r['asset_class']:<12} ¥{fmt_yuan(r['value_cents'])}")


def cmd_advise(args):
    from .advisor import advise, build_digest

    conn = get_db(args.db)
    if args.dry_run or not os.environ.get("ANTHROPIC_API_KEY"):
        if not args.dry_run:
            print("（未设置 ANTHROPIC_API_KEY，仅输出数据摘要。可把摘要交给任何 agent 分析。）\n",
                  file=sys.stderr)
        print(build_digest(conn, args.months))
        return
    result = advise(conn, args.months)
    out = Path(args.output or f"reports/advice-{date.today().isoformat()}.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(result, encoding="utf-8")
    print(result)
    print(f"已保存到 {out}")


def cmd_web(args):
    from .web import run
    run(args.db, port=args.port)


def main(argv=None):
    p = argparse.ArgumentParser(prog="wallet", description="个人财务系统")
    p.add_argument("--db", help="数据库路径（默认 data/wallet.db，或环境变量 WALLET_DB）")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("import", help="导入账单（微信/支付宝自动识别，目录则批量导入）")
    sp.add_argument("path", help="账单文件或目录（如 inbox/）")
    sp.add_argument("--format", choices=["wechat", "alipay", "generic"], help="不指定则自动识别")
    sp.add_argument("--bank", help="generic 格式对应的银行配置名（见 config/banks.yaml）")
    sp.set_defaults(func=cmd_import)

    sp = sub.add_parser("categorize", help="对未分类交易跑规则；--llm 用 Claude 兜底")
    sp.add_argument("--llm", action="store_true")
    sp.add_argument("--json", action="store_true", help="以 JSON 输出未识别商户清单")
    sp.set_defaults(func=cmd_categorize)

    sp = sub.add_parser("report", help="生成月报，如 wallet report 2026-06")
    sp.add_argument("month", help="YYYY-MM")
    sp.add_argument("-o", "--output", help="输出文件（默认 reports/<月份>.md）")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_report)

    sp = sub.add_parser("snapshot", help="资产快照管理")
    ssub = sp.add_subparsers(dest="snapshot_cmd", required=True)
    sa = ssub.add_parser("add", help="记录某账户市值")
    sa.add_argument("account", help="账户名，如 招行储蓄")
    sa.add_argument("asset_class", choices=["cash", "deposit", "fund", "stock", "bond",
                                            "gold", "insurance", "real_estate", "crypto", "other"])
    sa.add_argument("value", help="市值（元），负债记负数")
    sa.add_argument("--date", help="默认今天")
    sa.add_argument("--note")
    sl = ssub.add_parser("list")
    sl.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_snapshot)

    sp = sub.add_parser("advise", help="生成资产配置建议（需 ANTHROPIC_API_KEY；--dry-run 仅输出数据摘要）")
    sp.add_argument("--months", type=int, default=6, help="分析最近 N 个月现金流（默认 6）")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("-o", "--output")
    sp.set_defaults(func=cmd_advise)

    sp = sub.add_parser("web", help="启动本地仪表盘")
    sp.add_argument("--port", type=int, default=8016)
    sp.set_defaults(func=cmd_web)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
