# AR Aging

A Claude skill that ages an accounts receivable open-items export customer by customer, and tells you whom to chase first.

It uses the aging rules of a production AR aging agent, open-sourced by [Lars E. Wallin](https://larsewallin.com), on your own file. Nothing leaves your machine: the analysis is a local Python script with no network calls and no dependencies.

## Install

- **Claude app:** download `ar-aging-review.zip` from [larsewallin.com](https://larsewallin.com). Then in Claude open Settings → Capabilities, turn on code execution and upload the ZIP under Skills.
- **Claude Code:** `/plugin install larsewallin-ar-aging --marketplace larsewallin/trade-credit-plugins`

## What you get

- **Collections priority list:** customers sorted by their worst bucket, then over-limit accounts, then the largest old balances. Each comes with the reason in plain words, e.g. "169,153.27 USD is over 90 days past due (oldest 128 days); over the credit limit by 125,860.08 USD".
- **An interactive dashboard:** one HTML file that works offline and can be emailed. It shows:
  - the open balance, past-due share and amount over 90 days
  - open invoices by age
  - concentration
  - filters, search and click-through to each customer's open items
- **Spreadsheets:** one row per customer, and one row per open invoice with its days past due and bucket.

Ask Claude something like *"Age this open items export"*, *"Who should we chase first?"* or *"How much is over 90 days?"*. No file to hand? Ask for an AR aging of the sample data (12 fictional customers).

## Rules

- **Buckets:** Current, 1–30, 31–60, 61–90, over 90 days past due.
- **Severity:** set by the worst bucket. Over 90 is critical, 61–90 high, 31–60 medium, 1–30 low.
- **Credits:** credit notes and unapplied cash reduce the balance but never sit in a bucket.
- **Currencies:** kept apart and never converted.
- **Credit limits:** limit use is shown when the file has a credit limit.

See [methodology](skills/ar-aging-review/references/methodology.md) and [input format](skills/ar-aging-review/references/input-format.md).

## Limits

Aging shows how old balances are, not why: disputes and agreed extensions look overdue too. It is not a credit rating or a default prediction.

## Licence

MIT
