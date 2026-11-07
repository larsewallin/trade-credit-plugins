# Payment Risk

A Claude plugin that reads a customer payment history export and tells you which B2B customers are paying late, paying later over time, or paying erratically.

It runs a production payment-behaviour engine, open-sourced by [Lars E. Wallin](https://larsewallin.com), on your own file. Nothing leaves your machine: the analysis is a local Python script with no network calls and no dependencies.

## Install

Claude Code:

```
/plugin install larsewallin-payment-risk --marketplace larsewallin/trade-credit-plugins
```

Claude app: add *Payment Risk by Lars E. Wallin* from the plugin directory once it's listed, or download `larsewallin-payment-risk.plugin` from the repository's latest release and open it.

## What you get

- **A ranked watchlist**: customers sorted by urgency, each with the reason in plain words ("Paying later: +26.4 days vs due in the last 90 days, +20.3 before").
- **An interactive dashboard**: one HTML file that works offline and can be emailed. It has the portfolio's on-time rate, value by payment health, filters, search, a payment-timing sparkline per customer, and click-through to the reasons and recent payments.
- **A spreadsheet**: one row per customer, all metrics.
- **One-customer deep dives**: a profile with the pattern, possible explanations and talking points for a collections call or credit review.

## Skills

| Skill | Ask Claude something like |
|---|---|
| `payment-risk-review` | "Run a payment risk review on this export", "Which customers are getting slower to pay?" |
| `customer-payment-profile` | "How does Ironbark pay?", "Prepare me for a call with Kestrel about their payments" |

No file to hand? Ask for a review of the sample data; the plugin ships with 12 fictional customers.

## What it checks

- **Payment health** over the whole history: share of value paid on time, average days late, and whether the newer half of the history is later than the older half → At risk / Watch / Healthy.
- **Recent change**: last 90 days vs the 90 days before → paying later, paying earlier, erratic timing, each with a severity.

Every threshold can be changed (for example, count up to 5 days late as on time). See [methodology](skills/payment-risk-review/references/methodology.md).

## Input

One row per paid invoice with a customer, due date and payment date; an amount is recommended. CSV or Excel from any ERP or accounting system. Column names are recognised automatically, and day/month order is detected (it asks when it can't tell). See [input format](skills/payment-risk-review/references/input-format.md).

## Limits

The plugin measures behaviour on your own invoices only. Disputes, credit notes and agreed extensions can look like late payment. Flags are early warnings, not a credit rating or a default prediction.

## More

More free plugins for credit teams, and essays on AI in trade credit, at [larsewallin.com](https://larsewallin.com).

## Licence

MIT
