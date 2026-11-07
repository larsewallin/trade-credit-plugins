"""
Reads a payment history export (CSV, TSV, semicolon CSV, or XLSX) and turns
it into clean payment records:

  customer_key, customer_name, customer_id, invoice_number,
  invoice_date, due_date, payment_date, amount,
  days_early_late (payment - due, in days), days_to_pay (payment - invoice)

Design rules (learned the hard way in a production AR parser):
  - Column names are matched exactly against alias lists, never "contains".
  - A generic "Date" column is never auto-mapped (too ambiguous).
  - "Payment date" maps to payment_date only; it is never a due date.
  - Day/month order is detected across all date columns. If the file never
    shows a day above 12, the order is ambiguous and reading stops with a
    clear message instead of guessing.
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
        "invoice reference",
    ],
    "invoice_date": [
        "invoice date", "inv date", "document date", "doc date", "issue date", "billing date",
        "date of invoice", "invoiced on",
    ],
    "due_date": [
        "due date", "net due date", "invoice due date", "payment due date", "date due",
        "due on", "maturity date", "due",
    ],
    "payment_date": [
        "payment date", "paid date", "date paid", "paid on", "receipt date", "date received",
        "received date", "clearing date", "cleared date", "settlement date", "value date",
        "cash date", "collection date", "payment received date", "pay date",
    ],
    "amount": [
        "amount paid", "paid amount", "payment amount", "amount received", "receipt amount",
        "applied amount", "amount applied", "cash applied", "invoice amount", "amount",
        "gross amount", "total amount", "total", "value",
    ],
    "days_late": [
        "days late", "days early late", "days early or late", "days past due",
        "days past due at payment", "days overdue at payment", "dpd",
    ],
}

REQUIRED_ALWAYS = ["payment_date"]
FIELDS = list(ALIASES)


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

def read_payments(path: str, overrides: dict | None = None, date_order: str | None = None,
                  sheet: str | None = None) -> dict:
    """
    Returns {"payments", "mapping", "headers", "date_order", "date_order_basis",
             "warnings", "skipped", "row_count"}.
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

    # Manual overrides: field=Header name
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

    named = {f: headers[i] for f, i in mapping.items()}
    missing = []
    if "customer_name" not in mapping and "customer_id" not in mapping:
        missing.append("customer (name or ID)")
    if "payment_date" not in mapping:
        missing.append("payment date")
    if "due_date" not in mapping and "days_late" not in mapping:
        missing.append("due date (or a days-late column)")
    if missing:
        raise ReadError(
            "Couldn't find these columns: " + "; ".join(missing) + ". "
            f"Columns in the file: {headers}. Map them with --map field=\"Column name\" "
            f"(fields: {', '.join(FIELDS)}).")

    def cell(row, field):
        i = mapping.get(field)
        return row[i] if i is not None and i < len(row) else None

    # Day/month order across all date columns
    date_fields = [f for f in ("payment_date", "due_date", "invoice_date") if f in mapping]
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

    # Decimal separator for the amount column, decided once for the whole column
    decimal, dec_votes = None, Counter()
    if "amount" in mapping:
        dec_votes = amount_decimal_votes(cell(r, "amount") for r in data)
        if dec_votes["."] and dec_votes[","]:
            decimal = "." if dec_votes["."] >= dec_votes[","] else ","
            early_warnings.append(
                f"Amounts use both '.' and ',' as decimal marks ({dec_votes['.']} vs {dec_votes[',']} rows); "
                f"read with '{decimal}'. Check the amount column.")
        elif dec_votes["."] or dec_votes[","]:
            decimal = "." if dec_votes["."] else ","
        elif dec_votes["ambiguous"]:
            decimal = "."
            early_warnings.append(
                "Amounts like 1.250 could mean 1,250 or 1.25; read as decimals (1.25). If the export "
                "uses dots for thousands, say so and re-run.")

    # Customer IDs: rows missing an ID take the ID used elsewhere for the same name
    ids_by_name: dict[str, set] = {}
    for r in data:
        if blank(r):
            continue
        nm, ci = cell(r, "customer_name"), cell(r, "customer_id")
        if nm not in (None, "") and ci not in (None, ""):
            ci = str(ci).strip()
            ci = ci[:-2] if ci.endswith(".0") and ci[:-2].isdigit() else ci
            ids_by_name.setdefault(re.sub(r"\s+", " ", str(nm).strip().lower()), set()).add(ci)

    payments, skipped, warnings = [], [], list(early_warnings)
    names_by_key: dict[str, Counter] = {}
    no_amount = 0
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
            skipped.append({"row": n, "reason": "no customer"})
            continue
        if not cid and name:
            known_ids = ids_by_name.get(re.sub(r"\s+", " ", name.lower()), set())
            if len(known_ids) == 1:
                cid = next(iter(known_ids))
                filled_ids += 1
        key = f"id:{cid.lower()}" if cid else "name:" + re.sub(r"\s+", " ", name.lower())

        pay = parse_date(cell(row, "payment_date"), date_order)
        if pay is None:
            raw = cell(row, "payment_date")
            reason = "no payment date (unpaid or open item?)" if raw in (None, "") else f"unreadable payment date '{raw}'"
            skipped.append({"row": n, "reason": reason})
            continue

        due = parse_date(cell(row, "due_date"), date_order) if "due_date" in mapping else None
        inv = parse_date(cell(row, "invoice_date"), date_order) if "invoice_date" in mapping else None
        if due is not None:
            del_ = (pay - due).days
        elif "days_late" in mapping and parse_int(cell(row, "days_late")) is not None:
            del_ = parse_int(cell(row, "days_late"))
        else:
            raw = cell(row, "due_date")
            skipped.append({"row": n, "reason": "no due date" if raw in (None, "") else f"unreadable due date '{raw}'"})
            continue

        amount = None
        if "amount" in mapping:
            amount = parse_amount(cell(row, "amount"), decimal)
            if amount is not None and amount <= 0:
                skipped.append({"row": n, "reason": f"amount {amount:g} (credit note, reversal or zero)"})
                continue
            if amount is None:
                no_amount += 1

        if inv is not None and due is not None and due < inv:
            warnings.append(f"Row {n}: due date is before invoice date.")

        inv_no = cell(row, "invoice_number")
        payments.append({
            "row": n,
            "customer_key": key,
            "customer_id": cid or None,
            "invoice_number": str(inv_no).strip() if inv_no not in (None, "") else None,
            "invoice_date": inv.isoformat() if inv else None,
            "due_date": due.isoformat() if due else None,
            "payment_date": pay.isoformat(),
            "amount": amount,
            "days_early_late": del_,
            "days_to_pay": (pay - inv).days if inv else None,
        })
        names_by_key.setdefault(key, Counter())[name or cid] += 1

    for p in payments:
        p["customer_name"] = names_by_key[p["customer_key"]].most_common(1)[0][0]

    if "amount" not in mapping:
        warnings.append("No amount column found: every payment counts equally (not amount-weighted).")
    elif no_amount:
        warnings.append(f"{no_amount} payments have no readable amount; they count with weight 1.")

    dup = Counter((p["customer_key"], p["invoice_number"], p["payment_date"], p["amount"])
                  for p in payments if p["invoice_number"])
    n_dup = sum(c - 1 for c in dup.values() if c > 1)
    if n_dup:
        warnings.append(f"{n_dup} rows look like duplicates (same customer, invoice, date and amount). Kept as-is.")

    if filled_ids:
        warnings.append(f"{filled_ids} rows had no customer ID; matched to the ID used for the same customer name.")
    if payments:
        dates = sorted(p["payment_date"] for p in payments)
        if int(dates[-1][:4]) - int(dates[0][:4]) > 15:
            warnings.append(f"Payment dates span {dates[0]} to {dates[-1]}; check for mis-read dates "
                            "(e.g. two-digit years).")

    if not payments:
        raise ReadError("No usable payment rows were found. "
                        f"Skipped reasons: {Counter(s['reason'] for s in skipped).most_common(5)}")

    return {
        "payments": payments,
        "mapping": named,
        "headers": headers,
        "header_row": h + 1,
        "date_order": date_order,
        "date_order_basis": basis,
        "warnings": warnings,
        "skipped": skipped,
        "row_count": sum(1 for r in data if not blank(r)),
    }
