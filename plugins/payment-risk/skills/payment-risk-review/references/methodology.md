# Methodology

The plugin runs two engines ported from production code. The port is verified result-for-result against the original TypeScript on 3,000 random cases.

All lateness is measured in **days relative to the due date**: `payment date − due date`. Positive = late, negative = early, 0 = on the due date.

## 1. Payment behaviour (whole history in the file)

| Metric | Definition |
|---|---|
| On-time rate | Share of payment **value** paid on time (no later than the grace days after due). Large invoices count more than small ones. Without an amount column, each payment counts equally. |
| Last 3 | Same, for the most recent 3 payments only. |
| Avg days late | Value-weighted average of days late (negative = pays early on average). |
| Avg days to pay | Value-weighted average of payment date − invoice date. Shown only when every payment has an invoice date. |
| Trend | History split into an older and a newer half (by payment date). If the newer half is more than 3 days later on average (value-weighted) → deteriorating; more than 3 days earlier → improving; otherwise stable. Needs at least 2 payments. |

**Health**, evaluated in this order:

1. **At risk**: trend is deteriorating **and** on-time rate is below 85%.
2. **Watch**: on-time rate below 70%, **or** average more than 15 days late, **or** deteriorating while still paying 85%+ on time.
3. **Healthy**: everything else.
4. **Unknown**: no usable payments.

## 2. Recent change (last 90 days vs the 90 days before)

Compares the plain (not value-weighted) average of days late in two adjacent windows: the current window runs from 90 days before the as-of date up to and including it; the prior window is the 90 days before that. The as-of date is the latest payment in the file unless set; payments after a chosen as-of date are left out of the whole analysis. Each signal is independent; a customer can have several.

| Signal | Fires when | Severity |
|---|---|---|
| Paying later | current average is at least 5 days later than prior **and** current average is above 0 (actually late) | 5–10 days: medium · 10–20: high · 20+: critical |
| Paying earlier | current average is at least 5 days earlier than prior **and** prior average was above 0 | info below 10 days, low from 10 (never escalated) |
| Erratic timing | population standard deviation of days late in the current window is 10+ days | 10–20: high · 20+: critical |

All three signals need at least one payment in **each** window (as in the production engine). With monthly invoicing that means about six months of history. Erratic timing is measured on the current window only, so it needs two or more payments there to show any spread.

## Attention ranking

- **High**: health is At risk, or any high/critical paying-later or erratic signal.
- **Medium**: health is Watch, or a medium paying-later signal.
- **Low**: everything else.

Within each level, customers are ordered by worst signal severity, then number of warning signals, then health, then value paid (largest first).

## Thresholds you can change

Pass `--set key=value` (repeatable). Defaults are the production values.

| Key | Default | Meaning |
|---|---|---|
| `on_time_grace_days` | 0 | Paid up to N days after due still counts as on time (whole number) |
| `trend_delta_days` | 3 | Half-vs-half change that counts as a trend |
| `at_risk_on_time_below` | 0.85 | At risk needs on-time rate below this (with a deteriorating trend) |
| `watch_on_time_below` | 0.70 | Watch when on-time rate is below this |
| `watch_avg_days_late_above` | 15 | Watch when average days late is above this |
| `recent_count` | 3 | Payments in the "Last N" rate (whole number, 1 or more) |
| `window_days` | 90 | Length of each comparison window (whole number, 7 or more) |
| `swing_days` | 5 | Minimum change for paying later/earlier |
| `high_swing_days` | 10 | High severity from this change |
| `critical_swing_days` | 20 | Critical severity from this change |
| `volatility_stddev_days` | 10 | Erratic timing from this standard deviation |
| `critical_volatility_stddev_days` | 20 | Critical erratic timing from this |

Good reasons to change them: a company that treats a few days' slack as on time (`on_time_grace_days`), weekly invoicing (shorter `window_days` works), or quarterly invoicing (longer `window_days`).

## Limitations

- Behaviour is measured on the user's own invoices only.
- Disputes, short payments, credit notes, agreed extensions and invoicing errors can look like late payment.
- Unpaid invoices are excluded (no payment date). A customer who has stopped paying altogether is better caught by an AR aging review; the dashboard shows "days since last payment" in each customer's detail.
- Flags describe behaviour; they are not a credit rating or default probability.
