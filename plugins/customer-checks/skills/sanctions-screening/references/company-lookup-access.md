# Reaching Company Lookup

Company Lookup is a free, open-source service (github.com/larsewallin/company-lookup) that reads official company registers, GLEIF, EU VIES, Wikidata, domain records and the OFAC, EU, UN and UK sanctions lists. Use the first route that works.

## 1. The connector (best)

If the tools `search_companies`, `get_company_card` and `screen_sanctions` are available, use them. To add the connector in Claude:
1. Open **Settings → Connectors → Add custom connector**.
2. Name it **Company Lookup**, with the URL `https://open-company-lookup.vercel.app/api/mcp` and no authentication.
3. Allow the tools when Claude first asks.

## 2. The HTTP API

Use this when there is no connector but you can fetch web pages or run code with internet access. The base URL is `https://open-company-lookup.vercel.app`.

| What | Request |
|---|---|
| Search | `GET /v1/search?q=<name or number>&country=<ISO code>` |
| Company card | `GET /v1/company?id=<id from search>&website=<domain, optional>` |
| Sanctions screening, one name | `GET /v1/sanctions?name=<company name>&country=<ISO code>` |
| Sanctions screening, up to 50 names | `POST /v1/sanctions` with JSON `{"names": [{"name": "...", "country": "GB"}]}` |

The responses are JSON; the full contract is in `docs/api-v1.md` in the repository. Errors look like `{"error": {"code", "message"}}`.

## 3. Neither works

Say so plainly. Tell the user how to add the connector (route 1). Don't fill in register facts from memory or from a general web search, and don't present them as checked.
