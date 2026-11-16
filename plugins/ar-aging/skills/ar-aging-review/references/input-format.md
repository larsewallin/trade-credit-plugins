# Input format

One row per **open** (unpaid or part-paid) invoice. CSV, semicolon CSV, tab-separated (including Excel's "Unicode Text" export) or Excel (.xlsx). Title rows above the header are fine (the header is looked for in the first 20 rows), and subtotal or "Total" lines are skipped.

## Columns

| Field | Required | Recognised column names (case and punctuation ignored) |
|---|---|---|
| Customer | yes (name or ID) | customer name, customer, client, account name, debtor, buyer, company name, payer, sold to name, bill to name |
| Customer ID | recommended | customer id/number/no/code, account number/no/id, debtor number, client id, payer id, bp number |
| Due date | yes, or a days-past-due column | due date, net due date, invoice due date, payment due date, date due, maturity date, due |
| Days past due | only if no due date | days past due, days overdue, past due days, overdue days, days late, dpd |
| Open amount | yes | open amount, outstanding amount, amount outstanding, outstanding, open balance, balance due, amount due, amount remaining, remaining balance, residual amount, unpaid amount, balance |
| Invoice amount | only if no open amount | invoice amount, original amount, document amount, gross amount, total amount, amount, total, value (treated as fully open, with a warning) |
| Currency | recommended if more than one | currency, currency code, curr, ccy, document currency, invoice currency |
| Credit limit | optional | credit limit, credit line, approved limit, approved credit limit, limit |
| Invoice number | optional | invoice number/no/id, invoice, document number, doc no, reference |
| Invoice date | optional (used to check the as-of date) | invoice date, document date, issue date, billing date, posting date |
| Status | optional | status, invoice status, document status, item status |

Use `--map field="Column"` for anything unrecognised, e.g. `--map amount_open="Offener Betrag"`.

When both a customer ID and a name exist, customers are grouped by ID. A row with a name but no ID takes the ID used elsewhere in the file for that exact name. The credit limit is read per customer; if a customer has different limits on different rows, the highest is used, with a warning.

## Rows that are skipped or kept apart

- Status `paid`, `closed`, `cleared`, `settled`, `cancelled`, `void`, `reversed` or `written off`: skipped.
- Zero open amount: skipped.
- Negative amounts (credit notes, unapplied cash, overpayments): kept as **credits**. They reduce the customer's balance but are not put in an aging bucket.
- No customer, or a "Total" line: skipped.

Every skipped row is counted with its reason.

## Dates and amounts

The same rules as the Payment Risk skill:
- **Dates** accepted: `2026-03-04`, `04/03/2026`, `04.03.2026`, `4-Mar-2026`, `Mar 4, 2026`, Excel dates and serial numbers.
- **Day/month order** is detected; if every date is ambiguous the script stops and asks (`--date-order mdy` or `dmy`).
- **Amounts** accepted: `1,234.56`, `1.234,56`, `(1,234.56)`, `1234.56-`, `1,234.56 CR`. The decimal mark is decided once per column.

## Currencies

Customers with invoices in two currencies appear once per currency. Totals are kept per currency and never converted.

## The as-of date

Every bucket depends on it. The default is today. For an export run on an earlier date, pass `--as-of` with that date; the script warns when the newest invoice in the file is more than 31 days old.

## Getting the export

Ask for **open items** or **AR aging detail**: one row per unpaid customer invoice, with the due date and the amount still open (not the original amount). Common names for it:
- customer open items
- aged receivables detail
- open invoices
- AR aging by invoice

A summary aging report (one row per customer with bucket columns) can't be used, because it has no due dates to re-age.
