# Methodology

The rules are taken from the production AR aging agent this skill was extracted from (an open-source trade credit monitoring system). Every number is computed by `scripts/ar_aging.py`.

## Days past due and buckets

`days past due = as-of date − due date` (calendar days). Where the file has no due date but a days-past-due column, that value is used as given.

| Bucket | Days past due |
|---|---|
| Current | 0 or less (not yet due), or up to `grace_days` |
| 1–30 | 1 to 30 |
| 31–60 | 31 to 60 |
| 61–90 | 61 to 90 |
| Over 90 | 91 and more |

Negative amounts (credit notes, unapplied cash) are **credits**: they reduce the customer's net balance and are not put in a bucket.

## Customer severity

The oldest bucket with a past-due amount decides it:

| Worst bucket | Severity |
|---|---|
| Over 90 | Critical |
| 61–90 | High |
| 31–60 | Medium |
| 1–30 | Low |
| nothing past due | Current |

## Credit limit use

`utilisation = net open balance ÷ credit limit` (only when the file has a credit limit).
- **Over limit:** above 100%.
- **Near limit:** above `utilisation_high_pct` (default 80%).

In the production system, high utilisation on its own is not treated as a risk (a strong customer using its line is normal). It counts when the account is over the limit, or when it comes with weak payment signals. The report shows both, so the reader can judge.

## Collections priority

Customers are listed in this order:
1. severity (Critical first)
2. over-limit accounts
3. amount over 90 days
4. amount at 61–90 days
5. total past due

## Portfolio figures (per currency)

| Figure | How it's calculated |
|---|---|
| Open balance | invoices + credits |
| Past due share | past-due invoices ÷ all open invoices (credits excluded) |
| Weighted average days past due | amount-weighted, over past-due invoices only |
| Concentration | the largest customer's share and the top five customers' share of open invoices |

## Settings

| Key | Default | Meaning |
|---|---|---|
| `grace_days` | 0 | items up to this many days past due count as current |
| `utilisation_high_pct` | 80 | "near limit" above this percentage of the credit limit |
| `stale_export_days` | 31 | warn when the newest invoice is older than this before the as-of date |

Change with `--set key=value`.

## Limits

Aging measures how old balances are on the user's own invoices. It does not explain why, and it is not a credit rating or a default prediction.
