# Input format

One row per paid invoice (or per payment applied to an invoice). CSV, semicolon CSV, tab-separated (including Excel's "Unicode Text" export) or Excel (.xlsx). Title rows above the header are fine (the header is looked for in the first 20 rows).

## Columns

| Field | Required | Recognised column names (case and punctuation ignored) |
|---|---|---|
| Customer | yes (name or ID) | customer name, customer, client, account name, debtor, buyer, company name, payer, sold to name, bill to name |
| Customer ID | recommended | customer id/number/no/code, account number/no/id, debtor number, client id, payer id, bp number |
| Payment date | yes | payment date, paid date, date paid, paid on, receipt date, date received, clearing date, cleared date, settlement date, value date, pay date |
| Due date | yes, or a days-late column | due date, net due date, invoice due date, payment due date, date due, maturity date, due |
| Days late | only if no due date | days late, days past due (at payment), days early late, dpd |
| Amount | recommended | amount paid, paid amount, payment amount, amount received, applied amount, cash applied, invoice amount, amount, total |
| Invoice number | optional | invoice number/no/id, invoice, document number, doc no |
| Invoice date | optional | invoice date, document date, issue date, billing date |

Deliberately **not** auto-matched: a bare "Date" column (could be anything) and anything containing "payment date" for the due date. Use `--map field="Column"` for anything unrecognised, e.g. `--map due_date="Fälligkeit"`.

When both a customer ID and a name exist, customers are grouped by ID, so name variants ("ACME Corp" / "Acme Corporation") count as one customer. A row with a name but no ID takes the ID used elsewhere in the file for that exact name.

## Dates

Accepted: `2026-03-04`, `04/03/2026`, `04.03.2026`, `4-Mar-2026`, `Mar 4, 2026`, any of these followed by a time, Excel date cells and Excel serial numbers. A month without a day (`Jan-2026`) is not accepted. Two-digit years: 00–69 → 2000s, 70–99 → 1900s.

Day/month order for numeric dates is detected from the file: any date with a day above 12 settles it. If every date is ambiguous (all days ≤ 12), the script stops and asks; pass `--date-order mdy` (US) or `--date-order dmy`. Files that mix both orders are rejected.

## Amounts

Accepted: `1234.56`, `$1,234.56`, `1.234,56`, `1 234,56 EUR`, `(1,234.56)`, `1234.56-`, `1,234.56 CR`. The decimal mark (`.` or `,`) is decided once for the whole column from values that settle it; values like `1.250` alone can't settle it and are read as decimals, with a warning. Currency is ignored (all amounts are treated as one currency). If the file mixes currencies, value weighting is approximate; say so.

Rows with zero or negative amounts (credit notes, reversals) are skipped and counted.

## Getting the export

Ask for a report of **paid or cleared customer invoices** over the last 12–24 months, at invoice level, with the due date and the date the payment was received or applied. Common names for it: customer payment history, cleared items, paid invoices, cash receipts by invoice, invoice payment detail. An AR aging report usually isn't enough: it shows what is open, not when invoices were paid.

At least 6 months of history is needed for the 90-day comparison; 12–24 months gives better trends.
