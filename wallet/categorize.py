"""分类引擎：规则库优先，陌生商户交给 Claude 兜底，结果回写规则库形成正反馈。"""

import re
from pathlib import Path

import yaml

RULES_FILE = "config/rules.yaml"
LEARNED_FILE = "config/rules.learned.yaml"
TRANSFER_CATEGORY = "转账"  # 资金内部流转，不参与收支统计


def load_rules() -> tuple[list[str], list[dict]]:
    """返回 (分类列表, 规则列表)。手写规则优先于 LLM 学到的规则。"""
    base = yaml.safe_load(Path(RULES_FILE).read_text(encoding="utf-8")) or {}
    categories = base.get("categories", [])
    rules = list(base.get("rules", []))
    learned_path = Path(LEARNED_FILE)
    if learned_path.exists():
        learned = yaml.safe_load(learned_path.read_text(encoding="utf-8")) or {}
        rules += learned.get("rules", [])
    return categories, rules


def match_category(text: str, rules: list[dict]) -> str | None:
    for rule in rules:
        if re.search(rule["match"], text):
            return rule["category"]
    return None


def apply_rules(conn) -> int:
    """对所有未分类交易跑规则，返回成功分类数。转账类直接标记。"""
    _, rules = load_rules()
    rows = conn.execute(
        "SELECT id, counterparty, description, direction FROM transactions WHERE category IS NULL"
    ).fetchall()
    updated = 0
    for r in rows:
        if r["direction"] == "transfer":
            category = TRANSFER_CATEGORY
        else:
            category = match_category(f"{r['counterparty']} {r['description']}", rules)
        if category:
            conn.execute("UPDATE transactions SET category=? WHERE id=?", (category, r["id"]))
            updated += 1
    conn.commit()
    return updated


def uncategorized_merchants(conn, limit: int = 200) -> list[dict]:
    """规则没命中的商户清单（按出现次数聚合），供人工或 LLM 处理。"""
    rows = conn.execute(
        """SELECT counterparty, description, COUNT(*) AS n, SUM(amount_cents) AS total
           FROM transactions WHERE category IS NULL
           GROUP BY counterparty, description ORDER BY n DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def llm_categorize(conn, model: str = "claude-opus-4-8") -> tuple[int, int]:
    """用 Claude 给规则未覆盖的商户分类，并把结果固化到 rules.learned.yaml。

    返回 (本次分类的交易数, 新学到的规则数)。需要 ANTHROPIC_API_KEY。
    只把商户名/商品描述发给 API，不发送金额、时间等其他信息。
    """
    import anthropic
    from pydantic import BaseModel

    categories, _ = load_rules()
    merchants = uncategorized_merchants(conn)
    if not merchants:
        return 0, 0

    class Item(BaseModel):
        counterparty: str
        category: str

    class Result(BaseModel):
        items: list[Item]

    merchant_lines = "\n".join(
        f"- 对方: {m['counterparty'] or '(空)'} | 描述: {m['description'] or '(空)'}" for m in merchants
    )
    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=model,
        max_tokens=16000,
        system=(
            "你是个人记账系统的交易分类器。根据中国大陆常见商户名和商品描述，"
            f"把每笔交易归入且仅归入以下分类之一：{'、'.join(categories)}。"
            "无法判断时归入'其他'。counterparty 字段原样返回输入中的'对方'值。"
        ),
        messages=[{"role": "user", "content": f"请为以下交易分类：\n{merchant_lines}"}],
        output_format=Result,
    )
    result = response.parsed_output
    if result is None:
        raise RuntimeError("Claude 返回的分类结果无法解析")

    mapping = {item.counterparty: item.category for item in result.items if item.category in categories}

    updated = 0
    learned_rules = []
    for m in merchants:
        category = mapping.get(m["counterparty"] or "(空)") or mapping.get(m["counterparty"])
        if not category:
            continue
        cur = conn.execute(
            "UPDATE transactions SET category=? WHERE category IS NULL AND counterparty=? AND description=?",
            (category, m["counterparty"], m["description"]),
        )
        updated += cur.rowcount
        if m["counterparty"]:  # 固化为精确匹配规则，下次零成本命中
            learned_rules.append({"match": re.escape(m["counterparty"]), "category": category})

    conn.commit()
    if learned_rules:
        _append_learned(learned_rules)
    return updated, len(learned_rules)


def _append_learned(new_rules: list[dict]):
    path = Path(LEARNED_FILE)
    existing = {}
    if path.exists():
        existing = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    rules = existing.get("rules", [])
    known = {r["match"] for r in rules}
    rules += [r for r in new_rules if r["match"] not in known]
    path.write_text(
        "# 由 LLM 分类兜底自动学习的规则（可手动修正，手写的 rules.yaml 优先级更高）\n"
        + yaml.safe_dump({"rules": rules}, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
