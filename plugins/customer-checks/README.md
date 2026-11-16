# Customer Checks

Two Claude skills for checking new B2B customers and suppliers against official records. Facts come from [Company Lookup](https://github.com/larsewallin/company-lookup), a free, open-source service by Lars E. Wallin that reads:
- official company registers in over 30 countries
- GLEIF
- EU VAT (VIES)
- domain records
- the OFAC, EU, UN and UK sanctions lists

| Skill | Ask Claude something like |
|---|---|
| `new-customer-check` | "Check this new customer: Acme Trading Ltd, UK, 01234567", "Review this credit application" |
| `sanctions-screening` | "Screen our customer list against sanctions lists", "Is Rosneft on any sanctions list?" |

## Set up

1. **Add the Company Lookup connector in Claude.** Open Settings → Connectors → Add custom connector, use the URL `https://open-company-lookup.vercel.app/api/mcp`, and choose no authentication. Without the connector, the skills use Company Lookup's HTTP API when Claude can reach the internet.
2. **Add the skills.**
   - **Claude app:** download the ZIPs from [larsewallin.com](https://larsewallin.com), then upload them under Settings → Capabilities → Skills.
   - **Claude Code:** `/plugin install larsewallin-customer-checks --marketplace larsewallin/trade-credit-plugins`

## What you get

- **New customer check:** a one-page memo for the credit file, with:
  - identity and status, each with its source and date
  - ownership and group
  - what the customer told you vs the register
  - sanctions screening
  - flags and gaps
  - a verification level (Exists → Matches → Corroborated → Clean)
  - what to request before extending credit
- **Sanctions screening:** one company, or a whole customer list from CSV or Excel. You get a results CSV, possible matches with the list, programme, listing date and link, and steps for reviewing a match.

## Limits

These are not a compliance system, a credit rating or legal advice.
- A sanctions name match is a possible match to review, never a finding.
- Only companies are screened, not individuals.
- Ownership is not screened. Under OFAC's 50 percent rule, a company owned by listed parties can be restricted without being listed.

## Licence

MIT
