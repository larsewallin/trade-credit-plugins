#!/usr/bin/env python3
"""
AR aging review: age an open-items (accounts receivable) export customer by customer.

  python3 ar_aging.py FILE [--inspect] [--out-dir DIR] [--as-of YYYY-MM-DD]
                     [--date-order dmy|mdy] [--map field="Column"]...
                     [--set key=value]... [--customer NAME] [--sheet NAME] [--title TEXT]

--inspect     only show detected columns, date format and a preview; no analysis.
--as-of       the date the balances are aged to (default: today). Use the export date for an older file.
--map         fix a column match, e.g. --map amount_open="Open Amt LC". Fields: customer_name, customer_id,
              invoice_number, invoice_date, due_date, amount_open, amount_invoice, currency, credit_limit,
              days_past_due, status.
--set         change a setting, e.g. --set grace_days=5 --set utilisation_high_pct=90.
--customer    restrict the report to customers whose name or ID contains this text.

Writes results.json, customers.csv, open_items.csv and dashboard.html to --out-dir and prints a summary.
Every number in the outputs is computed here; nothing is estimated. Standard library only.

Rules (the same as the AR aging agent this was taken from):
  - Buckets by days past due: current (not yet due), 1-30, 31-60, 61-90, over 90.
  - Severity by the worst bucket with a past-due amount: over 90 critical, 61-90 high, 31-60 medium, 1-30 low.
  - Credit notes and unapplied cash (negative amounts) are kept apart and reduce the balance, never a bucket.
  - Utilisation = net open balance / credit limit. Over 100% is "over limit"; above utilisation_high_pct is "near limit".
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from reader import FIELDS, ReadError, read_open_items  # noqa: E402

VERSION = "0.1.0"
BUCKETS = ["current", "1_30", "31_60", "61_90", "over_90"]
BUCKET_LABEL = {"current": "Current", "1_30": "1–30", "31_60": "31–60", "61_90": "61–90", "over_90": "Over 90"}
SEVERITY_BY_BUCKET = {"over_90": "critical", "61_90": "high", "31_60": "medium", "1_30": "low"}
SEV_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1, "none": 0}
SEV_LABEL = {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low", "none": "Current"}

DEFAULTS = {
    "grace_days": 0,               # items this many days past due or fewer count as current
    "utilisation_high_pct": 80,    # "near limit" above this share of the credit limit
    "stale_export_days": 31,       # warn when the newest invoice is older than this before the as-of date
}


def build_config(pairs):
    cfg = dict(DEFAULTS)
    for k, v in pairs.items():
        if k not in DEFAULTS:
            raise ValueError(f"Unknown setting '{k}'. Available: {', '.join(DEFAULTS)}")
        try:
            num = float(v)
        except ValueError:
            raise ValueError(f"--set {k} needs a number, got '{v}'.") from None
        if num < 0 or num != int(num):
            raise ValueError(f"--set {k} needs a whole number of 0 or more, got '{v}'.")
        cfg[k] = int(num)
    return cfg


def bucket_for(dpd: int, grace: int) -> str:
    if dpd <= grace:
        return "current"
    if dpd <= 30:
        return "1_30"
    if dpd <= 60:
        return "31_60"
    if dpd <= 90:
        return "61_90"
    return "over_90"


def r2(x):
    return None if x is None else round(x + 0.0, 2)


def money(x, cur=None):
    if x is None:
        return "n/a"
    return f"{x:,.2f}" + (f" {cur}" if cur else "")


def pct(x):
    return "n/a" if x is None else f"{x * 100:.0f}%"


def pct_floor(x):
    """For shares compared with a threshold: 99.7% of a limit must not read as 100%."""
    return "n/a" if x is None else f"{math.floor(x * 100 + 1e-9):.0f}%"


def age_items(items, as_of: date, grace: int):
    """Adds days_past_due and bucket to every item (credits get bucket 'credit')."""
    for it in items:
        if it["due_date"]:
            dpd = (as_of - date.fromisoformat(it["due_date"])).days
        elif it["days_past_due_given"] is not None:
            dpd = it["days_past_due_given"]
        else:
            dpd = 0  # a credit without a due date
        it["days_past_due"] = dpd
        it["bucket"] = "credit" if it["amount_open"] < 0 else bucket_for(dpd, grace)
    return items


def analyse_customer(items, credit_limit, cfg):
    b = {k: 0.0 for k in BUCKETS}
    credits = 0.0
    for it in items:
        if it["bucket"] == "credit":
            credits += it["amount_open"]
        else:
            b[it["bucket"]] += it["amount_open"]
    gross = sum(b.values())
    net = gross + credits
    past_due = gross - b["current"]
    pd_items = [it for it in items if it["bucket"] not in ("credit", "current")]
    oldest = max((it["days_past_due"] for it in pd_items), default=None)
    w_avg = (sum(it["days_past_due"] * it["amount_open"] for it in pd_items) / past_due) if past_due > 0 else None
    worst = next((k for k in ("over_90", "61_90", "31_60", "1_30") if b[k] > 0), None)
    severity = SEVERITY_BY_BUCKET[worst] if worst else "none"

    util = (net / credit_limit) if credit_limit else None
    limit_flag = None
    if util is not None:
        if util > 1:
            limit_flag = "over_limit"
        elif util * 100 > cfg["utilisation_high_pct"]:
            limit_flag = "near_limit"

    reasons = []
    if worst:
        reasons.append(f"{money(b[worst], items[0]['currency'])} is {BUCKET_LABEL[worst].lower()} days past due"
                       + (f" (oldest {oldest} days)" if oldest is not None else ""))
    if gross > 0 and past_due > 0:
        reasons.append(f"{pct(past_due / gross)} of the open balance is past due")
    if limit_flag == "over_limit":
        reasons.append(f"over the credit limit by {money(net - credit_limit, items[0]['currency'])} "
                       f"({pct_floor(util)} of {money(credit_limit, items[0]['currency'])})")
    elif limit_flag == "near_limit":
        reasons.append(f"near the credit limit: {pct_floor(util)} of {money(credit_limit, items[0]['currency'])}")
    if net < 0:
        reasons.append("credit balance: credits exceed open invoices")

    first = items[0]
    return {
        "key": first["customer_key"] + "|" + (first["currency"] or ""),
        "customer": first["customer_name"],
        "customer_id": first["customer_id"],
        "currency": first["currency"],
        "severity": severity,
        "worst_bucket": worst,
        "limit_flag": limit_flag,
        "open_items": len(items),
        "past_due_items": len(pd_items),
        "gross_open": r2(gross),
        "credits": r2(credits),
        "net_open": r2(net),
        "past_due": r2(past_due),
        "past_due_share": (past_due / gross) if gross > 0 else None,
        "buckets": {k: r2(v) for k, v in b.items()},
        "oldest_days_past_due": oldest,
        "weighted_avg_days_past_due": None if w_avg is None else round(w_avg, 1),
        "credit_limit": r2(credit_limit),
        "utilisation": util,
        "reasons": reasons,
        "items": sorted(
            ({"invoice": it["invoice_number"], "invoice_date": it["invoice_date"], "due_date": it["due_date"],
              "days_past_due": it["days_past_due"], "bucket": it["bucket"], "amount_open": r2(it["amount_open"]),
              "row": it["row"]} for it in items),
            key=lambda x: (-x["days_past_due"], -(x["amount_open"] or 0))),
    }


def sort_key(c):
    return (-SEV_RANK[c["severity"]], 0 if c["limit_flag"] == "over_limit" else 1,
            -(c["buckets"]["over_90"] or 0), -(c["buckets"]["61_90"] or 0), -(c["past_due"] or 0),
            c["customer"].lower())


def portfolio(customers):
    """One summary per currency (amounts are never converted)."""
    out = {}
    by_cur = defaultdict(list)
    for c in customers:
        by_cur[c["currency"] or "unknown"].append(c)
    for cur, cs in by_cur.items():
        b = {k: sum(c["buckets"][k] for c in cs) for k in BUCKETS}
        gross = sum(b.values())
        credits = sum(c["credits"] for c in cs)
        past_due = gross - b["current"]
        pd_w = sum((c["weighted_avg_days_past_due"] or 0) * c["past_due"] for c in cs if c["past_due"] > 0)
        top = sorted((c["gross_open"] for c in cs), reverse=True)
        sev = Counter(c["severity"] for c in cs)
        out[cur] = {
            "customers": len(cs),
            "open_items": sum(c["open_items"] for c in cs),
            "gross_open": r2(gross),
            "credits": r2(credits),
            "net_open": r2(gross + credits),
            "past_due": r2(past_due),
            "past_due_share": (past_due / gross) if gross > 0 else None,
            "buckets": {k: r2(v) for k, v in b.items()},
            "bucket_shares": {k: (v / gross if gross > 0 else None) for k, v in b.items()},
            "weighted_avg_days_past_due": round(pd_w / past_due, 1) if past_due > 0 else None,
            "severity": {k: sev.get(k, 0) for k in SEV_RANK},
            "over_limit": sum(1 for c in cs if c["limit_flag"] == "over_limit"),
            "near_limit": sum(1 for c in cs if c["limit_flag"] == "near_limit"),
            "with_limit": sum(1 for c in cs if c["credit_limit"]),
            "top5_share": (sum(top[:5]) / gross) if gross > 0 else None,
            "largest_customer_share": (top[0] / gross) if gross > 0 and top else None,
        }
    return out


def safe_cell(v):
    """Stop spreadsheet apps treating text such as '=HYPERLINK(...)' as a formula."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def write_customers_csv(path, customers):
    cols = ["customer", "customer_id", "currency", "severity", "worst_bucket", "limit_flag", "net_open", "gross_open",
            "credits", "current", "1_30", "31_60", "61_90", "over_90", "past_due", "past_due_share",
            "oldest_days_past_due", "weighted_avg_days_past_due", "credit_limit", "utilisation", "open_items",
            "past_due_items", "reasons"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(cols)
        for c in customers:
            wr.writerow([
                safe_cell(c["customer"]), safe_cell(c["customer_id"] or ""), c["currency"] or "", c["severity"],
                c["worst_bucket"] or "", c["limit_flag"] or "", c["net_open"], c["gross_open"], c["credits"],
                *[c["buckets"][k] for k in BUCKETS], c["past_due"],
                "" if c["past_due_share"] is None else round(c["past_due_share"], 4),
                "" if c["oldest_days_past_due"] is None else c["oldest_days_past_due"],
                "" if c["weighted_avg_days_past_due"] is None else c["weighted_avg_days_past_due"],
                "" if c["credit_limit"] is None else c["credit_limit"],
                "" if c["utilisation"] is None else round(c["utilisation"], 4),
                c["open_items"], c["past_due_items"], safe_cell(" | ".join(c["reasons"])),
            ])


def write_items_csv(path, customers):
    cols = ["customer", "customer_id", "currency", "invoice", "invoice_date", "due_date", "days_past_due", "bucket",
            "amount_open", "source_row"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f)
        wr.writerow(cols)
        for c in customers:
            for it in c["items"]:
                wr.writerow([safe_cell(c["customer"]), safe_cell(c["customer_id"] or ""), c["currency"] or "",
                             safe_cell(it["invoice"] or ""), it["invoice_date"] or "", it["due_date"] or "",
                             it["days_past_due"], it["bucket"], it["amount_open"], it["row"]])


def parse_kv(items, what):
    out = {}
    for it in items or []:
        if "=" not in it:
            raise SystemExit(f"--{what} expects key=value, got '{it}'")
        k, v = it.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description="AR aging review")
    ap.add_argument("file")
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--out-dir", default="ar-aging-output")
    ap.add_argument("--as-of")
    ap.add_argument("--date-order", choices=["dmy", "mdy"])
    ap.add_argument("--map", action="append")
    ap.add_argument("--set", action="append")
    ap.add_argument("--customer")
    ap.add_argument("--sheet")
    ap.add_argument("--title", default="AR aging review")
    a = ap.parse_args(argv)

    try:
        cfg = build_config(parse_kv(a.set, "set"))
    except ValueError as e:
        print(f"INVALID OPTION: {e}")
        return 2
    if a.as_of:
        try:
            as_of = date.fromisoformat(a.as_of)
        except ValueError:
            print(f"INVALID OPTION: --as-of must be a date written as YYYY-MM-DD, got '{a.as_of}'.")
            return 2
    else:
        as_of = date.today()

    try:
        res = read_open_items(a.file, parse_kv(a.map, "map"), a.date_order, a.sheet)
    except ReadError as e:
        print(f"CANNOT READ FILE: {e}")
        return 2
    except FileNotFoundError:
        print(f"CANNOT READ FILE: no file at '{a.file}'.")
        return 2
    except Exception as e:  # noqa: BLE001 - anything else is reported, not dumped as a traceback
        print(f"CANNOT READ FILE: {type(e).__name__}: {e}. Try saving the file as CSV (UTF-8).")
        return 2

    items = res["items"]
    print(f"File: {os.path.basename(a.file)}  (header on row {res['header_row']}, {res['row_count']} data rows)")
    print("Columns used:")
    for f in FIELDS:
        if f in res["mapping"]:
            print(f"  {f:15} <- {res['mapping'][f]!r}")
    unused = [h for h in res["headers"] if h and h not in res["mapping"].values()]
    if unused:
        print(f"Columns not used: {unused}")
    print(f"Date format: {res['date_order'] or 'ISO/unambiguous'} ({res['date_order_basis']})")
    print(f"Open items: {len(items)}; skipped rows: {len(res['skipped'])}")
    for reason, n in Counter(s["reason"] for s in res["skipped"]).most_common(6):
        print(f"  skipped {n} x {reason}")

    # The as-of date decides every bucket: check it against the file
    inv_dates = [it["invoice_date"] for it in items if it["invoice_date"]]
    newest = max(inv_dates) if inv_dates else None
    if newest and not a.as_of and (as_of - date.fromisoformat(newest)).days > cfg["stale_export_days"]:
        res["warnings"].append(
            f"The newest invoice is dated {newest}, more than {cfg['stale_export_days']} days before today. If the "
            "export is older, re-run with --as-of set to the export date, or balances will look older than they are.")
    future = [it for it in items if it["invoice_date"] and it["invoice_date"] > as_of.isoformat()]
    if future:
        res["warnings"].append(f"{len(future)} invoices are dated after the as-of date {as_of.isoformat()}; "
                               "they are aged as current. Check the --as-of date.")
    if any(it["days_past_due_given"] is not None for it in items):
        res["warnings"].append("Some rows have no due date and use the file's days-past-due column as given, "
                               "whatever the as-of date.")
    for wmsg in res["warnings"][:12]:
        print(f"WARNING: {wmsg}")

    if a.inspect:
        print("Preview (first 5 open items):")
        for it in items[:5]:
            print(f"  row {it['row']}: {it['customer_name']} | invoice {it['invoice_number']} | due {it['due_date']} | "
                  f"open {it['amount_open']} {it['currency'] or ''}")
        return 0

    age_items(items, as_of, cfg["grace_days"])
    groups = defaultdict(list)
    for it in items:
        groups[(it["customer_key"], it["currency"])].append(it)
    customers = [analyse_customer(rows, res["credit_limits"].get(k[0]), cfg) for k, rows in groups.items()]
    if a.customer:
        q = a.customer.lower()
        customers = [c for c in customers if q in c["customer"].lower() or q in (c["customer_id"] or "").lower()]
        if not customers:
            names = sorted({rows[0]["customer_name"] for rows in groups.values()})
            print(f"No customer matches '{a.customer}'. Some names in the file: {names[:15]}")
            return 3
    customers.sort(key=sort_key)
    summary = portfolio(customers)

    os.makedirs(a.out_dir, exist_ok=True)
    result = {
        "tool": {"name": "ar-aging", "version": VERSION},
        "title": a.title,
        "source_file": os.path.basename(a.file),
        "as_of": as_of.isoformat(),
        "as_of_basis": "set by user" if a.as_of else "today",
        "config": cfg,
        "read": {k: res[k] for k in ("mapping", "date_order", "date_order_basis", "amount_basis", "warnings", "row_count")}
        | {"skipped": res["skipped"][:200], "skipped_count": len(res["skipped"])},
        "portfolio": summary,
        "customers": customers,
    }
    with open(os.path.join(a.out_dir, "results.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1, default=str)
    write_customers_csv(os.path.join(a.out_dir, "customers.csv"), customers)
    write_items_csv(os.path.join(a.out_dir, "open_items.csv"), customers)
    from dashboard import render
    with open(os.path.join(a.out_dir, "dashboard.html"), "w", encoding="utf-8") as f:
        f.write(render(result))

    print()
    print(f"Aged to {as_of.isoformat()} ({result['as_of_basis']}).")
    for cur, s in summary.items():
        label = "" if cur == "unknown" and len(summary) == 1 else f" [{cur}]"
        print(f"Portfolio{label}: {s['customers']} customers, {s['open_items']} open items, "
              f"net open {money(s['net_open'])} (invoices {money(s['gross_open'])}, credits {money(s['credits'])})")
        print("  Buckets: " + ", ".join(f"{BUCKET_LABEL[k]} {money(s['buckets'][k])} ({pct(s['bucket_shares'][k])})"
                                       for k in BUCKETS))
        print(f"  Past due: {money(s['past_due'])} = {pct(s['past_due_share'])} of invoices"
              + (f"; weighted average {s['weighted_avg_days_past_due']} days past due" if s["weighted_avg_days_past_due"] is not None else ""))
        print("  Customers by worst bucket: " + ", ".join(f"{SEV_LABEL[k]} {v}" for k, v in s["severity"].items() if v))
        if s["with_limit"]:
            print(f"  Credit limits: {s['with_limit']} customers have one; over limit {s['over_limit']}, "
                  f"near limit {s['near_limit']}")
        print(f"  Concentration: largest customer {pct(s['largest_customer_share'])}, top 5 {pct(s['top5_share'])} of invoices")
    top = [c for c in customers if c["severity"] != "none" or c["limit_flag"]][:10]
    if top:
        print("\nCollections priority (top 10):")
        for c in top:
            cur = f" {c['currency']}" if c["currency"] else ""
            print(f"  [{SEV_LABEL[c['severity']]}] {c['customer']}: past due {money(c['past_due'])}{cur} "
                  f"of {money(c['net_open'])}{cur} open. " + "; ".join(c["reasons"]))
    print(f"\nWrote {a.out_dir}/dashboard.html, customers.csv, open_items.csv, results.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
