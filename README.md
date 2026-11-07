# Trade credit plugins for Claude

Free, open-source Claude plugins for trade credit, credit management and receivables teams, by [Lars E. Wallin](https://larsewallin.com).

| Plugin | What it does |
|---|---|
| [Payment Risk](plugins/payment-risk) | Finds customers who are paying late, paying later over time, or paying erratically, from any payment history export. Ranked watchlist, dashboard, one-customer deep dives. |

More to come: AR aging, credit-limit calculation, collections letters, sanctions screening and new-customer checks. Suggestions welcome in Discussions.

## Install

**Claude Code**

```
/plugin install larsewallin-payment-risk --marketplace larsewallin/trade-credit-plugins
```

(Older Claude Code: `/plugin marketplace add larsewallin/trade-credit-plugins`, then `/plugin install larsewallin-payment-risk@larsewallin`.)

**Claude app:** add *Payment Risk by Lars E. Wallin* from the plugin directory once it's listed, or download `larsewallin-payment-risk.plugin` from the latest release and open it, or add this repository as a plugin marketplace.

Then ask Claude: *"Run a payment risk review on the sample data."*

## Principles

- **Your data stays with you.** Analysis runs locally; plugins make no network calls unless they say so.
- **Numbers come from code, not from the model.** Claude explains results; scripts compute them.
- **Thresholds are yours.** Defaults come from production use; every one can be changed.

## Development

```
python3 tests/test_engine.py     # engine tests (ported from the production TypeScript suite)
python3 tests/test_reader.py     # file reading + end-to-end
python3 tests/make_sample.py     # regenerate the sample file
```

No dependencies (Python 3.9+). `openpyxl` is used for .xlsx files when installed.

Built by [Lars E. Wallin](https://larsewallin.com), who writes about AI in trade credit. MIT licence.
