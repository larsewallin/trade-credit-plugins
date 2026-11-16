"""
Reads an open-items (accounts receivable) export (CSV, TSV, semicolon CSV, or XLSX)
and turns it into clean open invoices:

  customer_key, customer_name, customer_id, invoice_number, invoice_date,
  due_date, amount_open, currency, credit_limit, days_past_due

The value helpers (dates, amounts, delimiters) are the same as in the Payment Risk
reader, with the same rules:
  - Column names are matched exactly against alias lists, never "contains".
  - A generic "Date" column is never auto-mapped (too ambiguous).
  - Day/month order is detected across all date columns. If the file never shows
    a day above 12, the order is ambiguous and reading stops instead of guessing.
  - Every row that is skipped is reported with its row number and reason.

Standard library only (openpyxl is used for .xlsx when available).
"""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from datetime import date, datetime, timedelta

# ── Column aliases (normalised: lowercase, punctuation -> space) ─────────────
# Order inside each list = priority when several headers match.

ALIASES = {
    "customer_name": [
        "customer name", "customer", "client name", "client", "account name", "debtor name",
        "debtor", "buyer name", "buyer", "company name", "sold to name", "bill to name",
        "payer name", "payer", "cust name", "partner name",
    ],
    "customer_id": [
        "customer id", "customer number", "customer no", "customer code", "customer num",
        "account number", "account no", "account id", "debtor number", "debtor no", "debtor id",
        "cust id", "cust no", "client id", "client number", "buyer id", "payer id", "bp number",
    ],
    "invoice_number": [
        "invoice number", "invoice no", "invoice num", "invoice id", "invoice", "inv no",
        "inv number", "document number", "document no", "doc no", "doc number", "invoice ref",
        "invoice reference", "reference",
    ],
    "invoice_date": [
        "invoice date", "inv date", "document date", "doc date", "issue date", "billing date",
        "date of invoice", "invoiced on", "posting date",
    ],
    "due_date": [
        "due date", "net due date", "invoice due date", "payment due date", "date due",
        "due on", "maturity date", "due",
    ],
    "amount_open": [
        "open amount", "amount open", "outstanding amount", "amount outstanding", "outstanding",
        "outstanding balance", "balance outstanding", "open balance", "balance due", "amount due",
        "amount remaining", "remaining amount", "remaining balance", "residual amount", "unpaid amount",
        "amount unpaid", "open item amount", "balance",
    ],
    "amount_invoice": [
        "invoice amount", "original amount", "original invoice amount", "document amount", "gross amount",
        "total amount", "amount", "total", "value",
    ],
    "currency": [
        "currency", "currency code", "curr", "ccy", "cur", "document currency", "invoice currency",
    ],
    "credit_limit": [
        "credit limit", "credit line", "approved limit", "approved credit limit", "credit limit amount",
        "limit",
    ],
    "days_past_due": [
        "days past due", "days overdue", "past due days", "overdue days", "days late", "dpd",
    ],
    "status": [
        "status", "invoice status", "document status", "item status",
    ],
}

FIELDS = list(ALIASES)
CLOSED_STATUS = {"paid", "closed", "cleared", "settled", "cancelled", "canceled", "void", "voided",
                 "reversed", "written off", "write off", "fully paid"}
# Headers that mean the file is an aging summary (one row per customer, amounts already in buckets)
SUMMARY_HEADERS = {"current", "1 30", "31 60", "61 90", "90", "91 120", "over 90", "90 plus", "120",
                   "0 30", "30 60", "60 90", "1 30 days", "31 60 days", "61 90 days", "over 90 days"}


def norm_header(h) -> str:
    s = str(h if h is not None else "").replace("﻿", "").strip().lower()
    s = s.replace("#", " number ").replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


class ReadError(Exception):
    """Reading stopped; the message is written for the person running the review."""


# ── Loading ──────────────────────────────────────────────────────────────────

def _decode(raw: bytes) -> str:
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")) or raw[:200].count(b"\x00") > 20:
        return raw.decode("utf-16")  # Excel "Unicode Text" exports
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _header_score(rows: list[list]) -> tuple:
    """(alias hits in the best header row, number of columns there) for choosing a delimiter."""
    known = {a for lst in ALIASES.values() for a in lst}
    best = (0, 0)
    for row in rows[:20]:
        hits = sum(1 for c in row if norm_header(c) in known)
        best = max(best, (hits, len(row)))
    return best


def load_rows(path: str, sheet: str | None = None) -> list[list]:
    low = path.lower()
    if low.endswith((".xlsx", ".xlsm")):
        try:
            import openpyxl  # type: ignore
        except ImportError as e:  # pragma: no cover
            raise ReadError("This is an Excel file and openpyxl is not installed. "
                            "Install it (pip install openpyxl) or save the sheet as CSV.") from e
        try:
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        except Exception as e:  # noqa: BLE001
            raise ReadError(f"Couldn't open the Excel file ({e}). Try saving it again as .xlsx or CSV.") from e
        if sheet and sheet not in wb.sheetnames:
            raise ReadError(f"There is no sheet called '{sheet}'. Sheets in the file: {wb.sheetnames}")
        ws = wb[sheet] if sheet else wb.worksheets[0]
        return [list(r) for r in ws.iter_rows(values_only=True)]
    if low.endswith(".xls"):
        raise ReadError("Old .xls files aren't supported. Save the sheet as .xlsx or CSV.")
    with open(path, "rb") as f:
        text = _decode(f.read()).replace("\x00", "")
    # Pick the delimiter that produces a recognisable header (title rows above it are common)
    best_rows, best_score = None, (-1, -1)
    for delim in [",", ";", "\t", "|"]:
        rows = list(csv.reader(io.StringIO(text), delimiter=delim))
        score = _header_score(rows)
        if score > best_score:
            best_rows, best_score = rows, score
    return best_rows or []


def find_header(rows: list[list]) -> int:
    """First row (within the first 20) that matches at least two known columns."""
    known = {a for lst in ALIASES.values() for a in lst}
    best, best_hits = 0, -1
    for i, row in enumerate(rows[:20]):
        hits = sum(1 for c in row if norm_header(c) in known)
        if hits >= 2:
            return i
        if hits > best_hits:
            best, best_hits = i, hits
    return best


def auto_map(headers: list) -> dict:
    normed = [norm_header(h) for h in headers]
    used: set[int] = set()
    mapping: dict[str, int] = {}
    for field in FIELDS:
        for alias in ALIASES[field]:
            idx = next((i for i, h in enumerate(normed) if h == alias and i not in used), None)
            if idx is not None:
                mapping[field] = idx
                used.add(idx)
                break
    return mapping


# ── Values ───────────────────────────────────────────────────────────────────

MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
EXCEL_EPOCH = date(1899, 12, 30)
_TIME = r"(?:[ T]\d{1,2}:\d{2}.*)?"

_NUMERIC_DMY = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})(?:[ T].*)?$")
_ISO = re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[ T].*)?$")
# 15-Jan-2025, 15 Jan 25, 15th January 2025 (a separator before the year is required)
_TEXT_MONTH_1 = re.compile(r"^(\d{1,2})(?:st|nd|rd|th)?[ \-/.]?([A-Za-z]{3,9})\.?[ \-/.,]+(\d{4}|\d{2})" + _TIME + "$")
# Jan 15, 2025 / January 15 2025 (a day is required: "Jan-2025" is rejected)
_TEXT_MONTH_2 = re.compile(r"^([A-Za-z]{3,9})\.?[ \-/.]?(\d{1,2})(?:st|nd|rd|th)?(?:,\s*|[ \-/.]+)(\d{4}|\d{2})" + _TIME + "$")


def _year(y: str) -> int:
    v = int(y)
    if v >= 100:
        return v
    return 2000 + v if v < 70 else 1900 + v


def date_order_votes(values) -> Counter:
    """Count evidence for day-first vs month-first in numeric dates like 03/04/2025."""
    votes = Counter()
    for v in values:
        if v is None or isinstance(v, (date, datetime)):
            continue
        m = _NUMERIC_DMY.match(str(v).strip())
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        if a > 12 and b <= 12:
            votes["dmy"] += 1
        elif b > 12 and a <= 12:
            votes["mdy"] += 1
        else:
            votes["ambiguous"] += 1
    return votes


def parse_date(v, order: str | None) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if 20000 < v < 80000:  # Excel serial date
            return EXCEL_EPOCH + timedelta(days=int(v))
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        m = _ISO.match(s)
        if m:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = _NUMERIC_DMY.match(s)
        if m:
            a, b, y = int(m.group(1)), int(m.group(2)), _year(m.group(3))
            if order == "dmy":
                return date(y, b, a)
            if order == "mdy":
                return date(y, a, b)
            return None
        m = _TEXT_MONTH_1.match(s)
        if m and m.group(2)[:3].lower() in MONTHS:
            return date(_year(m.group(3)), MONTHS[m.group(2)[:3].lower()], int(m.group(1)))
        m = _TEXT_MONTH_2.match(s)
        if m and m.group(1)[:3].lower() in MONTHS:
            return date(_year(m.group(3)), MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
        if re.fullmatch(r"\d{5}(\.\d+)?", s):
            return parse_date(float(s), order)
    except ValueError:
        return None  # e.g. 31/02/2025
    return None


_SCI = re.compile(r"^\d+(\.\d+)?[eE][+-]?\d+$")


def _clean_amount_text(v) -> tuple:
    """-> (core digits/separators text, is_negative)"""
    s = str(v).strip().replace("−", "-").replace("–", "-").replace("\xa0", " ").replace(" ", " ")
    neg = False
    up = s.upper()
    if re.search(r"(^|[^A-Z])CR\.?$", up) or up.startswith("CR "):
        neg = True
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    s = s.strip()
    if s.endswith("-"):
        neg, s = True, s[:-1]
    core = re.sub(r"[^0-9.,eE+\-]", "", s)
    if not _SCI.match(core.lstrip("+-")):
        core = re.sub(r"[eE+]", "", core)
    if core.startswith("-"):
        neg, core = True, core.lstrip("-")
    return core, neg


def amount_decimal_votes(values) -> Counter:
    """Evidence for '.' or ',' as the decimal separator in an amount column."""
    votes = Counter()
    for v in values:
        if v is None or isinstance(v, (int, float)):
            continue
        core, _ = _clean_amount_text(v)
        if "." in core and "," in core:
            votes["." if core.rfind(".") > core.rfind(",") else ","] += 1
        elif re.fullmatch(r"\d*,\d{1,2}", core):
            votes[","] += 1
        elif re.fullmatch(r"\d*\.\d{1,2}", core):
            votes["."] += 1
        elif re.fullmatch(r"\d{1,3}(,\d{3})+", core):
            votes["."] += 1          # comma used as thousands
        elif re.fullmatch(r"\d{1,3}(\.\d{3}){2,}", core):
            votes[","] += 1          # 1.234.567
        elif re.fullmatch(r"\d{1,3}\.\d{3}", core):
            votes["ambiguous"] += 1  # 1.250 could be 1250 or 1.25
    return votes


def parse_amount(v, decimal: str | None = None) -> float | None:
    """decimal: '.' or ',' (decided per column); None = infer from this value alone."""
    if v is None:
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if not str(v).strip():
        return None
    core, neg = _clean_amount_text(v)
    if not core:
        return None
    if _SCI.match(core):
        val = float(core)
        return -val if neg else val
    if decimal is None:
        if "." in core and "," in core:
            decimal = "." if core.rfind(".") > core.rfind(",") else ","
        elif "," in core:
            decimal = "." if re.fullmatch(r"\d{1,3}(,\d{3})+", core) else ","
        elif re.fullmatch(r"\d{1,3}(\.\d{3}){2,}", core):
            decimal = ","
        else:
            decimal = "."
    core = core.replace(",", "") if decimal == "." else core.replace(".", "").replace(",", ".")
    try:
        val = float(core)
    except ValueError:
        return None
    return -val if neg else val


def parse_int(v) -> int | None:
    a = parse_amount(v)
    return None if a is None else int(round(a))


# ── Main ─────────────────────────────────────────────────────────────────────

def _key(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def read_open_items(path: str, overrides: dict | None = None, date_order: str | None = None,
                    sheet: str | None = None) -> dict:
    """
    Returns {"items", "mapping", "headers", "date_order", "date_order_basis", "amount_basis",
             "warnings", "skipped", "row_count", "credit_limits"}.
    Raises ReadError when the file can't be analysed safely.
    """
    rows = load_rows(path, sheet)

    def blank(r):
        return not any(c not in (None, "") and str(c).strip() for c in r)

    if sum(1 for r in rows if not blank(r)) < 2:
        raise ReadError("The file has no data rows.")

    h = find_header(rows)
    headers = [str(c).strip() if c is not None else "" for c in rows[h]]
    data = rows[h + 1:]  # blank lines kept so row numbers match the file; skipped below
    mapping = auto_map(headers)

    for field, header in (overrides or {}).items():
        if field not in FIELDS:
            raise ReadError(f"Unknown field '{field}'. Use one of: {', '.join(FIELDS)}.")
        if header in ("", None, "none"):
            mapping.pop(field, None)
            continue
        idx = next((i for i, hh in enumerate(headers) if hh == header), None)
        if idx is None:
            idx = next((i for i, hh in enumerate(headers) if norm_header(hh) == norm_header(header)), None)
        if idx is None:
            raise ReadError(f"Column '{header}' was not found. Columns in the file: {headers}")
        for f, i in list(mapping.items()):
            if i == idx and f != field:
                mapping.pop(f)
        mapping[field] = idx

    normed = {norm_header(x) for x in headers}
    if "due_date" not in mapping and "days_past_due" not in mapping and len(normed & SUMMARY_HEADERS) >= 2:
        raise ReadError(
            "This looks like an aging summary (one row per customer, amounts already split into "
            "buckets such as Current / 1-30 / 31-60). Export the open items instead: one row per unpaid "
            "invoice, with its due date and open amount. Most systems call it 'open items', "
            "'AR aging detail' or 'customer open invoices'.")

    named = {f: headers[i] for f, i in mapping.items()}
    missing = []
    if "customer_name" not in mapping and "customer_id" not in mapping:
        missing.append("customer (name or ID)")
    if "due_date" not in mapping and "days_past_due" not in mapping:
        missing.append("due date (or a days-past-due column)")
    if "amount_open" not in mapping and "amount_invoice" not in mapping:
        missing.append("open amount")
    if missing:
        raise ReadError(
            "Couldn't find these columns: " + "; ".join(missing) + ". "
            f"Columns in the file: {headers}. Map them with --map field=\"Column name\" "
            f"(fields: {', '.join(FIELDS)}).")
    amount_field = "amount_open" if "amount_open" in mapping else "amount_invoice"

    def cell(row, field):
        i = mapping.get(field)
        return row[i] if i is not None and i < len(row) else None

    # Day/month order across all date columns
    date_fields = [f for f in ("due_date", "invoice_date") if f in mapping]
    votes = Counter()
    for f in date_fields:
        votes += date_order_votes(cell(r, f) for r in data)
    basis = "not needed (no numeric day/month dates)"
    early_warnings = []
    if date_order:
        basis = "set by user"
        contra = votes["mdy" if date_order == "dmy" else "dmy"]
        if contra:
            early_warnings.append(
                f"{contra} dates can't be {'day-first' if date_order == 'dmy' else 'month-first'} "
                "(their middle or first number is above 12); those rows are skipped as unreadable. "
                "Check the --date-order setting.")
    elif votes["dmy"] and votes["mdy"]:
        raise ReadError(
            f"The dates mix day-first and month-first formats ({votes['dmy']} look day-first, "
            f"{votes['mdy']} look month-first). Clean the file or tell me which format it uses "
            "(--date-order dmy or mdy).")
    elif votes["dmy"]:
        date_order, basis = "dmy", f"detected: {votes['dmy']} dates have a day above 12 in first position"
    elif votes["mdy"]:
        date_order, basis = "mdy", f"detected: {votes['mdy']} dates have a day above 12 in second position"
    elif votes["ambiguous"]:
        raise ReadError(
            "The dates could be day/month or month/day (e.g. 03/04/2025) and the file never shows "
            "a day above 12, so the order can't be detected. Ask which format the export uses, "
            "then re-run with --date-order mdy (US, 04/03 = April 3) or --date-order dmy "
            "(most other countries, 04/03 = 4 March).")

    # Decimal separator, decided once per amount column
    def decimal_for(field):
        dv = amount_decimal_votes(cell(r, field) for r in data)
        if dv["."] and dv[","]:
            d = "." if dv["."] >= dv[","] else ","
            early_warnings.append(
                f"{named[field]}: amounts use both '.' and ',' as decimal marks ({dv['.']} vs {dv[',']} rows); "
                f"read with '{d}'. Check the column.")
            return d
        if dv["."] or dv[","]:
            return "." if dv["."] else ","
        if dv["ambiguous"]:
            early_warnings.append(
                f"{named[field]}: amounts like 1.250 could mean 1,250 or 1.25; read as decimals (1.25). "
                "If the export uses dots for thousands, say so and re-run.")
        return "."
    dec_amount = decimal_for(amount_field)
    dec_limit = decimal_for("credit_limit") if "credit_limit" in mapping else None

    # Customer IDs: rows missing an ID take the ID used elsewhere for the same name
    ids_by_name: dict[str, set] = {}
    for r in data:
        if blank(r):
            continue
        nm, ci = cell(r, "customer_name"), cell(r, "customer_id")
        if nm not in (None, "") and ci not in (None, ""):
            ci = str(ci).strip()
            ci = ci[:-2] if ci.endswith(".0") and ci[:-2].isdigit() else ci
            ids_by_name.setdefault(_key(str(nm)), set()).add(ci)

    items, skipped, warnings = [], [], list(early_warnings)
    names_by_key: dict[str, Counter] = {}
    limits_by_key: dict[str, set] = {}
    filled_ids = 0
    for n, row in enumerate(data, start=h + 2):
        if blank(row):
            continue
        name = cell(row, "customer_name")
        cid = cell(row, "customer_id")
        name = str(name).strip() if name not in (None, "") else ""
        cid = str(cid).strip() if cid not in (None, "") else ""
        if cid.endswith(".0") and cid[:-2].isdigit():
            cid = cid[:-2]
        if not name and not cid:
            # Subtotal and grand-total lines in exported reports have no customer
            skipped.append({"row": n, "reason": "no customer (subtotal or total line?)"})
            continue
        if re.match(r"^(grand )?total\b", name.lower()) or re.match(r"^(grand )?total\b", cid.lower()):
            skipped.append({"row": n, "reason": "total line"})
            continue
        if not cid and name:
            known = ids_by_name.get(_key(name), set())
            if len(known) == 1:
                cid = next(iter(known))
                filled_ids += 1
        key = f"id:{cid.lower()}" if cid else "name:" + _key(name)

        st = cell(row, "status")
        if st not in (None, "") and _key(str(st)) in CLOSED_STATUS:
            skipped.append({"row": n, "reason": f"status '{str(st).strip()}' (not open)"})
            continue

        amount = parse_amount(cell(row, amount_field), dec_amount)
        if amount is None:
            raw = cell(row, amount_field)
            skipped.append({"row": n, "reason": "no amount" if raw in (None, "") else f"unreadable amount '{raw}'"})
            continue
        if amount == 0:
            skipped.append({"row": n, "reason": "zero open amount (paid?)"})
            continue

        due = parse_date(cell(row, "due_date"), date_order) if "due_date" in mapping else None
        inv = parse_date(cell(row, "invoice_date"), date_order) if "invoice_date" in mapping else None
        dpd = None
        if due is None:
            dpd = parse_int(cell(row, "days_past_due")) if "days_past_due" in mapping else None
            if dpd is None:
                raw = cell(row, "due_date")
                if "due_date" in mapping and raw not in (None, ""):
                    skipped.append({"row": n, "reason": f"unreadable due date '{raw}'"})
                    continue
                if amount > 0:
                    skipped.append({"row": n, "reason": "no due date"})
                    continue
                # A credit without a due date (unapplied cash) is still a credit; age it as current

        cur = cell(row, "currency")
        cur = str(cur).strip().upper() if cur not in (None, "") else None

        lim = parse_amount(cell(row, "credit_limit"), dec_limit) if "credit_limit" in mapping else None
        if lim is not None and lim > 0:
            limits_by_key.setdefault(key, set()).add(lim)

        inv_no = cell(row, "invoice_number")
        items.append({
            "row": n,
            "customer_key": key,
            "customer_id": cid or None,
            "invoice_number": str(inv_no).strip() if inv_no not in (None, "") else None,
            "invoice_date": inv.isoformat() if inv else None,
            "due_date": due.isoformat() if due else None,
            "days_past_due_given": dpd,
            "amount_open": amount,
            "currency": cur,
        })
        names_by_key.setdefault(key, Counter())[name or cid] += 1

    for it in items:
        it["customer_name"] = names_by_key[it["customer_key"]].most_common(1)[0][0]

    credit_limits = {}
    for k, vals in limits_by_key.items():
        if len(vals) > 1:
            warnings.append(f"{names_by_key[k].most_common(1)[0][0]}: several credit limits in the file "
                            f"({', '.join(f'{v:,.0f}' for v in sorted(vals))}); the highest is used.")
        credit_limits[k] = max(vals)

    if amount_field == "amount_invoice":
        warnings.append(f"No open-amount column found; '{named['amount_invoice']}' is treated as the amount "
                        "still owed. Partly paid invoices will be overstated. Map the open amount with "
                        "--map amount_open=\"Column\" if the file has one.")
    curs = {it["currency"] for it in items}
    if len(curs - {None}) > 1:
        warnings.append(f"The file has {len(curs - {None})} currencies ({', '.join(sorted(curs - {None}))}); "
                        "totals are kept per currency and never converted.")
        if None in curs:
            warnings.append("Some rows have no currency; they are grouped as 'unknown'.")

    dup = Counter((it["customer_key"], it["invoice_number"], it["amount_open"])
                  for it in items if it["invoice_number"])
    n_dup = sum(c - 1 for c in dup.values() if c > 1)
    if n_dup:
        warnings.append(f"{n_dup} rows look like duplicates (same customer, invoice and amount). Kept as-is.")
    if filled_ids:
        warnings.append(f"{filled_ids} rows had no customer ID; matched to the ID used for the same customer name.")

    if not items:
        raise ReadError("No usable open items were found. "
                        f"Skipped reasons: {Counter(s['reason'] for s in skipped).most_common(5)}")

    return {
        "items": items,
        "mapping": named,
        "headers": headers,
        "header_row": h + 1,
        "date_order": date_order,
        "date_order_basis": basis,
        "amount_basis": amount_field,
        "warnings": warnings,
        "skipped": skipped,
        "row_count": sum(1 for r in data if not blank(r)),
        "credit_limits": credit_limits,
    }
