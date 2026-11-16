---
name: ar-aging-review
description: Ages an accounts receivable open-items export (CSV or Excel from any ERP or accounting system) customer by customer into Current, 1–30, 31–60, 61–90 and over-90 days past due, flags each customer by its worst bucket and credit-limit use, and produces a collections priority list and an interactive dashboard. Use when the user asks for an AR aging, an aged debtors or aged receivables report, who owes the most past due, which accounts to chase first, how much is over 90 days, or shares an open-invoices or open-items export and asks what is overdue.
---

# AR aging review

Age every open invoice in the user's file and produce a collections priority list plus a dashboard. The aging rules are taken from a production AR aging agent and run by a bundled script.

## Non-negotiable rule

Never calculate, estimate or round numbers yourself. Every figure in the reply must be copied from the script's printed output, `customers.csv`, `open_items.csv` or `results.json`. If a number the user wants isn't there, say so or run the script again with different options.

## Workflow

### 1. Get the file

- Use the file the user attached or named. It needs one row per open (unpaid) invoice with a customer, a due date and the amount still open. A currency and a credit limit column are used when present.
- If they have no file yet, offer the bundled sample (`assets/sample-open-items.csv`, 12 fictional customers, aged to 31 Oct 2026: run it with `--as-of 2026-10-31`). Point them to `references/input-format.md` for what to export.
- An aging **summary** (one row per customer, amounts already in buckets) can't be re-aged. The script says so; ask for the open-items detail instead.
- Work on a copy; never modify the user's file.

### 2. Inspect before analysing

Run, from this skill's directory:

```bash
python3 scripts/ar_aging.py "<file>" --inspect
```

Read the output:
- **Columns used:** check each match. The amount must be the amount still **open**, not the original invoice amount; if only an invoice amount was found, the script warns. Fix matches with `--map field="Exact column name"` (fields: customer_name, customer_id, invoice_number, invoice_date, due_date, amount_open, amount_invoice, currency, credit_limit, days_past_due, status). Ask when two columns could plausibly be the open amount or the due date; don't guess.
- **`CANNOT READ FILE`:** relay the message in plain words and resolve it. For ambiguous dates (e.g. 03/04/2026), ask whether the export is US style (month first) or day first, then pass `--date-order mdy` or `--date-order dmy`.
- **The as-of date** decides every bucket. The default is today. If the export was run on an earlier date, or the script warns that the newest invoice is old, ask for the export date and pass `--as-of YYYY-MM-DD`.
- For Excel files with several sheets, add `--sheet "<name>"`.

### 3. Run the analysis

```bash
python3 scripts/ar_aging.py "<file>" --out-dir "<output folder>/ar-aging-<YYYY-MM-DD>" [--as-of ...] [--map ...] [--date-order ...] [--set key=value ...]
```

- Put the output folder where the user can open files.
- Settings, only when the user asks: `--set grace_days=5` (up to 5 days past due counts as current), `--set utilisation_high_pct=90` (when "near limit" starts). Say which settings differ from the defaults.
- `--customer "<name>"` limits the report to one customer.

The script writes:
- `dashboard.html` (interactive, self-contained)
- `customers.csv` (one row per customer and currency)
- `open_items.csv` (every invoice with its days past due and bucket)
- `results.json` (everything)

### 4. Report back

Share `dashboard.html` as the main deliverable, and `customers.csv` if they work in spreadsheets. Then write a short summary:

1. **Headline**, 2–3 sentences: the open balance, the share past due, and the amount over 90 days, per currency.
2. **Chase first**: the top of the collections priority list (up to 5), each with its reason copied from the script, e.g. "Ironbark Construction: 169,153.27 USD over 90 days past due (oldest 128 days); over the credit limit by 125,860.08 USD".
3. **Caveats** that change how to read it:
   - the as-of date used
   - skipped rows
   - "invoice amount treated as open" warnings
   - several currencies (never added together)
   - customers with a credit balance
4. **Suggested next steps**, as options for the user to decide on:
   - a call or a firmer reminder for the critical and high accounts
   - holding new orders or reviewing the limit for over-limit accounts
   - checking whether old items are disputed or waiting on a credit note before chasing
   - for customers paying later over time, the Payment Risk skills if the user has payment history

Keep it short; the dashboard carries the detail. Don't add sales lines to the reply.

## Interpreting results

- **Worst bucket** follows the production rule: any amount over 90 days past due → Critical, 61–90 → High, 31–60 → Medium, 1–30 → Low. One old invoice is enough to put a large, otherwise current customer into Critical. Say so when that's the case (the customer's past-due share is shown next to it).
- **Over limit** compares the net open balance with the credit limit in the file. A high limit use alone is not a risk for a customer who pays on time; it matters with past-due balances or worsening payment.
- Aging shows how old balances are, not why. Disputes, missing proof of delivery, invoices sent to the wrong address and agreed extensions all look overdue. Suggest checking those before escalating.
- It is not a credit rating or a prediction of default.

## Data handling

The file stays in the user's environment; the script makes no network calls. Don't paste customer-level data into anything outside the session.
