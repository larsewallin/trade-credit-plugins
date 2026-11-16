---
name: new-customer-check
description: Checks a new B2B customer or supplier against official company registers, GLEIF, EU VAT, domain records and sanctions lists using Company Lookup, compares what the customer told you with the register, and drafts a short new-customer memo with verification levels, flags, gaps and documents to request. Use when the user asks to check, verify, vet or onboard a new customer or supplier, run KYB, review a credit application, asks "is this company real", or wants a new account memo before extending credit.
---

# New customer check

Check that a new customer is who it says it is, using official records, and write it up as a short memo for the credit file. Facts come from **Company Lookup** (registers, GLEIF, VIES, Wikidata, RDAP and sanctions lists). See `references/company-lookup-access.md` for the connector, the HTTP API, and what to do when neither is available.

## Rules

- **Only state what a source returned.** Every fact in the memo carries its source and the date checked, taken from the card. Never fill gaps from memory or a general web search and present them as checked.
- **Flags and sanctions matches are prompts to review, never verdicts.** Don't call a company fraudulent, sanctioned or a bad risk, and don't tell the user to decline. Say what to check and why.
- **No credit limit or score.** This skill checks identity and good standing. A limit needs financials and the user's own policy.
- **Companies only.** Don't look up private individuals (directors, owners) beyond what the card itself shows.

## Workflow

### 1. Collect what the customer gave you

Ask for, or read from the credit application the user attached:
- **Required:** legal name and country.
- **Best:** the registration number, and the VAT number in the EU.
- **Also useful:** the website, the registered address, and who signed or sent the application, with their email domain.

Work with what is there; don't hold the check up for optional details.

### 2. Find the company

Call `search_companies` with the registration number if you have one, otherwise the name, plus the two-letter country code.
- Several plausible matches: show the top three (name, number, status, city) and ask which one. Don't pick one yourself when names differ.
- No match: try the name without its legal form, a former name, or GLEIF only (no country). Then say it wasn't found, which is itself a finding for the memo.

### 3. Get the card

Call `get_company_card` with the id, adding the customer's website if you have one. The card includes:
- identity, status and filings
- officers and owners where the register publishes them
- the group from GLEIF
- the VAT check
- website domain age
- a sanctions screening of the company and its parents
- flags, sources and gaps

If the user named a parent or guarantor, check that company too.

### 4. Compare what they said with the register

Compare each detail the customer gave with the card:
- **Name:** exact, or only the legal form differs. A trading name doesn't count; note it.
- **Registration and VAT numbers.**
- **Address:** registered address or headquarters.
- **Website domain:** does it match the company's website on the card? How old is it?
- **Email domain:** does it match the website?

Mark each detail **matches**, **differs** or **not checked**. A free webmail address, a domain registered weeks ago, or a different bank-account country are classic payment-fraud signs; list them as checks, not conclusions.

### 5. Verification levels

Grade the customer on the levels below. Stop at the first level it doesn't reach, and say why.

| Level | Name | Reached when |
|---|---|---|
| 1 | Exists | Found on an official register (or GLEIF) and active |
| 2 | Matches | The name, number and address the customer gave match the register |
| 3 | Corroborated | Independent sources agree: valid VAT where checked, an LEI if it has one, a website domain over 12 months old that plausibly belongs to it, a parent that checks out |
| 4 | Clean | No Stop flags: not dissolved, insolvent or in liquidation; no recent name or address change; no possible sanctions match |
| 5 | Payment-safe | Not checked here. The bank account must be confirmed by the user's bank (Confirmation of Payee in the UK, Verification of Payee in the EU) and by calling a number from the register, never one from the request |

### 6. Write the memo

Keep it to about one page. Write it in the chat; if the user wants a document, use the user's normal document format.

1. **Header:** legal name, country, register and number, the date checked, and the verification level reached.
2. **Summary:** 2–3 sentences: who they are, whether the details match, and the main thing to check.
3. **Identity and status:** the key card facts with sources: status, incorporated date and age, legal form, registered address, and filings (accounts up to date or overdue).
4. **Ownership and group:** parents from GLEIF, and owners or officers where published. Suggest a parent guarantee where the card's next step says so.
5. **What they told us vs the register:** the comparison from step 4.
6. **Sanctions:** the lists and their dates from the card's `sanctions` block. For any match:
   - name the list, the listed name, the programme and the link
   - state plainly that a name match must be confirmed on address, registration number and ownership before anyone treats it as a hit
   - point to the Sanctions Screening skill or the list's own search
7. **Flags and gaps:** every flag with its detail, and the gaps that matter (for example, "officers are not published in this country").
8. **Before extending credit:** what to request, chosen by the gaps. For example:
   - latest filed accounts, or management accounts
   - trade references
   - a bank reference
   - a parent guarantee
   - credit insurance cover
   - confirmation of bank details by Confirmation or Verification of Payee

End with the line: "Checked with Company Lookup on <date>. For information only; not a credit rating or advice."

## Several customers

For a list of new accounts, run steps 2–3 for each one. Then give a short table (name, country, found, status, verdict, flags, sanctions) and full memos only for those that need attention, unless the user asks for all.
