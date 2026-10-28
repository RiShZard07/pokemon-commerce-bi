"""Reproducible, local BI prototype. All commerce data is synthetic."""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import random
import sqlite3
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def generate(folder: Path, n: int = 20000, seed: int = 42) -> None:
    """Generate fictional product catalog and dirty order-line fixtures."""
    if n < 1:
        raise ValueError("n must be positive")
    folder.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    names = ["Pikachu", "Eevee", "Charizard", "Bulbasaur", "Squirtle", "Mewtwo"]
    products = [{"product_id": f"P{i:02}", "name": f"{name} art print",
                 "category": "foil" if j else "standard", "list_cents": 500 + i * 150}
                for i, (name, j) in enumerate((name, j) for name in names for j in (0, 1))]
    write_csv(folder / "products.csv", products)
    rows = []
    for i in range(n):
        p = rng.choice(products)
        day = date(2026, 1, 1) + timedelta(days=rng.randrange(90))
        qty = rng.randint(1, 3)
        rows.append({"line_id": f"L{i:07}", "day": day.isoformat(), "product_id": p["product_id"],
                     "quantity": qty, "unit_cents": p["list_cents"],
                     "discount_cents": rng.choice([0, 0, 100]),
                     "status": rng.choices(["completed", "returned", "cancelled"], [90, 6, 4])[0]})
    # Deliberate faults: duplicates, invalid dates, negative quantities, orphan keys.
    rows.extend(dict(r) for r in rows[:max(1, n // 100)])
    for i in range(0, n, 200):
        rows[i]["quantity"] = -1
    for i in range(1, n, 250):
        rows[i]["product_id"] = "MISSING"
    for i in range(2, n, 300):
        rows[i]["day"] = "2026-02-31"
    write_csv(folder / "orders.csv", rows)


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def validate(row: dict, product_ids: set[str]) -> dict:
    """Strict contract before any warehouse mutation; prices are integer cents."""
    line = str(row["line_id"]).strip()
    if not line:
        raise ValueError("blank line_id")
    day = date.fromisoformat(row["day"]).isoformat()
    if row["product_id"] not in product_ids:
        raise ValueError("unknown product_id")
    qty, price, discount = (int(row[k]) for k in ("quantity", "unit_cents", "discount_cents"))
    if qty <= 0 or price < 0 or not 0 <= discount <= qty * price:
        raise ValueError("invalid quantity or monetary bounds")
    if row["status"] not in {"completed", "returned", "cancelled"}:
        raise ValueError("invalid status")
    return dict(line_id=line, day=day, product_id=row["product_id"], quantity=qty,
                unit_cents=price, discount_cents=discount, status=row["status"])


def load(folder: Path, db: Path, alert_threshold: float = .02) -> dict:
    """Atomic full refresh; input-order deterministic dedup; rejected rows exported."""
    products = read_csv(folder / "products.csv")
    if not products or len({p["product_id"] for p in products}) != len(products):
        raise ValueError("product keys must be nonempty and unique")
    for p in products:
        if not p["product_id"].strip() or not p["name"].strip() or int(p["list_cents"]) < 0:
            raise ValueError("invalid product")
    rows = read_csv(folder / "orders.csv")
    ids = {p["product_id"] for p in products}
    valid, rejected, seen = [], [], set()
    for i, row in enumerate(rows, 2):
        try:
            clean = validate(row, ids)
            if clean["line_id"] in seen:
                raise ValueError("duplicate line_id")
            seen.add(clean["line_id"])
            valid.append(clean)
        except (ValueError, KeyError, TypeError) as error:
            rejected.append({"source_line": i, "reason": str(error), "row": row})
    if not valid:
        raise ValueError("no valid orders; previous warehouse preserved")
    db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db) as con:
        con.execute("PRAGMA foreign_keys=ON")
        # executescript commits pending work, so run schema creation before transaction.
        con.executescript((ROOT / "schema.sql").read_text())
        con.execute("DELETE FROM fact_order_line")
        con.execute("DELETE FROM dim_product")
        con.execute("DELETE FROM dim_date")
        con.executemany("INSERT INTO dim_product VALUES (?,?,?,?)", [
            (p["product_id"], p["name"], p["category"], int(p["list_cents"])) for p in products])
        days = sorted({r["day"] for r in valid})
        con.executemany("INSERT INTO dim_date VALUES (?,?)", [(d, date.fromisoformat(d).weekday()) for d in days])
        fields = ("line_id", "day", "product_id", "quantity", "unit_cents", "discount_cents", "status")
        con.executemany("INSERT INTO fact_order_line VALUES (?,?,?,?,?,?,?)",
                        [tuple(r[k] for k in fields) for r in valid])
        con.execute("INSERT INTO load_audit(input_rows,accepted_rows,rejected_rows) VALUES(?,?,?)",
                    (len(rows), len(valid), len(rejected)))
    rate = len(rejected) / len(rows)
    result = {"synthetic": True, "input_rows": len(rows), "accepted_rows": len(valid),
              "rejected_rows": len(rejected), "rejected_rate": rate,
              "alert": rate > alert_threshold, "alert_threshold": alert_threshold,
              "input_sha256": hashlib.sha256((folder / "orders.csv").read_bytes()).hexdigest()}
    (db.parent / "rejected.json").write_text(json.dumps(rejected, indent=2))
    (db.parent / "quality.json").write_text(json.dumps(result, indent=2))
    return result


def baseline_evaluation(daily: list[dict], holdout: int = 14) -> dict:
    """Fixed-origin mean vs last-week-repeat baseline, no holdout leakage."""
    if len(daily) <= holdout + 7:
        return {"available": False, "reason": "Need more than holdout + 7 days"}
    values = [r["net_cents"] / 100 for r in daily]
    train, test = values[:-holdout], values[-holdout:]
    mean_pred = [sum(train) / len(train)] * holdout
    weekly_pred = [train[-7:][i % 7] for i in range(holdout)]
    mae = lambda pred: sum(abs(a - b) for a, b in zip(test, pred)) / len(test)
    return {"available": True, "holdout_days": holdout, "train_days": len(train),
            "mean_mae_usd": round(mae(mean_pred), 2),
            "weekly_repeat_mae_usd": round(mae(weekly_pred), 2),
            "note": "Synthetic-data baseline evaluation, not real demand prediction."}


def report(db: Path, out: Path) -> dict:
    with sqlite3.connect(db) as con:
        con.row_factory = sqlite3.Row
        daily = [dict(r) for r in con.execute("SELECT * FROM mart_daily ORDER BY day")]
        products = [dict(r) for r in con.execute("SELECT * FROM mart_product ORDER BY net_cents DESC")]
        kpi = dict(con.execute("SELECT * FROM mart_kpi").fetchone())
    # Fill missing calendar days as zero; do not compress time for forecasting.
    by_day = {r["day"]: r for r in daily}
    start, end = date.fromisoformat(daily[0]["day"]), date.fromisoformat(daily[-1]["day"])
    daily = [by_day.get((start + timedelta(days=i)).isoformat(),
             {"day": (start + timedelta(days=i)).isoformat(), "completed_lines": 0, "net_cents": 0})
             for i in range((end - start).days + 1)]
    metrics = {"synthetic": True, "kpi": kpi, "forecast": baseline_evaluation(daily)}
    out.mkdir(parents=True, exist_ok=True)
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2))
    write_csv(out / "daily.csv", daily)
    write_csv(out / "products.csv", products)
    maximum = max(r["net_cents"] for r in daily) or 1
    points = " ".join(f"{i * 1000 / max(1,len(daily)-1):.1f},{180-r['net_cents']/maximum*160:.1f}" for i,r in enumerate(daily))
    quality = json.loads((db.parent / "quality.json").read_text())
    body_rows = "".join("<tr>" + "".join(f"<td>{html.escape(str(v))}</td>" for v in
        [r["name"], r["category"], r["completed_units"], f"${r['net_cents']/100:,.2f}"]) + "</tr>" for r in products)
    page = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pokemon Commerce BI</title><style>
body{{font:16px system-ui;background:#f5f7fb;color:#17253b;max-width:1100px;margin:40px auto;padding:0 22px}}h1{{font-size:38px;margin-bottom:8px}}
.label{{color:#775100;background:#fff0b3;padding:8px 12px;display:inline-block;border-radius:8px}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin:24px 0}}
article,section{{background:white;border:1px solid #dce2eb;padding:22px;border-radius:12px;margin-bottom:18px}}strong{{font-size:28px;display:block}}small{{color:#56657a}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;padding:10px;border-bottom:1px solid #e4e8ee}}th{{font-size:13px;text-transform:uppercase}}svg{{width:100%;height:200px}}input{{padding:10px;border:1px solid #bbb;border-radius:6px}}@media(max-width:600px){{.grid{{grid-template-columns:1fr}}h1{{font-size:30px}}}}
</style><header><small>ANALYTICS ENGINEERING / PORTFOLIO PROTOTYPE</small><h1>Pokemon Commerce BI</h1>
<p class="label">Synthetic demonstration data. Not real card prices, sales, or Nintendo data.</p></header>
<div class="grid"><article>Net completed revenue<strong>${kpi['net_cents']/100:,.2f}</strong><small>After discounts; returns and cancellations excluded</small></article>
<article>Completed units<strong>{kpi['completed_units']:,}</strong><small>{kpi['completed_lines']:,} completed order lines</small></article>
<article>Data quality<strong>{quality['rejected_rate']:.1%} rejected</strong><small>{'ALERT: threshold exceeded' if quality['alert'] else 'Within configured threshold'}; {quality['rejected_rows']:,} quarantined rows</small></article></div>
<section><h2>Daily net revenue</h2><svg viewBox="0 0 1000 200" role="img" aria-label="Daily revenue line chart"><path d="M0 180H1000" stroke="#dce2eb"/><polyline fill="none" stroke="#2465c5" stroke-width="2" points="{points}"/></svg><small>{daily[0]['day']} to {daily[-1]['day']} | USD | Zero-filled calendar days</small></section>
<section><h2>Product performance</h2><input id="search" placeholder="Filter by product name" aria-label="Filter product table"><table><thead><tr><th>Product</th><th>Category</th><th>Units</th><th>Net revenue</th></tr></thead><tbody>{body_rows}</tbody></table></section>
<section><h2>Forecast sanity check</h2><p>Fixed-origin 14-day holdout. Compares a training-mean baseline with repetition of the last training week.</p><pre>{html.escape(json.dumps(metrics['forecast'],indent=2))}</pre><small>No claims about actual market demand or business lift.</small></section>
<script>document.getElementById('search').addEventListener('input',e=>{{for(const row of document.querySelectorAll('tbody tr'))row.hidden=!row.textContent.toLowerCase().includes(e.target.value.toLowerCase())}})</script></html>'''
    (out / "dashboard.html").write_text(page, encoding="utf-8")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["demo", "load", "report"])
    parser.add_argument("--input", type=Path, default=ROOT / "data")
    parser.add_argument("--output", type=Path, default=ROOT / "output")
    parser.add_argument("--rows", type=int, default=20000)
    args = parser.parse_args()
    db = args.output / "warehouse.sqlite"
    if args.command == "demo":
        generate(args.input, args.rows)
    if args.command in {"demo", "load"}:
        print(json.dumps(load(args.input, db), indent=2))
    print(json.dumps(report(db, args.output), indent=2))


if __name__ == "__main__":
    main()
