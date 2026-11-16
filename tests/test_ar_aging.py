"""
Tests for the AR Aging skill: reader, aging rules and the end-to-end script.

Run:  python3 tests/test_ar_aging.py
"""

import csv
import io
import json
import os
import subprocess
import sys
import tempfile
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.join(HERE, "..", "plugins", "ar-aging", "skills", "ar-aging-review")
SCRIPTS = os.path.join(SKILL, "scripts")
sys.path.insert(0, SCRIPTS)

import ar_aging  # noqa: E402
from reader import ReadError, read_open_items  # noqa: E402

TMP = tempfile.mkdtemp()


def write(name, text):
    p = os.path.join(TMP, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


def run(path, *args):
    out = os.path.join(TMP, "out-" + os.path.basename(path))
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = ar_aging.main([path, "--out-dir", out, *args])
    res = None
    if code == 0:
        with open(os.path.join(out, "results.json"), encoding="utf-8") as f:
            res = json.load(f)
    return code, buf.getvalue(), res, out


def cust(res, name, cur=None):
    return next(c for c in res["customers"] if c["customer"] == name and (cur is None or c["currency"] == cur))


def test_buckets_and_severity():
    p = write("basic.csv", "\n".join([
        "Customer,Invoice No,Due Date,Open Amount",
        "Alpha,1,2026-10-31,100",     # 0 days: current
        "Alpha,2,2026-10-30,200",     # 1: 1-30
        "Beta,3,2026-10-01,300",      # 30: 1-30
        "Beta,4,2026-09-30,400",      # 31: 31-60
        "Gamma,5,2026-09-01,500",     # 60: 31-60
        "Gamma,6,2026-08-31,600",     # 61: 61-90
        "Delta,7,2026-08-02,700",     # 90: 61-90
        "Delta,8,2026-08-01,800",     # 91: over 90
        "Echo,9,2026-12-01,50",       # not yet due
    ]))
    code, out, res, _ = run(p, "--as-of", "2026-10-31")
    assert code == 0, out
    a, b, g, d, e = (cust(res, n) for n in ("Alpha", "Beta", "Gamma", "Delta", "Echo"))
    assert a["buckets"] == {"current": 100.0, "1_30": 200.0, "31_60": 0.0, "61_90": 0.0, "over_90": 0.0}
    assert b["buckets"]["1_30"] == 300.0 and b["buckets"]["31_60"] == 400.0
    assert g["buckets"]["31_60"] == 500.0 and g["buckets"]["61_90"] == 600.0
    assert d["buckets"]["61_90"] == 700.0 and d["buckets"]["over_90"] == 800.0
    assert [x["severity"] for x in (a, b, g, d, e)] == ["low", "medium", "high", "critical", "none"]
    assert d["oldest_days_past_due"] == 91
    # Priority order: worst bucket first
    assert [c["customer"] for c in res["customers"]] == ["Delta", "Gamma", "Beta", "Alpha", "Echo"]
    p0 = res["portfolio"]["unknown"]
    assert p0["gross_open"] == 3650.0 and p0["past_due"] == 3500.0
    assert abs(p0["past_due_share"] - 3500 / 3650) < 1e-9
    # Weighted average days past due over past-due items only
    exp = (1 * 200 + 30 * 300 + 31 * 400 + 60 * 500 + 61 * 600 + 90 * 700 + 91 * 800) / 3500
    assert p0["weighted_avg_days_past_due"] == round(exp, 1)


def test_credits_kept_apart_and_net_balance():
    p = write("credits.csv", "\n".join([
        "Customer,Invoice,Due Date,Balance",
        "Acme,INV1,2026-09-15,1000.00",
        "Acme,CN1,,(250.00)",
        "Acme,CASH,2026-10-01,-100",
        "Zeta,CN9,,-500",
    ]))
    code, out, res, _ = run(p, "--as-of", "2026-10-31")
    assert code == 0, out
    acme = cust(res, "Acme")
    assert acme["credits"] == -350.0 and acme["gross_open"] == 1000.0 and acme["net_open"] == 650.0
    assert acme["buckets"]["31_60"] == 1000.0
    zeta = cust(res, "Zeta")
    assert zeta["net_open"] == -500.0 and zeta["severity"] == "none"
    assert any("credit balance" in r for r in zeta["reasons"])


def test_credit_limits_and_utilisation():
    p = write("limits.csv", "\n".join([
        "Customer,Due Date,Amount Due,Credit Limit",
        "Over,2026-10-01,1100,1000",
        "Near,2026-11-30,850,1000",
        "Fine,2026-11-30,100,1000",
        "Edge,2026-11-30,999.7,1000",
    ]))
    code, out, res, _ = run(p, "--as-of", "2026-10-31")
    assert code == 0, out
    assert cust(res, "Over")["limit_flag"] == "over_limit"
    assert cust(res, "Near")["limit_flag"] == "near_limit"
    assert cust(res, "Fine")["limit_flag"] is None
    edge = cust(res, "Edge")
    assert edge["limit_flag"] == "near_limit"
    assert any("99% of" in r for r in edge["reasons"])  # floored, never "100%" while under the limit
    assert any("over the credit limit by 100.00" in r for r in cust(res, "Over")["reasons"])
    code, out, res, _ = run(p, "--as-of", "2026-10-31", "--set", "utilisation_high_pct=90")
    assert cust(res, "Near")["limit_flag"] is None


def test_currencies_never_added():
    p = write("fx.csv", "\n".join([
        "Customer;Customer ID;Due date;Open amount;Currency",
        "Nordic AB;N1;15.10.2026;1.000,00;SEK",
        "Nordic AB;N1;15.10.2026;500,00;EUR",
        "Other;O1;20.12.2026;2.500,50;EUR",
    ]))
    code, out, res, _ = run(p, "--as-of", "2026-10-31")
    assert code == 0, out
    assert set(res["portfolio"]) == {"SEK", "EUR"}
    assert res["portfolio"]["EUR"]["gross_open"] == 3000.5
    assert res["portfolio"]["SEK"]["gross_open"] == 1000.0
    assert len([c for c in res["customers"] if c["customer"] == "Nordic AB"]) == 2
    assert any("currencies" in w for w in res["read"]["warnings"])


def test_status_totals_and_skips():
    p = write("status.csv", "\n".join([
        "Aged receivables detail",
        "",
        "Customer,Invoice,Due Date,Outstanding,Status",
        "A,1,2026-10-01,100,Open",
        "A,2,2026-10-01,100,Paid",
        "A,3,2026-10-01,0,Open",
        ",,,,",
        "Total,,,200,",
        ",,,200,",
    ]))
    code, out, res, _ = run(p, "--as-of", "2026-10-31")
    assert code == 0, out
    assert res["portfolio"]["unknown"]["gross_open"] == 100.0
    reasons = " ".join(s["reason"] for s in res["read"]["skipped"])
    assert "status 'Paid'" in reasons and "zero open amount" in reasons and "total line" in reasons
    assert "no customer" in reasons


def test_summary_aging_rejected():
    p = write("summary.csv", "Customer,Current,1-30,31-60,61-90,Over 90,Total\nA,100,50,0,0,0,150\n")
    try:
        read_open_items(p)
    except ReadError as e:
        assert "aging summary" in str(e)
    else:
        raise AssertionError("summary file should be rejected")


def test_invoice_amount_fallback_warns():
    p = write("invamt.csv", "Customer,Due Date,Invoice Amount\nA,2026-10-01,100\n")
    code, out, res, _ = run(p, "--as-of", "2026-10-31")
    assert code == 0, out
    assert any("treated as the amount still owed" in w for w in res["read"]["warnings"])


def test_days_past_due_column_and_grace():
    p = write("dpd.csv", "Customer,Days Past Due,Open Amount\nA,3,100\nB,45,200\n")
    code, out, res, _ = run(p, "--as-of", "2026-10-31", "--set", "grace_days=5")
    assert code == 0, out
    assert cust(res, "A")["severity"] == "none" and cust(res, "A")["buckets"]["current"] == 100.0
    assert cust(res, "B")["buckets"]["31_60"] == 200.0


def test_ambiguous_dates_stop():
    p = write("amb.csv", "Customer,Due Date,Open Amount\nA,03/04/2026,100\nB,05/06/2026,100\n")
    code, out, res, _ = run(p)
    assert code == 2 and "--date-order" in out
    code, out, res, _ = run(p, "--date-order", "dmy", "--as-of", "2026-10-31")
    assert code == 0
    assert cust(res, "A")["oldest_days_past_due"] == 211  # 3 Apr -> 31 Oct


def test_stale_export_warning():
    p = write("stale.csv", "Customer,Invoice Date,Due Date,Open Amount\nA,2020-01-01,2020-01-31,100\n")
    code, out, res, _ = run(p)  # as of today
    assert code == 0
    assert any("--as-of" in w for w in res["read"]["warnings"])


def test_csv_formula_injection_and_outputs():
    p = write("inj.csv", 'Customer,Invoice,Due Date,Open Amount\n"=HYPERLINK(""x"")",=1+1,2026-10-01,100\n')
    code, out, res, outdir = run(p, "--as-of", "2026-10-31")
    assert code == 0, out
    with open(os.path.join(outdir, "customers.csv"), encoding="utf-8") as f:
        row = list(csv.reader(f))[1]
    assert row[0].startswith("'=")
    with open(os.path.join(outdir, "open_items.csv"), encoding="utf-8") as f:
        row = list(csv.reader(f))[1]
    assert row[3].startswith("'=")
    with open(os.path.join(outdir, "dashboard.html"), encoding="utf-8") as f:
        html = f.read()
    assert '=HYPERLINK(&quot;x&quot;)' in html  # escaped, never raw markup


def test_sample_file_end_to_end_cli():
    sample = os.path.join(SKILL, "assets", "sample-open-items.csv")
    out = os.path.join(TMP, "sample")
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "ar_aging.py"), sample, "--as-of", "2026-10-31",
                        "--out-dir", out], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Collections priority" in r.stdout
    with open(os.path.join(out, "results.json"), encoding="utf-8") as f:
        res = json.load(f)
    assert res["customers"][0]["customer"] == "Ironbark Construction"
    assert res["customers"][0]["severity"] == "critical"
    assert res["portfolio"]["USD"]["customers"] == 12
    for fn in ("dashboard.html", "customers.csv", "open_items.csv"):
        assert os.path.getsize(os.path.join(out, fn)) > 0
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, "ar_aging.py"), sample, "--inspect"],
                       capture_output=True, text=True)
    assert r.returncode == 0 and "Columns used" in r.stdout


def test_customer_filter_and_bad_options():
    sample = os.path.join(SKILL, "assets", "sample-open-items.csv")
    code, out, res, _ = run(sample, "--as-of", "2026-10-31", "--customer", "kestrel")
    assert code == 0 and [c["customer"] for c in res["customers"]] == ["Kestrel Aerospace Parts"]
    code, out, _, _ = run(sample, "--customer", "nobody")
    assert code == 3
    code, out, _, _ = run(sample, "--set", "grace_days=-1")
    assert code == 2 and "INVALID OPTION" in out
    code, out, _, _ = run(sample, "--as-of", "31/10/2026")
    assert code == 2


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"ok   {t.__name__}")
        except Exception as e:  # noqa: BLE001
            failed += 1
            print(f"FAIL {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
