---
name: customer-payment-profile
description: Builds a payment profile for one B2B customer from a payment history export, explaining how they pay, whether it is getting worse, and what to do about it, with talking points for a collections call or credit review. Use when the user asks how a specific customer pays, wants a deep dive on one account, is preparing for a call, renewal or credit-limit review with a customer, or asks whether one customer's payment behaviour supports extending more credit or better terms.
---

# Customer payment profile

Deep dive on one customer, using the same engine and script as `payment-risk-review`. The script lives in the sibling skill: `../payment-risk-review/scripts/payment_risk.py` (relative to this skill's directory).

## Non-negotiable rule

Never calculate or estimate numbers yourself. Quote figures only from the script's output, `customers.csv` or `results.json`. Payment-by-payment details come from the `history` list in `results.json`.

## Workflow

1. **Get the file and the customer name.** If the user already ran a portfolio review in this session, reuse the same file and options (column mappings, date order, thresholds).
2. **Inspect first** if the file is new: `python3 ../payment-risk-review/scripts/payment_risk.py "<file>" --inspect`, and resolve column or date-format issues exactly as described in the payment-risk-review skill.
3. **Run for that customer:**
   ```bash
   python3 ../payment-risk-review/scripts/payment_risk.py "<file>" --customer "<name or ID>" --out-dir "<output folder>/payment-profile-<customer>-<YYYY-MM-DD>" --title "Payment profile: <customer>"
   ```
   `--customer` matches part of the name or ID. If several customers match, ask which one. If none match, the script prints names from the file; offer the closest.
4. **Read `results.json`** for that customer: health, on-time rates, average days late, the 90-day window comparison, signals and the payment history.

## The profile

Share the generated `dashboard.html` and write:

1. **Verdict in one sentence**: e.g. "Pays reliably about 6 days early, no change in the last six months" or "Has slipped from about on time to around 26 days late since spring".
2. **The numbers that matter**: on-time share by value overall and for the last 3 payments, average days late, last 90 days vs the 90 before, and the number of payments behind these figures (fewer than 6 payments means low confidence; say so).
3. **The pattern**, described from the payment history: when the change started, whether it is gradual or a step, whether lateness clusters on large invoices, and any single outliers. Describe only what the history list shows.
4. **What it could mean**: possible explanations to check, not conclusions: cash-flow pressure, a dispute or invoicing problem, a change of payables contact or process, seasonality. Be clear that payment data alone can't tell these apart.
5. **Next steps, as options**, matched to the situation:
   - Healthy or improving: no action, or room to discuss better terms or a higher limit if commercially wanted.
   - Watch (consistently late but stable): talk about terms that match how they actually pay, or reminder timing.
   - Paying later / at risk: a check-in call before the next large invoice falls due; review open exposure and the credit limit; consider shorter terms or security for new orders.
   - Erratic: check for disputes, short payments or invoicing issues first.
6. **Talking points** if the user is preparing a call: 3–5 factual, non-accusatory points based on the figures. Offer to draft a reminder or check-in email; if drafted, keep it courteous and factual and never imply legal action unless the user asks for it.

## Limits to state when relevant

- The profile covers only the payments in the file: the user's own invoices with this customer, not the customer's behaviour with other suppliers.
- It isn't a credit rating or a default prediction. For a credit decision, combine it with financials, credit agency data and exposure.
