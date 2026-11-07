#!/usr/bin/env python3
"""
Payment risk review: analyse a payment history export customer by customer.

  python3 payment_risk.py FILE [--inspect] [--out-dir DIR] [--as-of YYYY-MM-DD]
                         [--date-order dmy|mdy] [--map field="Column"]...
                         [--set threshold=value]... [--customer NAME]
                         [--sheet NAME] [--title TEXT]

--inspect     only show detected columns, date format and a preview; no analysis.
--as-of       reference date for the 90-day windows (default: latest payment date in the file).
--map         fix a column match, e.g. --map due_date="Net Due Dt". Fields: customer_name,
              customer_id, invoice_number, invoice_date, due_date, payment_date, amount, days_late.
--set         change a threshold, e.g. --set window_days=60 --set on_time_grace_days=5.
--customer    restrict the report to customers whose name or ID contains this text.

Writes results.json, customers.csv and dashboard.html to --out-dir and prints a summary.
Every number in the outputs is computed here; nothing is estimated.
Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import math
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from engine import DEFAULTS, analyse_payment_behaviour, analyse_payment_trend, js_round1, jsum  # noqa: E402
from reader import FIELDS, ReadError, read_payments  # noqa: E402

VERSION = "0.1.0"
SEV_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}
HEALTH_RANK = {"at_risk": 0, "watch": 1, "healthy": 2, "unknown": 3}
ATTN_RANK = {"high": 0, "medium": 1, "low": 2}
HEALTH_LABEL = {"at_risk": "At risk", "watch": "Watch", "healthy": "Healthy", "unknown": "Unknown"}


def fmt_days(x):
    if x is None:
        return "n/a"
    return f"{abs(x):.1f} days {'late' if x > 0 else 'early'}" if x != 0 else "on the due date"


def pct(x):
    return "n/a" if x is None else f"{x * 100:.0f}%"


def pct_floor(x):
    """For sentences that compare with a threshold: 84.9% must not read as 85%."""
    return "n/a" if x is None else f"{math.floor(x * 100 + 1e-9):.0f}%"


INT_KEYS = {"recent_count": 1, "window_days": 7, "on_time_grace_days": 0}
RATE_KEYS = {"at_risk_on_time_below", "watch_on_time_below"}


def build_config(pairs):
    cfg = dict(DEFAULTS)
    for k, v in pairs.items():
        if k not in DEFAULTS:
            raise ValueError(f"Unknown threshold '{k}'. Available: {', '.join(DEFAULTS)}")
        try:
            num = float(v)
        except ValueError:
            raise ValueError(f"--set {k} needs a number, got '{v}'.") from None
        if k in INT_KEYS:
            if num != int(num) or num < INT_KEYS[k]:
                raise ValueError(f"--set {k} needs a whole number of at least {INT_KEYS[k]}, got '{v}'.")
            cfg[k] = int(num)
        elif k in RATE_KEYS:
            if not 0 < num <= 1:
                raise ValueError(f"--set {k} is a share between 0 and 1 (e.g. 0.85 for 85%), got '{v}'.")
            cfg[k] = num
        else:
            if num < 0:
                raise ValueError(f"--set {k} can't be negative.")
            cfg[k] = num
    return cfg


def analyse_customer(rows, as_of, cfg):
    grace = cfg["on_time_grace_days"]
    tx = [{
        "payment_date": r["payment_date"],
        "days_to_pay": r["days_to_pay"],
        "days_early_late": r["days_early_late"],
        "on_time": r["days_early_late"] <= grace,
        "amount": r["amount"],
    } for r in rows]
    b = analyse_payment_behaviour(tx, cfg)
    if any(r["days_to_pay"] is None for r in rows):
        b["avg_days_to_pay"] = None  # only meaningful when every payment has an invoice date
    t = analyse_payment_trend(tx, as_of, cfg)
    w = int(cfg["window_days"])

    signals = []
    if b["health"] == "at_risk":
        signals.append({"type": "health", "severity": "high",
                        "text": f"Paying later over time, and only {pct_floor(b['on_time_rate'])} of value paid on time"})
    elif b["health"] == "watch":
        why = []
        if b["on_time_rate"] < cfg["watch_on_time_below"]:
            why.append(f"only {pct_floor(b['on_time_rate'])} of value paid on time")
        if (b["avg_days_early_late"] or 0) > cfg["watch_avg_days_late_above"]:
            why.append(f"{b['avg_days_early_late']:.1f} days late on average")
        if not why and b["trend"] == "deteriorating":
            why.append(f"paying later over time, though {pct(b['on_time_rate'])} of value is still paid on time")
        if not why:  # average just above the threshold but rounds down to it
            why.append(f"about {b['avg_days_early_late']:.1f} days late on average "
                       f"(threshold {cfg['watch_avg_days_late_above']:g})")
        signals.append({"type": "watch", "severity": "medium", "text": "Watch: " + "; ".join(why)})
    if t.get("deterioration"):
        d = t["deterioration"]
        signals.append({"type": "deterioration", "severity": d["severity"],
                        "text": f"Paying later: {t['current_avg_days_late']:+.1f} days vs due in the last {w} days, "
                                f"{t['prior_avg_days_late']:+.1f} in the {w} days before"})
    if t.get("volatility"):
        v = t["volatility"]
        signals.append({"type": "volatility", "severity": v["severity"],
                        "text": f"Erratic timing: payment dates vary by ±{v['standard_deviation_days']:.1f} days "
                                f"in the last {w} days"})
    if t.get("improvement"):
        i = t["improvement"]
        signals.append({"type": "improvement", "severity": i["severity"],
                        "text": f"Paying earlier: {t['current_avg_days_late']:+.1f} days vs due in the last {w} days, "
                                f"{t['prior_avg_days_late']:+.1f} before"})

    risk_sev = [SEV_RANK[s["severity"]] for s in signals if s["type"] != "improvement"]
    worst = max(risk_sev, default=-1)
    if b["health"] == "at_risk" or worst >= SEV_RANK["high"]:
        attention = "high"
    elif b["health"] == "watch" or worst >= SEV_RANK["medium"]:
        attention = "medium"
    else:
        attention = "low"

    rows_sorted = sorted(rows, key=lambda r: r["payment_date"])
    last = date.fromisoformat(rows_sorted[-1]["payment_date"])
    amounts = [r["amount"] for r in rows if r["amount"] is not None]
    return {
        "key": rows[0]["customer_key"],
        "customer": rows[0]["customer_name"],
        "customer_id": rows[0]["customer_id"],
        "payments": len(rows),
        "amount_paid": jsum(amounts) if amounts else None,
        "first_payment": rows_sorted[0]["payment_date"],
        "last_payment": rows_sorted[-1]["payment_date"],
        "days_since_last_payment": (date.fromisoformat(as_of) - last).days,
        "health": b["health"],
        "attention": attention,
        "on_time_rate": b["on_time_rate"],
        "recent_on_time_rate": b["recent_on_time_rate"],
        "avg_days_late": b["avg_days_early_late"],
        "avg_days_to_pay": b["avg_days_to_pay"],
        "trend": b["trend"],
        "window": t,
        "signals": signals,
        "worst_severity": worst,
        "risk_signal_count": len(risk_sev),
        "history": [{"date": r["payment_date"], "days_late": r["days_early_late"], "amount": r["amount"],
                     "invoice": r["invoice_number"], "due": r["due_date"]} for r in rows_sorted],
    }


def portfolio_summary(customers, payments, cfg):
    grace = cfg["on_time_grace_days"]
    w = [(p["amount"] if p["amount"] is not None else 1.0) for p in payments]
    tot_w = jsum(w)
    on_time_w = jsum(wi for wi, p in zip(w, payments) if p["days_early_late"] <= grace)
    late_w = jsum(wi * p["days_early_late"] for wi, p in zip(w, payments))
    amounts = [p["amount"] for p in payments if p["amount"] is not None]
    by_health = {h: {"customers": 0, "amount_paid": 0.0} for h in HEALTH_RANK}
    for c in customers:
        by_health[c["health"]]["customers"] += 1
        by_health[c["health"]]["amount_paid"] += c["amount_paid"] or 0.0
    total_paid = jsum(amounts) if amounts else None
    attn = Counter(c["attention"] for c in customers)
    attn_amount = jsum(c["amount_paid"] or 0.0 for c in customers if c["attention"] == "high")
    return {
        "customers": len(customers),
        "payments": len(payments),
        "amount_paid": total_paid,
        "amount_weighted": bool(amounts),
        "on_time_rate": on_time_w / tot_w if tot_w else None,
        "avg_days_late": js_round1(late_w / tot_w) if tot_w else None,
        "by_health": by_health,
        "attention": {k: attn.get(k, 0) for k in ATTN_RANK},
        "high_attention_amount_share": (attn_amount / total_paid) if total_paid else None,
        "signals": {
            "deteriorating": sum(1 for c in customers if c["window"].get("deterioration")),
            "volatile": sum(1 for c in customers if c["window"].get("volatility")),
            "improving": sum(1 for c in customers if c["window"].get("improvement")),
            "no_trend_data": sum(1 for c in customers if not c["window"]["has_sufficient_data"]),
        },
        "period": [min(p["payment_date"] for p in payments), max(p["payment_date"] for p in payments)],
    }


def safe_cell(v):
    """Stop spreadsheet apps treating text such as '=HYPERLINK(...)' as a formula."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def write_csv(path, customers):
    cols = ["customer", "customer_id", "attention", "health", "payments", "amount_paid", "on_time_rate",
            "recent_on_time_rate", "avg_days_late", "avg_days_to_pay", "trend", "current_window_avg_days_late",
            "prior_window_avg_days_late", "deterioration", "volatility", "improvement", "last_payment",
            "signals"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(cols)
        for c in customers:
            t = c["window"]
            wr.writerow([
                safe_cell(c["customer"]), safe_cell(c["customer_id"] or ""), c["attention"], c["health"], c["payments"],
                "" if c["amount_paid"] is None else round(c["amount_paid"], 2),
                "" if c["on_time_rate"] is None else round(c["on_time_rate"], 4),
                "" if c["recent_on_time_rate"] is None else round(c["recent_on_time_rate"], 4),
                c["avg_days_late"], "" if c["avg_days_to_pay"] is None else c["avg_days_to_pay"], c["trend"],
                t.get("current_avg_days_late", ""), t.get("prior_avg_days_late", ""),
                (t.get("deterioration") or {}).get("severity", ""),
                (t.get("volatility") or {}).get("severity", ""),
                (t.get("improvement") or {}).get("severity", ""),
                c["last_payment"], " | ".join(s["text"] for s in c["signals"]),
            ])


def parse_kv(items, what):
    out = {}
    for it in items or []:
        if "=" not in it:
            raise SystemExit(f"--{what} expects key=value, got '{it}'")
        k, v = it.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="Payment risk review")
    ap.add_argument("file")
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--out-dir", default="payment-risk-output")
    ap.add_argument("--as-of")
    ap.add_argument("--date-order", choices=["dmy", "mdy"])
    ap.add_argument("--map", action="append")
    ap.add_argument("--set", action="append")
    ap.add_argument("--customer")
    ap.add_argument("--sheet")
    ap.add_argument("--title", default="Payment risk review")
    a = ap.parse_args(argv)

    try:
        cfg = build_config(parse_kv(a.set, "set"))
    except ValueError as e:
        print(f"INVALID OPTION: {e}")
        return 2
    if a.as_of:
        try:
            date.fromisoformat(a.as_of)
        except ValueError:
            print(f"INVALID OPTION: --as-of must be a date written as YYYY-MM-DD, got '{a.as_of}'.")
            return 2

    try:
        res = read_payments(a.file, parse_kv(a.map, "map"), a.date_order, a.sheet)
    except ReadError as e:
        print(f"CANNOT READ FILE: {e}")
        return 2
    except FileNotFoundError:
        print(f"CANNOT READ FILE: no file at '{a.file}'.")
        return 2
    except Exception as e:  # noqa: BLE001 - anything else is reported, not dumped as a traceback
        print(f"CANNOT READ FILE: {type(e).__name__}: {e}. Try saving the file as CSV (UTF-8).")
        return 2

    pays = res["payments"]
    print(f"File: {os.path.basename(a.file)}  (header on row {res['header_row']}, {res['row_count']} data rows)")
    print("Columns used:")
    for f in FIELDS:
        if f in res["mapping"]:
            print(f"  {f:15} <- {res['mapping'][f]!r}")
    unused = [h for h in res["headers"] if h and h not in res["mapping"].values()]
    if unused:
        print(f"Columns not used: {unused}")
    print(f"Date format: {res['date_order'] or 'ISO/unambiguous'} ({res['date_order_basis']})")
    print(f"Usable payments: {len(pays)}; skipped rows: {len(res['skipped'])}")
    for reason, n in Counter(s["reason"] for s in res["skipped"]).most_common(6):
        print(f"  skipped {n} x {reason}")
    for wmsg in res["warnings"][:10]:
        print(f"WARNING: {wmsg}")

    if a.inspect:
        print("Preview (first 5 usable payments):")
        for p in pays[:5]:
            print(f"  row {p['row']}: {p['customer_name']} | invoice {p['invoice_number']} | due {p['due_date']} | "
                  f"paid {p['payment_date']} | {p['days_early_late']:+d} days | amount {p['amount']}")
        return 0

    as_of = a.as_of or max(p["payment_date"] for p in pays)
    later = [p for p in pays if p["payment_date"] > as_of]
    if later:
        pays = [p for p in pays if p["payment_date"] <= as_of]
        msg = f"{len(later)} payments made after the as-of date {as_of} were left out."
        res["warnings"].append(msg)
        print(f"NOTE: {msg}")
        if not pays:
            print(f"CANNOT ANALYSE: no payments on or before {as_of}.")
            return 2
    groups = defaultdict(list)
    for p in pays:
        groups[p["customer_key"]].append(p)

    customers = [analyse_customer(rows, as_of, cfg) for rows in groups.values()]
    if a.customer:
        q = a.customer.lower()
        customers = [c for c in customers if q in c["customer"].lower() or q in (c["customer_id"] or "").lower()]
        if not customers:
            names = sorted({c for c in (r[0]["customer_name"] for r in groups.values())})
            print(f"No customer matches '{a.customer}'. Some names in the file: {names[:15]}")
            return 3
        keys = {c["key"] for c in customers}
        pays = [p for p in pays if p["customer_key"] in keys]

    customers.sort(key=lambda c: (ATTN_RANK[c["attention"]], -c["worst_severity"], -c["risk_signal_count"],
                                  HEALTH_RANK[c["health"]],
                                  -(c["amount_paid"] or 0), c["customer"].lower()))
    summary = portfolio_summary(customers, pays, cfg)

    os.makedirs(a.out_dir, exist_ok=True)
    result = {
        "tool": {"name": "payment-risk", "version": VERSION},
        "title": a.title,
        "source_file": os.path.basename(a.file),
        "as_of": as_of,
        "as_of_basis": "set by user" if a.as_of else "latest payment date in the file",
        "config": cfg,
        "read": {k: res[k] for k in ("mapping", "date_order", "date_order_basis", "warnings", "row_count")}
        | {"skipped": res["skipped"][:200], "skipped_count": len(res["skipped"])},
        "portfolio": summary,
        "customers": customers,
    }
    with open(os.path.join(a.out_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1, default=str)
    write_csv(os.path.join(a.out_dir, "customers.csv"), customers)
    from dashboard import render
    with open(os.path.join(a.out_dir, "dashboard.html"), "w", encoding="utf-8") as f:
        f.write(render(result))

    s = summary
    print()
    print(f"As of {as_of} ({result['as_of_basis']}); payments from {s['period'][0]} to {s['period'][1]}.")
    print(f"Customers: {s['customers']} | payments: {s['payments']}"
          + (f" | paid: {s['amount_paid']:,.2f}" if s["amount_paid"] is not None else ""))
    print(f"On time ({'by value' if s['amount_weighted'] else 'by count'}): {pct(s['on_time_rate'])} | "
          f"average {fmt_days(s['avg_days_late'])}")
    print("Health: " + ", ".join(f"{HEALTH_LABEL[h]} {v['customers']}" for h, v in s["by_health"].items() if v["customers"]))
    print(f"Needs attention: high {s['attention']['high']}, medium {s['attention']['medium']}"
          + (f" (high = {pct(s['high_attention_amount_share'])} of value paid)" if s["high_attention_amount_share"] is not None else ""))
    print(f"Signals: deteriorating {s['signals']['deteriorating']}, volatile {s['signals']['volatile']}, "
          f"improving {s['signals']['improving']}, too little history for the {int(cfg['window_days'])}-day "
          f"comparison {s['signals']['no_trend_data']}")
    top = [c for c in customers if c["attention"] != "low"][:10]
    if top:
        print("\nTop of the watchlist:")
        for c in top:
            sig = "; ".join(x["text"] for x in c["signals"]) or HEALTH_LABEL[c["health"]]
            print(f"  [{c['attention']}] {c['customer']}: on time {pct(c['on_time_rate'])}, "
                  f"avg {fmt_days(c['avg_days_late'])}. {sig}")
    print(f"\nWrote {a.out_dir}/dashboard.html, customers.csv, results.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
