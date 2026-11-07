"""
Generates the plugin's sample file (fictional customers, deterministic).
Each customer follows a designed pattern so the review has something to find.

  python3 tests/make_sample.py
"""

import csv
import os
import random
from datetime import date, timedelta

OUT = os.path.join(os.path.dirname(__file__), "..", "plugins", "payment-risk", "skills",
                   "payment-risk-review", "assets", "sample-payments.csv")
END = date(2026, 9, 30)
START = date(2025, 4, 1)

# name, id, terms, invoices/month, typical amount, pattern
CUSTOMERS = [
    ("Harbor Point Fabrication", "C-1001", 30, 3, 42000, "early"),
    ("Larkspur Medical Supply", "C-1002", 45, 2, 18500, "early"),
    ("Copperline Electric", "C-1003", 30, 4, 9800, "on_time"),
    ("Pinecrest Furniture", "C-1004", 60, 1, 27000, "on_time"),
    ("Tidewater Logistics", "C-1005", 30, 3, 61000, "slipping_big"),
    ("Ironbark Construction", "C-1006", 45, 2, 88000, "deteriorating_sharp"),
    ("Saltmarsh Brewing", "C-1007", 30, 2, 7400, "deteriorating"),
    ("Riverbend Plastics", "C-1008", 30, 2, 15200, "chronic_late"),
    ("Meadowgate Retail Group", "C-1009", 60, 3, 33500, "chronic_late_mild"),
    ("Kestrel Aerospace Parts", "C-1010", 45, 2, 54000, "volatile"),
    ("Summit Ridge Outfitters", "C-1011", 30, 2, 12600, "improving"),
    ("Quillfeather Print", "C-1012", 30, 1, 5200, "new"),
]


def lateness(pattern, progress, rng):
    """progress: 0 at START -> 1 at END. Returns days late (negative = early)."""
    j = rng.gauss(0, 2.5)
    if pattern == "early":
        return round(-6 + j)
    if pattern == "on_time":
        return round(-1 + j)
    if pattern == "slipping_big":       # mostly on time, drifting later lately
        return round(-3 + (9 * max(0, progress - 0.6) / 0.4) + j * 0.6)
    if pattern == "deteriorating_sharp":
        return round(-2 + (34 * max(0, progress - 0.55) / 0.45) ** 1.1 + j)
    if pattern == "deteriorating":
        return round(1 + 16 * progress + j)
    if pattern == "chronic_late":
        return round(22 + j * 1.6)
    if pattern == "chronic_late_mild":
        return round(9 + j * 2.2)
    if pattern == "volatile":
        return round(rng.choice([-10, -4, 2, 14, 30, 38]) + j)
    if pattern == "improving":
        return round(26 - 26 * progress + j)
    if pattern == "new":
        return round(2 + j)
    raise ValueError(pattern)


def main():
    rng = random.Random(20261031)
    rows = []
    inv_no = 50000
    span = (END - START).days
    for name, cid, terms, per_month, typical, pattern in CUSTOMERS:
        start = START if pattern != "new" else END - timedelta(days=95)
        d = start
        while d < END - timedelta(days=terms - 20):
            for _ in range(per_month):
                inv_date = d + timedelta(days=rng.randint(0, 27))
                due = inv_date + timedelta(days=terms)
                inv_no += 1
                amount = round(typical * rng.uniform(0.55, 1.45), 2)
                progress = (due - START).days / span
                pay = due + timedelta(days=lateness(pattern, progress, rng))
                paid = pay if pay <= END else None   # not yet paid at export date
                rows.append([name, cid, f"INV-{inv_no}", inv_date, due, paid, amount])
            d += timedelta(days=30)
    # A credit note (should be skipped) and a duplicate-looking re-export line
    rows.append(["Copperline Electric", "C-1003", "CN-7710", date(2026, 6, 3), date(2026, 7, 3),
                 date(2026, 6, 20), -1450.00])
    rows.sort(key=lambda r: (r[3], r[2]))

    def us(d):
        return "" if d is None else d.strftime("%m/%d/%Y")

    def amt(a):
        return f"-${abs(a):,.2f}" if a < 0 else f"${a:,.2f}"

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Customer Name", "Customer ID", "Invoice No", "Invoice Date", "Due Date", "Payment Date", "Amount Paid"])
        for r in rows:
            w.writerow([r[0], r[1], r[2], us(r[3]), us(r[4]), us(r[5]), amt(r[6])])
    print(f"wrote {len(rows)} rows to {os.path.normpath(OUT)}")


if __name__ == "__main__":
    main()
