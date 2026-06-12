"""本地 Web 仪表盘：收支趋势、分类占比、净资产曲线、交易明细。

只监听 127.0.0.1，财务数据不出本机。JSON API 同时供页面和外部 agent 使用。
"""

from flask import Flask, jsonify, render_template, request

from .db import get_db
from .report import month_data, monthly_series


def create_app(db_path: str | None = None) -> Flask:
    app = Flask(__name__)

    def db():
        return get_db(db_path)

    @app.route("/")
    def index():
        return render_template("index.html")

    @app.route("/api/trend")
    def trend():
        months = int(request.args.get("months", 12))
        return jsonify(monthly_series(db(), months))

    @app.route("/api/month/<ym>")
    def month(ym):
        return jsonify(month_data(db(), ym))

    @app.route("/api/networth")
    def networth():
        conn = db()
        rows = conn.execute(
            "SELECT date, SUM(value_cents) cents FROM snapshots GROUP BY date ORDER BY date"
        ).fetchall()
        latest = conn.execute("SELECT MAX(date) d FROM snapshots").fetchone()["d"]
        allocation = []
        if latest:
            allocation = [dict(r) for r in conn.execute(
                "SELECT asset_class, SUM(value_cents) cents FROM snapshots"
                " WHERE date=? GROUP BY asset_class ORDER BY cents DESC", (latest,))]
        return jsonify({"history": [dict(r) for r in rows], "latest_date": latest,
                        "allocation": allocation})

    @app.route("/api/transactions")
    def transactions():
        conn = db()
        limit = min(int(request.args.get("limit", 100)), 1000)
        ym = request.args.get("month")
        category = request.args.get("category")
        sql = ("SELECT time, amount_cents, direction, counterparty, description,"
               " COALESCE(category,'未分类') category, source FROM transactions WHERE 1=1")
        args: list = []
        if ym:
            sql += " AND substr(time,1,7)=?"
            args.append(ym)
        if category:
            sql += " AND COALESCE(category,'未分类')=?"
            args.append(category)
        sql += " ORDER BY time DESC LIMIT ?"
        args.append(limit)
        return jsonify([dict(r) for r in conn.execute(sql, args)])

    return app


def run(db_path: str | None = None, port: int = 8016):
    app = create_app(db_path)
    print(f"仪表盘: http://127.0.0.1:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)
