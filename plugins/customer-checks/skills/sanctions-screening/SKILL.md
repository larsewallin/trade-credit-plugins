---
name: sanctions-screening
description: Screens company names (one customer, supplier or a whole customer list from CSV or Excel) against the official US OFAC, EU, UN and UK sanctions lists via Company Lookup, and reports possible matches with the list, programme and listing date for review. Use when the user asks to screen customers or suppliers against sanctions lists, check whether a company is on OFAC, the EU, UN or UK lists, run a periodic sanctions check on their customer base, or review a sanctions hit.
---

# Sanctions screening

Screen company names against four official lists, refreshed daily, through **Company Lookup**:
- the US OFAC SDN list and Consolidated (non-SDN) list
- the EU consolidated financial sanctions list
- the UN Security Council consolidated list
- the UK Sanctions List

See `references/company-lookup-access.md` for the connector (`screen_sanctions`) and the HTTP API (`/v1/sanctions`).

## Rules

- **A name match is a possible match, never a finding.** Similar and identical names are common. Never write that a company "is sanctioned" or "is on the list" unless the user has confirmed identity. Write "possible match to review".
- **Not a compliance system.** Say so once, plainly, in every report. Screening names cannot see ownership. Under OFAC's 50 percent rule and similar EU and UK rules, a company owned by listed parties can be restricted without being listed itself.
- **Companies only.** The index holds entities, not individuals. Don't screen directors or owners by name, and don't present the result as covering them.
- Copy list names, programmes, dates and links exactly from the result; don't paraphrase a listing into a claim.

## Workflow

### One company

1. Call `screen_sanctions` with the name and the two-letter country code, if known. The country doesn't filter; it ranks same-country listings first. If the user is already looking at a company card, its `sanctions` block has this result, with its parents screened too.
2. **No match:** say which lists were checked, the date each was downloaded (`lists[].fetched_at`), and that nothing matched the name.
3. **Matches:** list each one:
   - the level (exact, strong or possible)
   - the list
   - the listed name, plus `matched_name` if it's an alias
   - the programme, the listing date, the countries and the link
   Then give the review steps below.

### A list of customers

1. Read the user's file with code. Take the customer name column, and the country column if there is one; ask which column if it isn't obvious. Remove exact duplicates, and keep the customer ID if the file has one.
2. Screen in batches of up to 50 names: `screen_sanctions` with `names: [{name, country}]`, or `POST /v1/sanctions`.
3. Write the results to a CSV with one row per customer:
   - customer, ID and country
   - result (`no_match` or `possible_match`)
   - the best match's level, list, listed name, programme, listing date and link
   - the number of matches
   Share the CSV.
4. Reply with the counts screened, matched and not matched, the lists and their dates, and a short table of the possible matches only (exact first). Don't paste every no-match.

## Reviewing a possible match

Tell the user to compare the listing with what they know about the customer before acting, and give these steps:
1. **Open the listing** (the `url`, or the list's official search) and read the full entry: addresses, registration numbers, other names and remarks.
2. **Compare identity:** country, address, registration number, and the date of incorporation against the listing date. Different numbers or addresses usually mean a different company with a similar name.
3. **Check ownership:** who owns the customer, from the company card, the register or the customer. Listed owners can matter even when the company isn't listed.
4. **If it still looks like the same entity**, stop and escalate to whoever handles sanctions compliance or legal in their organisation before shipping, paying or extending credit. Don't contact the customer about the suspected match.
5. **Record the decision:** what was compared, the outcome and the date. Screening results and list dates belong in the customer file.

Weak `possible` matches on common words, such as "Global Trading", are usually noise. Say so, but still list them.

## Report wording

End every report with: "Screened with Company Lookup against the OFAC, EU, UN and UK lists as downloaded on <dates>. Companies only; ownership not screened. For information only; not a compliance system or legal advice."
