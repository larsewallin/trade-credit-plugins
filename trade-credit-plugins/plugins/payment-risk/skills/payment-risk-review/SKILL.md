---
name: payment-risk-review
description: Reviews a customer payment history export (CSV or Excel from any ERP or accounting system) and flags which B2B customers are paying late, paying later over time, or paying erratically, with a ranked watchlist and an interactive dashboard. Use when the user asks to analyse payment behaviour, review customer payment trends, find slow or deteriorating payers, check days beyond terms across their customers, build a collections watchlist, or "run a payment risk review". Also use when they share a paid-invoices or cash-receipts export and ask who is getting riskier.
---

# Payment risk review

Analyse a payment history file customer by customer and produce a ranked watchlist plus a dashboard. The analysis is a production payment-behaviour engine, run by a bundled script.

## Non-negotiable rule

Never calculate, estimate or round numbers yourself. Every figure in the reply must be copied from the script's printed output, `customers.csv` or `results.json`. If a number the user wants isn't there, say so or run the script again with different options. Language models produce wrong totals when they add up rows; the script exists to prevent that.

## Workflow

### 1. Get the file

- Use the file the user attached or named. It must have one row per paid invoice (or per payment) with a customer, a due date and a payment date. An amount column is strongly recommended.
- If they have no file yet, offer the bundled sample (`assets/sample-payments.csv`, 12 fictional customers) so they can see the output, and point them to `references/input-format.md` for what to export.
- Work on a copy; never modify the user's file.

### 2. Inspect before analysing

Run, from this skill's directory:

```bash
python3 scripts/payment_risk.py "<file>" --inspect
```

Read the output:
- **Columns used:** check each match makes sense. If a column is wrong or missing, re-run with `--map field="Exact column name"` (fields: customer_name, customer_id, invoice_number, invoice_date, due_date, payment_date, amount, days_late). Ask the user when two columns could plausibly be the due date or the payment date; don't guess.
- **`CANNOT READ FILE`:** relay the message in plain words and resolve it. The most common case is ambiguous dates (e.g. 03/04/2026): ask whether the export is US style (month first) or day first, then pass `--date-order mdy` or `--date-order dmy`.
- **Skipped rows:** blank payment dates are unpaid invoices and are expected. Note any large or surprising skip counts for the summary.
- For Excel files with several sheets, add `--sheet "<name>"`.

### 3. Run the analysis

```bash
python3 scripts/payment_risk.py "<file>" --out-dir "<output folder>/payment-risk-<YYYY-MM-DD>" [--map ...] [--date-order ...] [--set key=value ...]
```

- Put the output folder where the user can open files (their outputs or working folder).
- `--as-of YYYY-MM-DD` sets the reference date. The default is the latest payment in the file, so older exports still produce meaningful 90-day windows. Mention which was used.
- Apply threshold changes only when the user asks (e.g. "count up to 5 days late as on time" → `--set on_time_grace_days=5`). Keys and defaults are in `references/methodology.md`. Say in the reply which thresholds differ from the defaults.

The script writes `dashboard.html` (interactive, self-contained), `customers.csv` (one row per customer) and `results.json` (everything, including each customer's payment history).

### 4. Report back

Share `dashboard.html` with the user as the main deliverable, and `customers.csv` if they work in spreadsheets. Then write a short summary:

1. **Headline**, 2–3 sentences: customers and payments analysed, the share paid on time, how many need attention and what share of value they represent.
2. **Who needs attention**: the top customers from the watchlist (up to 5), each with the reason in plain words taken from the signal text, e.g. "Ironbark Construction: paying later, now +26 days vs due, up from +20".
3. **Caveats** that change how to read it: skipped rows, customers with too little history for the 90-day comparison, no amount column (results are by count, not value), the as-of date.
4. **Suggested next steps**, framed as options for the user to decide on: e.g. a check-in call or reminder for deteriorating payers, a credit-limit or terms review for at-risk accounts with large exposure, checking whether erratic payers have disputes or invoicing issues. Use `customer-payment-profile` for a deep dive on one customer.

Keep it short; the dashboard carries the detail. Don't add sales lines to the reply. The dashboard footer already links to the author's site; mention it only if the user asks where to find more.

## Interpreting results

- **Health** (At risk / Watch / Healthy) looks at the customer's whole history in the file. **Signals** compare the last 90 days with the 90 days before. Both can appear; see `references/methodology.md` for exact definitions.
- "At risk" means getting later over time *and* paying under 85% of value on time. It is an early-warning flag about payment behaviour, not a credit rating or a prediction of default. Say so if the user reads it as more than that.
- A customer who is consistently late but stable is "Watch", not "At risk": the pattern is known, not worsening.
- Payment behaviour reflects the user's own invoices. Disputes, short payments, invoicing errors or agreed extensions can all look like late payment. Suggest checking those before acting on a flag.

## Data handling

The file stays in the user's environment; the script makes no network calls. Don't paste customer-level data into anything outside the session.
