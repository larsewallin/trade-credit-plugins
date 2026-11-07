"""
Tests for the payment-export reader and the end-to-end script on messy files.

Run:  python3 tests/test_reader.py
"""

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(HERE, "..", "plugins", "payment-risk", "skills", "payment-risk-review", "scripts")
sys.path.insert(0, SCRIPTS)

from reader import ReadError, parse_amount, parse_date, read_payments  # noqa: E402

TMP = tempfile.mkdtemp()


def write(name, text):
    p = os.path.join(TMP, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


def test_amounts():
    assert parse_amount("$1,234.56") == 1234.56
    assert parse_amount("1.234,56") == 1234.56
    assert parse_amount("1 234,56 EUR") == 1234.56
    assert parse_amount("(1,000.00)") == -1000.0
    assert parse_amount("-$45.10") == -45.1
    assert parse_amount("250-") == -250.0
    assert parse_amount("12,5") == 12.5
    assert parse_amount("1,234") == 1234.0
    assert parse_amount("") is None and parse_amount("n/a") is None


def test_dates():
    assert str(parse_date("2026-03-04", None)) == "2026-03-04"
    assert str(parse_date("04/03/2026", "dmy")) == "2026-03-04"
    assert str(parse_date("04/03/2026", "mdy")) == "2026-04-03"
    assert parse_date("04/03/2026", None) is None           # never guessed
    assert str(parse_date("15-Jan-2026", None)) == "2026-01-15"
    assert str(parse_date("Jan 15, 2026", None)) == "2026-01-15"
    assert str(parse_date("15.01.26", "dmy")) == "2026-01-15"
    assert str(parse_date(46037, None)) == "2026-01-15"      # Excel serial
    assert parse_date("31/02/2026", "dmy") is None           # impossible date


def test_payment_date_is_never_the_due_date():
    # A classic AR-parser bug: "Payment Date" listed before "Due Date"
    p = write("order.csv", "Customer,Payment Date,Due Date,Amount\nAcme,2026-02-10,2026-02-01,100\n")
    r = read_payments(p)
    assert r["mapping"]["payment_date"] == "Payment Date" and r["mapping"]["due_date"] == "Due Date"
    assert r["payments"][0]["days_early_late"] == 9


def test_generic_date_column_not_mapped():
    p = write("generic.csv", "Customer,Date,Due Date,Paid Date,Amount\nAcme,2026-01-01,2026-01-31,2026-02-02,10\n")
    r = read_payments(p)
    assert "Date" not in r["mapping"].values() and r["mapping"]["payment_date"] == "Paid Date"


def test_european_file_with_title_rows():
    p = write("eu.csv", "Zahlungsbericht Q3;;;;\n;;;;\n"
              "Customer;Invoice No;Due Date;Payment Date;Amount Paid\n"
              "Müller GmbH;R-1;15.07.2026;20.07.2026;1.250,00\n"
              "Müller GmbH;R-2;31.07.2026;29.07.2026;980,50\n")
    r = read_payments(p)
    assert r["header_row"] == 3 and r["date_order"] == "dmy"
    a, b = r["payments"]
    assert a["amount"] == 1250.0 and a["days_early_late"] == 5
    assert b["amount"] == 980.5 and b["days_early_late"] == -2


def test_ambiguous_dates_stop_and_explain():
    p = write("amb.csv", "Customer,Due Date,Payment Date,Amount\nAcme,03/04/2026,05/04/2026,10\n")
    try:
        read_payments(p)
        assert False, "should have stopped"
    except ReadError as e:
        assert "date-order" in str(e)
    r = read_payments(p, date_order="mdy")
    assert r["payments"][0]["days_early_late"] == 61   # Mar 4 -> May 4


def test_mixed_date_orders_rejected():
    p = write("mixed.csv", "Customer,Due Date,Payment Date,Amount\nA,25/04/2026,26/04/2026,1\nB,04/25/2026,04/27/2026,1\n")
    try:
        read_payments(p)
        assert False
    except ReadError as e:
        assert "mix" in str(e)


def test_days_late_column_when_no_due_date():
    p = write("dl.csv", "Account Name,Receipt Date,Days Late,Payment Amount\nAcme,2026-05-01,12,500\n")
    r = read_payments(p)
    assert r["payments"][0]["days_early_late"] == 12 and r["payments"][0]["amount"] == 500


def test_missing_columns_explained_and_map_override():
    p = write("odd.csv", "Kunde,Fällig,Bezahlt,Betrag\nAcme,2026-01-31,2026-02-03,10\n")
    try:
        read_payments(p)
        assert False
    except ReadError as e:
        assert "Couldn't find" in str(e) and "Kunde" in str(e)
    r = read_payments(p, {"customer_name": "Kunde", "due_date": "Fällig", "payment_date": "Bezahlt", "amount": "Betrag"})
    assert r["payments"][0]["days_early_late"] == 3


def test_unpaid_and_credit_notes_skipped():
    p = write("skip.csv", "Customer,Due Date,Payment Date,Amount\nA,2026-01-01,,10\nA,2026-01-01,2026-01-02,-5\n"
              "A,2026-01-01,2026-01-03,7\n")
    r = read_payments(p)
    assert len(r["payments"]) == 1 and len(r["skipped"]) == 2


def test_no_amount_column_warns():
    p = write("noamt.csv", "Customer,Due Date,Payment Date\nA,2026-01-01,2026-01-02\n")
    r = read_payments(p)
    assert any("not amount-weighted" in w for w in r["warnings"])


def test_customer_id_groups_name_variants():
    p = write("ids.csv", "Customer Name,Customer ID,Due Date,Payment Date,Amount\n"
              "ACME Corp,77,2026-01-01,2026-01-02,1\nAcme Corporation,77,2026-02-01,2026-02-01,1\n"
              "Acme Corporation,77,2026-03-01,2026-03-01,1\n")
    r = read_payments(p)
    assert len({x["customer_key"] for x in r["payments"]}) == 1
    assert r["payments"][0]["customer_name"] == "Acme Corporation"


def test_xlsx_input():
    try:
        import openpyxl
    except ImportError:
        print("  (skipped: openpyxl not installed)")
        return
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Customer", "Due Date", "Payment Date", "Amount Paid"])
    ws.append(["Acme", datetime(2026, 1, 31), datetime(2026, 2, 5), 1200.5])
    p = os.path.join(TMP, "x.xlsx")
    wb.save(p)
    r = read_payments(p)
    assert r["payments"][0]["days_early_late"] == 5 and r["payments"][0]["amount"] == 1200.5


def test_end_to_end_sample():
    sample = os.path.join(SCRIPTS, "..", "assets", "sample-payments.csv")
    out = os.path.join(TMP, "out")
    res = subprocess.run([sys.executable, os.path.join(SCRIPTS, "payment_risk.py"), sample, "--out-dir", out],
                         capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr
    data = json.load(open(os.path.join(out, "results.json")))
    by = {c["customer"]: c for c in data["customers"]}
    assert by["Ironbark Construction"]["health"] == "at_risk"
    assert by["Riverbend Plastics"]["health"] == "watch"
    assert by["Harbor Point Fabrication"]["health"] == "healthy"
    assert by["Kestrel Aerospace Parts"]["window"]["volatility"] is not None
    assert by["Summit Ridge Outfitters"]["window"]["improvement"] is not None
    assert not by["Quillfeather Print"]["window"]["has_sufficient_data"]
    assert data["customers"][0]["attention"] == "high"
    for f in ("dashboard.html", "customers.csv"):
        assert os.path.getsize(os.path.join(out, f)) > 1000


def test_cli_unreadable_file_exit_code():
    p = write("bad.csv", "foo,bar\n1,2\n")
    res = subprocess.run([sys.executable, os.path.join(SCRIPTS, "payment_risk.py"), p, "--out-dir", TMP],
                         capture_output=True, text=True)
    assert res.returncode == 2 and "CANNOT READ FILE" in res.stdout


# ── Regression tests from the independent review ───────────────────────────

def run_cli(*args):
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, "payment_risk.py"), *args],
                          capture_output=True, text=True)


def test_title_row_above_semicolon_and_tab_headers():
    p = write("t1.csv", "Payment history export\nCustomer;Due Date;Payment Date;Amount\nA;2026-01-01;2026-01-05;1.250,00\n")
    r = read_payments(p)
    assert r["payments"][0]["amount"] == 1250.0 and r["payments"][0]["days_early_late"] == 4
    p = write("t2.tsv", "Payments, Q1 2025\nCustomer\tDue Date\tPayment Date\tAmount\nA\t2026-01-01\t2026-01-02\t10\n")
    assert read_payments(p)["payments"][0]["days_early_late"] == 1


def test_utf16_export():
    p = os.path.join(TMP, "u16.txt")
    with open(p, "w", encoding="utf-16") as f:
        f.write("Customer\tDue Date\tPayment Date\tAmount\r\nA\t2026-01-01\t2026-01-03\t5\r\n")
    assert read_payments(p)["payments"][0]["days_early_late"] == 2


def test_rows_without_id_join_their_customer():
    p = write("mixid.csv", "Customer,Customer ID,Due Date,Payment Date,Amount\nAcme Corp,C1,2026-01-01,2026-01-02,1\n"
              "Acme Corp,,2026-02-01,2026-02-02,1\nAcme Corp,C1,2026-03-01,2026-03-02,1\n")
    r = read_payments(p)
    assert len({x["customer_key"] for x in r["payments"]}) == 1


def test_as_of_drops_later_payments_everywhere():
    sample = os.path.join(SCRIPTS, "..", "assets", "sample-payments.csv")
    out = os.path.join(TMP, "asof")
    res = run_cli(sample, "--as-of", "2025-12-31", "--out-dir", out)
    assert res.returncode == 0 and "left out" in res.stdout
    data = json.load(open(os.path.join(out, "results.json")))
    assert data["portfolio"]["period"][1] <= "2025-12-31"
    assert all(c["days_since_last_payment"] >= 0 for c in data["customers"])


def test_watch_reason_never_blank():
    p = write("w.csv", "Customer,Due Date,Payment Date,Amount\nAcme,2025-01-01,2025-05-13,9\nAcme,2025-06-01,2025-06-01,70\n")
    out = os.path.join(TMP, "w")
    assert run_cli(p, "--out-dir", out).returncode == 0
    c = json.load(open(os.path.join(out, "results.json")))["customers"][0]
    if c["health"] == "watch":
        texts = [s["text"] for s in c["signals"] if s["type"] == "watch"]
        assert texts and texts[0] != "Watch: "


def test_bad_options_give_messages_not_tracebacks():
    sample = os.path.join(SCRIPTS, "..", "assets", "sample-payments.csv")
    for args in (["--set", "window_days=abc"], ["--set", "recent_count=0"], ["--set", "recent_count=2.7"],
                 ["--set", "at_risk_on_time_below=85"], ["--as-of", "2026/03/01"], ["--set", "nope=1"]):
        res = run_cli(sample, *args, "--out-dir", TMP)
        assert res.returncode == 2 and "INVALID OPTION" in res.stdout and "Traceback" not in res.stderr, args
    res = run_cli(os.path.join(TMP, "does-not-exist.csv"))
    assert res.returncode == 2 and "CANNOT READ FILE" in res.stdout


def test_recent_count_label_follows_setting():
    sample = os.path.join(SCRIPTS, "..", "assets", "sample-payments.csv")
    out = os.path.join(TMP, "rc")
    assert run_cli(sample, "--set", "recent_count=2", "--out-dir", out).returncode == 0
    html_text = open(os.path.join(out, "dashboard.html"), encoding="utf-8").read()
    assert ">Last 2<" in html_text and ">Last 3<" not in html_text


def test_amount_edge_cases():
    assert parse_amount("1e5") == 100000.0
    assert parse_amount("−100") == -100.0
    assert parse_amount("1,234.56 CR") == -1234.56
    assert parse_amount("(-5)") == -5.0
    assert parse_amount(",5") == 0.5
    assert parse_amount("1.250", ",") == 1250.0 and parse_amount("1.250", ".") == 1.25


def test_column_decimal_detection():
    p = write("dec.csv", "Customer;Due Date;Payment Date;Amount\nA;2026-01-01;2026-01-02;1.250\nA;2026-02-01;2026-02-02;980,50\n")
    a, b = read_payments(p)["payments"]
    assert a["amount"] == 1250.0 and b["amount"] == 980.5


def test_date_edge_cases():
    assert parse_date("Jan-2025", None) is None and parse_date("March 2025", None) is None
    assert str(parse_date("1/2/99", "mdy")) == "1999-01-02"
    assert str(parse_date("15-Jan-25 10:00", None)) == "2025-01-15"


def test_contradicting_date_order_warns():
    p = write("contra.csv", "Customer,Due Date,Payment Date,Amount\nA,03/20/2026,03/26/2026,1\nA,20/03/2026,26/03/2026,1\n"
              "A,04/01/2026,04/02/2026,1\n")
    try:
        read_payments(p)
    except ReadError:
        pass  # mixed orders are rejected without --date-order
    r = read_payments(p, date_order="mdy")
    assert any("can't be month-first" in w for w in r["warnings"])


def test_missing_sheet_message():
    try:
        import openpyxl
    except ImportError:
        return
    wb = openpyxl.Workbook()
    wb.active.title = "Payments"
    p = os.path.join(TMP, "s.xlsx")
    wb.save(p)
    try:
        read_payments(p, sheet="Nope")
        assert False
    except ReadError as e:
        assert "Payments" in str(e)


def test_csv_formula_injection_guard():
    p = write("inj.csv", 'Customer,Due Date,Payment Date,Amount\n"=HYPERLINK(""http://x"",""y"")",2026-01-01,2026-01-02,1\n')
    out = os.path.join(TMP, "inj")
    assert run_cli(p, "--out-dir", out).returncode == 0
    body = open(os.path.join(out, "customers.csv"), encoding="utf-8").read()
    assert "'=HYPERLINK" in body


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
