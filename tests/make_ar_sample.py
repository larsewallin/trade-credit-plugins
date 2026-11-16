"""
Generates the AR Aging skill's sample open-items file (fictional customers, deterministic).
Same fictional customers as the Payment Risk sample, aged to 31 Oct 2026.

  python3 tests/make_ar_sample.py
"""

import csv
import os
import random
from datetime import date, timedelta

OUT = os.path.join(os.path.dirname(__file__), "..", "plugins", "ar-aging", "skills",
                   "ar-aging-review", "assets", "sample-open-items.csv")
AS_OF = date(2026, 10, 31)

# name, id, terms, credit limit, typical amount, [days past due of each open invoice (negative = not yet due)]
CUSTOMERS = [
    ("Harbor Point Fabrication", "C-1001", 30, 250000, 42000, [-25, -18, -12, -6, -3]),
    ("Larkspur Medical Supply", "C-1002", 45, 80000, 18500, [-30, -22, -8, 4]),
    ("Copperline Electric", "C-1003", 30, 80000, 9800, [-24, -20, -14, -6, 2, 9]),
    ("Pinecrest Furniture", "C-1004", 60, 150000, 27000, [-50, -40, -20, 18]),
    ("Tidewater Logistics", "C-1005", 30, 450000, 61000, [-26, -15, -8, 12, 38, 66]),
    ("Ironbark Construction", "C-1006", 45, 250000, 88000, [-20, 25, 47, 95, 128]),
    ("Saltmarsh Brewing", "C-1007", 30, 30000, 7400, [-10, 21, 44, 52]),
    ("Riverbend Plastics", "C-1008", 30, 60000, 15200, [-5, 15, 33, 35]),
    ("Meadowgate Retail Group", "C-1009", 60, 250000, 33500, [-45, -35, -20, -10, 8, 26]),
    ("Kestrel Aerospace Parts", "C-1010", 45, 300000, 54000, [-38, -30, -12, 3, 62]),
    ("Summit Ridge Outfitters", "C-1011", 30, 40000, 12600, [-25, -18, -2]),
    ("Quillfeather Print", "C-1012", 30, 10000, 5200, [-22, 14]),
]


def main():
    rng = random.Random(20261031)
    rows = []
    n = 70100
    for name, cid, terms, limit, amount, ages in CUSTOMERS:
        for dpd in ages:
            due = AS_OF - timedelta(days=dpd)
            inv = due - timedelta(days=terms)
            n += rng.randint(3, 40)
            amt = round(amount * rng.uniform(0.55, 1.35), 2)
            if dpd > 60 and rng.random() < 0.4:
                amt = round(amt * 0.6, 2)  # part-paid older invoice
            rows.append([name, cid, f"INV-{n}", inv.strftime("%m/%d/%Y"), due.strftime("%m/%d/%Y"),
                         f"{amt:,.2f}", "USD", f"{limit:,.0f}"])
    # A credit note and unapplied cash
    rows.append(["Meadowgate Retail Group", "C-1009", "CN-4411", "10/02/2026", "", "-4,250.00", "USD", "250,000"])
    rows.append(["Copperline Electric", "C-1003", "UNAPPLIED-0918", "09/18/2026", "", "-1,960.00", "USD", "80,000"])
    rows.sort(key=lambda r: (r[0], r[4] or "99"))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["AR open items as of 10/31/2026"])
        w.writerow([])
        w.writerow(["Customer Name", "Customer No", "Invoice No", "Invoice Date", "Due Date", "Open Amount",
                    "Currency", "Credit Limit"])
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows to {OUT}")


if __name__ == "__main__":
    main()
