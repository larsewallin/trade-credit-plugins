"""
Renders results.json into one self-contained HTML dashboard (no external
files, fonts or libraries, works offline and as an email attachment).
All numbers come from the analysis; this module only formats them.
"""

from __future__ import annotations

import html
import json
from datetime import date

AUTHOR_URL = "https://larsewallin.com"

HEALTH = {
    "at_risk": ("At risk", "crit", "▲"),
    "watch": ("Watch", "warn", "●"),
    "healthy": ("Healthy", "good", "✓"),
    "unknown": ("Unknown", "none", "?"),
}
SEV = {"critical": ("Critical", "crit"), "high": ("High", "crit"), "medium": ("Medium", "warn"),
       "low": ("Low", "good"), "info": ("Info", "good")}
SIG_LABEL = {"health": "At risk", "watch": "Watch", "deterioration": "Paying later", "volatility": "Erratic timing",
             "improvement": "Paying earlier"}


def esc(x) -> str:
    return html.escape("" if x is None else str(x))


def money(x) -> str:
    if x is None:
        return "–"
    a = abs(x)
    if a >= 1e9:
        return f"{x / 1e9:.1f}B"
    if a >= 1e6:
        return f"{x / 1e6:.1f}M"
    if a >= 1e4:
        return f"{x / 1e3:.0f}K"
    return f"{x:,.0f}"


def pct(x) -> str:
    return "–" if x is None else f"{x * 100:.0f}%"


def days(x) -> str:
    if x is None:
        return "–"
    return f"{x:+.1f}"


def sparkline(history, as_of: str, start: str, w=132, h=30) -> str:
    pts = [(date.fromisoformat(p["date"]), p["days_late"]) for p in history]
    if not pts:
        return ""
    t0, t1 = date.fromisoformat(start), max(date.fromisoformat(as_of), pts[-1][0])  # same axis for every customer
    span = max((t1 - t0).days, 1)
    vals = [v for _, v in pts] + [0]
    lo, hi = min(vals), max(vals)
    if hi - lo < 10:
        mid = (hi + lo) / 2
        lo, hi = mid - 5, mid + 5
    pad = 3

    def X(d):
        return pad + (w - 2 * pad) * ((d - t0).days / span)

    def Y(v):
        return pad + (h - 2 * pad) * (1 - (v - lo) / (hi - lo))

    line = " ".join(f"{X(d):.1f},{Y(v):.1f}" for d, v in pts)
    zero = Y(0)
    dots = "".join(
        f'<circle cx="{X(d):.1f}" cy="{Y(v):.1f}" r="{3 if i == len(pts) - 1 else 1.6}" '
        f'class="{"pt-last" if i == len(pts) - 1 else "pt"}"><title>{d.isoformat()}: '
        f'{abs(v)} days {"late" if v > 0 else "early" if v < 0 else "(on due date)"}</title></circle>'
        for i, (d, v) in enumerate(pts))
    return (f'<svg class="spark" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" '
            f'aria-label="Days late per payment, {esc(start)} to {esc(as_of)}">'
            f'<line x1="{pad}" x2="{w - pad}" y1="{zero:.1f}" y2="{zero:.1f}" class="zero"/>'
            f'<polyline points="{line}" class="ln"/>{dots}</svg>')


def badge(kind, label, icon="") -> str:
    return f'<span class="badge {kind}">{f"<i aria-hidden=true>{icon}</i>" if icon else ""}{esc(label)}</span>'


def render(r: dict) -> str:
    p = r["portfolio"]
    cfg = r["config"]
    win = int(cfg["window_days"])
    total_val = p["amount_paid"] or 0
    weighted = p["amount_weighted"]
    multi = p["customers"] > 1

    # Stacked bar: value (or customers) by health
    seg_basis = "amount_paid" if weighted and total_val else "customers"
    seg_total = sum(v[seg_basis] for v in p["by_health"].values()) or 1
    segs, legend = [], []
    for h in ("at_risk", "watch", "healthy", "unknown"):
        v = p["by_health"][h]
        if not v["customers"]:
            continue
        share = v[seg_basis] / seg_total
        lab, cls, icon = HEALTH[h]
        val = money(v["amount_paid"]) if seg_basis == "amount_paid" else f"{v['customers']} customers"
        segs.append(f'<div class="seg {cls}" style="flex:{max(share, 0.004):.4f}" '
                    f'title="{lab}: {v["customers"]} customers, {val} ({share * 100:.0f}%)"></div>')
        legend.append(f'<span class="lg"><span class="sw {cls}"></span>{icon} {lab} '
                      f'<b>{share * 100:.0f}%</b> <span class="muted">· {v["customers"]} customers'
                      f'{" · " + money(v["amount_paid"]) if seg_basis == "amount_paid" else ""}</span></span>')

    rows = []
    for i, c in enumerate(r["customers"]):
        t = c["window"]
        lab, cls, icon = HEALTH[c["health"]]
        chips = "".join(
            f'<span class="chip {SEV[s["severity"]][1]}" title="{esc(s["text"])}">{esc(SIG_LABEL[s["type"]])}'
            f' <span class="muted">{SEV[s["severity"]][0]}</span></span>'
            for s in c["signals"] if s["type"] not in ("health", "watch"))
        if t["has_sufficient_data"]:
            delta = t["current_avg_days_late"] - t["prior_avg_days_late"]
            arrow = "↑" if delta >= 0.05 else "↓" if delta <= -0.05 else "→"
            wcell = (f'{days(t["current_avg_days_late"])} <span class="muted">vs {days(t["prior_avg_days_late"])}</span> '
                     f'<span class="{"bad" if delta >= cfg["swing_days"] else "goodtxt" if -delta >= cfg["swing_days"] else "muted"}">'
                     f'{arrow}</span>')
        else:
            wcell = '<span class="muted">not enough history</span>'
        hist = c["history"][-12:]
        hrows = "".join(
            f'<tr><td>{esc(x["date"])}</td><td>{esc(x["invoice"] or "–")}</td><td>{esc(x["due"] or "–")}</td>'
            f'<td class="num">{money(x["amount"]) if x["amount"] is not None else "–"}</td>'
            f'<td class="num {"bad" if x["days_late"] > cfg["on_time_grace_days"] else ""}">{x["days_late"]:+d}</td></tr>'
            for x in reversed(hist))
        dtp = "–" if c["avg_days_to_pay"] is None else "%.1f" % c["avg_days_to_pay"]
        idline = '<div class="muted">%s</div>' % esc(c["customer_id"]) if c["customer_id"] else ""
        sig_text = "".join(f"<li>{esc(s['text'])}</li>" for s in c["signals"]) or "<li>No warning signals.</li>"
        detail = (
            f'<tr class="detail" id="d{i}"{"" if not multi else " hidden"}><td colspan="8"><div class="dgrid">'
            f'<div><h4>Why it is flagged</h4><ul>{sig_text}</ul>'
            f'<dl><dt>Payments analysed</dt><dd>{c["payments"]} ({esc(c["first_payment"])} to {esc(c["last_payment"])})</dd>'
            f'<dt>Value paid</dt><dd>{money(c["amount_paid"])}</dd>'
            f'<dt>Average days to pay (from invoice)</dt><dd>{dtp}</dd>'
            f'<dt>Trend, first half vs second half of history</dt><dd>{esc(c["trend"].replace("_", " "))}</dd>'
            f'<dt>Days since last payment</dt><dd>{c["days_since_last_payment"]}</dd></dl></div>'
            f'<div><h4>Last {len(hist)} payments <span class="muted">(+ = days late, − = early)</span></h4>'
            f'<table class="mini"><thead><tr><th>Paid</th><th>Invoice</th><th>Due</th><th class="num">Amount</th>'
            f'<th class="num">Days</th></tr></thead><tbody>{hrows}</tbody></table></div></div></td></tr>')
        rows.append(
            f'<tr class="row" data-h="{c["health"]}" data-a="{c["attention"]}" data-n="{esc(c["customer"].lower())} {esc((c["customer_id"] or "").lower())}" '
            f'tabindex="0" aria-expanded="{"false" if multi else "true"}" aria-controls="d{i}">'
            f'<td><span class="caret" aria-hidden="true">›</span><b>{esc(c["customer"])}</b>'
            f'{idline}</td>'
            f'<td>{badge(cls, lab, icon)}</td>'
            f'<td class="num">{pct(c["on_time_rate"])}</td>'
            f'<td class="num">{pct(c["recent_on_time_rate"])}</td>'
            f'<td class="num">{days(c["avg_days_late"])}</td>'
            f'<td class="num nowrap">{wcell}</td>'
            f'<td>{chips or "<span class=muted>–</span>"}</td>'
            f'<td>{sparkline(c["history"], r["as_of"], p["period"][0])}</td></tr>{detail}')

    rc = int(cfg["recent_count"])
    th = [("Customer", ""), ("Health", ""), ("On time", "num"), (f"Last {rc}", "num"), ("Avg days late", "num"),
          (f"Last {win}d vs prior {win}d", "num"), ("Signals", ""), ("Payment timing", "")]
    head = "".join(f'<th class="{c}">{esc(t)}</th>' for t, c in th)

    thresholds = [
        ("On time", f"paid no later than {cfg['on_time_grace_days']:g} days after the due date"),
        ("At risk", f"history trending later (second half vs first half, by more than {cfg['trend_delta_days']:g} days) "
                    f"and under {cfg['at_risk_on_time_below'] * 100:.0f}% of value paid on time"),
        ("Watch", f"under {cfg['watch_on_time_below'] * 100:.0f}% paid on time, or more than "
                  f"{cfg['watch_avg_days_late_above']:g} days late on average, or trending later while still mostly on time"),
        ("Paying later", f"average days late in the last {win} days at least {cfg['swing_days']:g} days worse than the "
                         f"{win} days before and above zero; high from {cfg['high_swing_days']:g}, critical from {cfg['critical_swing_days']:g}"),
        ("Erratic timing", f"standard deviation of days late in the last {win} days of {cfg['volatility_stddev_days']:g}+ days "
                           f"(critical from {cfg['critical_volatility_stddev_days']:g}); needs payments in both {win}-day periods"),
        ("Paying earlier", f"the mirror of paying later; shown for information, never escalated"),
        (f"Last {int(cfg['recent_count'])}", f"share of value paid on time across the last {int(cfg['recent_count'])} payments"),
    ]
    thr = "".join(f"<dt>{esc(a)}</dt><dd>{esc(b)}</dd>" for a, b in thresholds)
    mapping = "".join(f"<li><b>{esc(k)}</b> ← “{esc(v)}”</li>" for k, v in r["read"]["mapping"].items())
    warns = "".join(f"<li>{esc(w)}</li>" for w in r["read"]["warnings"])
    sig = p["signals"]

    kpis = [
        ("Customers", f'{p["customers"]:,}', f'{p["payments"]:,} payments'),
        ("Paid on time" + (" (by value)" if weighted else ""), pct(p["on_time_rate"]),
         f'average {days(p["avg_days_late"])} days vs due'),
        ("Need attention", f'{p["attention"]["high"]}',
         (f'{pct(p["high_attention_amount_share"])} of value paid · ' if p["high_attention_amount_share"] is not None else "")
         + f'{p["attention"]["medium"]} more to watch'),
        ("Paying later", f'{sig["deteriorating"]}',
         f'{sig["volatile"]} erratic · {sig["improving"]} paying earlier'),
    ]
    if not multi and r["customers"]:
        c0 = r["customers"][0]
        w0 = c0["window"]
        kpis = [
            ("Paid on time" + (" (by value)" if weighted else ""), pct(c0["on_time_rate"]), f'{c0["payments"]} payments'),
            (f"Last {int(cfg['recent_count'])} payments on time", pct(c0["recent_on_time_rate"]), "share of value"),
            ("Average vs due date", days(c0["avg_days_late"]) + " days", "+ late, − early"),
            (f"Last {win} days vs due",
             days(w0["current_avg_days_late"]) + " days" if w0["has_sufficient_data"] else "–",
             f'prior {win} days: {days(w0["prior_avg_days_late"])}' if w0["has_sufficient_data"] else "not enough history"),
        ]
    kpi_html = "".join(f'<div class="kpi"><div class="kl">{esc(a)}</div><div class="kv">{esc(b)}</div>'
                       f'<div class="ks">{esc(c)}</div></div>' for a, b, c in kpis)

    data_note = (f'{sig["no_trend_data"]} of {p["customers"]} customers have too little history for the '
                 f'{win}-day comparison (they need payments in both of the last two {win}-day periods).'
                 if sig["no_trend_data"] else "")

    embedded = json.dumps({"as_of": r["as_of"], "portfolio": p}, default=str).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(r["title"])}</title>
<style>
:root{{color-scheme:light;--bg:#f6f5f2;--surface:#fcfcfb;--line:#e4e2dc;--text:#0b0b0b;--text2:#52514e;--muted:#7a7873;
--good:#0ca30c;--warn:#fab219;--crit:#d03b3b;--none:#a3a19b;--goodtxt:#006300;--badtxt:#b42323;--accent:#2a78d6;--chipbg:#efeee9}}
@media (prefers-color-scheme:dark){{:root:not([data-theme="light"]){{color-scheme:dark;--bg:#121211;--surface:#1a1a19;--line:#2e2e2b;
--text:#f0efec;--text2:#c3c2b7;--muted:#8f8e86;--goodtxt:#5fd35f;--badtxt:#f08080;--accent:#3987e5;--chipbg:#262624}}}}
:root[data-theme="dark"]{{color-scheme:dark;--bg:#121211;--surface:#1a1a19;--line:#2e2e2b;--text:#f0efec;--text2:#c3c2b7;
--muted:#8f8e86;--goodtxt:#5fd35f;--badtxt:#f08080;--accent:#3987e5;--chipbg:#262624}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);font:14px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
.wrap{{max-width:1180px;margin:0 auto;padding:28px 16px 48px}}
h1{{font-size:24px;margin:0 0 4px;letter-spacing:-.01em}}h2{{font-size:15px;margin:0 0 12px}}h4{{margin:0 0 8px;font-size:13px}}
.sub{{color:var(--text2)}}.muted{{color:var(--muted)}}.bad{{color:var(--badtxt);font-weight:600}}.goodtxt{{color:var(--goodtxt);font-weight:600}}
.card{{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:18px;margin-top:16px}}
.kpis{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-top:20px}}
.kpi{{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px}}
.kl{{color:var(--text2);font-size:12px}}.kv{{font-size:28px;font-weight:650;margin:2px 0;font-variant-numeric:tabular-nums}}.ks{{color:var(--muted);font-size:12px}}
.bar{{display:flex;gap:2px;height:14px;border-radius:4px;overflow:hidden}}.seg{{min-width:3px}}
.seg.crit,.sw.crit{{background:var(--crit)}}.seg.warn,.sw.warn{{background:var(--warn)}}.seg.good,.sw.good{{background:var(--good)}}.seg.none,.sw.none{{background:var(--none)}}
.legend{{display:flex;flex-wrap:wrap;gap:6px 18px;margin-top:10px;font-size:13px}}.sw{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px}}
.tools{{display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:space-between;margin-bottom:12px}}
.seg-btns{{display:flex;flex-wrap:wrap;gap:4px}}.seg-btns button{{border:1px solid var(--line);background:transparent;color:var(--text2);
border-radius:999px;padding:5px 12px;font:inherit;font-size:13px;cursor:pointer}}.seg-btns button[aria-pressed=true]{{background:var(--text);color:var(--surface);border-color:var(--text)}}
input[type=search]{{border:1px solid var(--line);background:var(--surface);color:var(--text);border-radius:8px;padding:6px 10px;font:inherit;min-width:220px}}
.tbl{{overflow-x:auto}}table{{border-collapse:collapse;width:100%}}th{{text-align:left;font-weight:600;color:var(--text2);font-size:12px;
padding:8px;border-bottom:1px solid var(--line);white-space:nowrap}}td{{padding:9px 8px;border-bottom:1px solid var(--line);vertical-align:middle}}
.num{{text-align:right;font-variant-numeric:tabular-nums}}.nowrap{{white-space:nowrap}}
tr.row{{cursor:pointer}}tr.row:hover td{{background:var(--chipbg)}}tr.row:focus-visible{{outline:2px solid var(--accent);outline-offset:-2px}}
.caret{{display:inline-block;width:14px;color:var(--muted);transition:transform .15s}}tr.row[aria-expanded=true] .caret{{transform:rotate(90deg)}}
td>.muted{{font-size:12px;margin-left:14px}}
.badge{{display:inline-flex;gap:5px;align-items:center;border-radius:999px;padding:2px 9px 2px 7px;font-size:12px;font-weight:600;white-space:nowrap;border:1px solid}}
.badge i{{font-style:normal;font-size:10px}}.badge.crit{{color:var(--badtxt);border-color:var(--crit)}}.badge.warn{{color:var(--text);border-color:var(--warn)}}
.badge.good{{color:var(--goodtxt);border-color:var(--good)}}.badge.none{{color:var(--muted);border-color:var(--none)}}
.chip{{display:inline-block;border-radius:6px;padding:1px 7px;margin:1px 4px 1px 0;font-size:12px;background:var(--chipbg);border-left:3px solid var(--none);white-space:nowrap}}
.chip.crit{{border-left-color:var(--crit)}}.chip.warn{{border-left-color:var(--warn)}}.chip.good{{border-left-color:var(--good)}}
.spark .zero{{stroke:var(--muted);stroke-dasharray:2 3;stroke-width:1}}.spark .ln{{fill:none;stroke:var(--text2);stroke-width:1.5}}
.spark .pt{{fill:var(--text2)}}.spark .pt-last{{fill:var(--accent);stroke:var(--surface);stroke-width:2}}
tr.detail td{{background:var(--bg)}}.dgrid{{display:grid;grid-template-columns:1fr 1.3fr;gap:24px;padding:6px 4px}}
.dgrid ul{{margin:0 0 10px;padding-left:18px}}dl{{display:grid;grid-template-columns:auto 1fr;gap:4px 14px;margin:0;font-size:13px}}dt{{color:var(--text2)}}dd{{margin:0}}
table.mini td,table.mini th{{padding:4px 6px;font-size:12px}}
details summary{{cursor:pointer;font-weight:600}}details[open] summary{{margin-bottom:10px}}.cols{{display:grid;grid-template-columns:1fr 1fr;gap:24px}}
.cols ul{{margin:0;padding-left:18px}}footer{{margin-top:28px;color:var(--text2);font-size:13px;border-top:1px solid var(--line);padding-top:14px}}
footer a{{color:var(--accent)}}.note{{font-size:13px;color:var(--text2);margin-top:10px}}
@media (max-width:760px){{.kpis{{grid-template-columns:repeat(2,minmax(0,1fr))}}.dgrid,.cols{{grid-template-columns:1fr}}input[type=search]{{min-width:0;width:100%}}}}
@media print{{.tools{{display:none}}tr.detail{{display:none}}body{{background:#fff}}}}
</style></head><body><div class="wrap">
<header><h1>{esc(r["title"])}</h1>
<div class="sub">As of {esc(r["as_of"])} · payments from {esc(p["period"][0])} to {esc(p["period"][1])} · source: {esc(r["source_file"])}</div></header>
<section class="kpis">{kpi_html}</section>
{f'''<section class="card"><h2>{"Value paid" if seg_basis == "amount_paid" else "Customers"} by payment health</h2>
<div class="bar" role="img" aria-label="Share by payment health">{"".join(segs)}</div><div class="legend">{"".join(legend)}</div></section>''' if multi else ""}
<section class="card"><div class="tools"{"" if multi else ' style="display:none"'}><h2 style="margin:0">Customers <span class="muted" id="cnt"></span></h2>
<div class="seg-btns" role="group" aria-label="Filter">
<button data-f="all" aria-pressed="true">All</button><button data-f="attn" aria-pressed="false">Needs attention</button>
<button data-f="at_risk" aria-pressed="false">At risk</button><button data-f="watch" aria-pressed="false">Watch</button>
<button data-f="healthy" aria-pressed="false">Healthy</button></div>
<input type="search" id="q" placeholder="Search customer" aria-label="Search customer"></div>
<div class="tbl"><table><thead><tr>{head}</tr></thead><tbody id="tb">{"".join(rows)}</tbody></table></div>
<div class="note">{"Sorted by urgency. Click a customer for the reasons and recent payments. " if multi else ""}Days are relative to the due date: + late, − early. {esc(data_note)}</div></section>
<section class="card"><details><summary>How this was calculated</summary><div class="cols">
<div><h4>Definitions</h4><dl>{thr}</dl></div>
<div><h4>Data used</h4><ul>{mapping}</ul>
<p class="muted">Date format: {esc(r["read"]["date_order"] or "ISO")} ({esc(r["read"]["date_order_basis"])}).
As of date: {esc(r["as_of_basis"])}. {r["read"]["skipped_count"]} of {r["read"]["row_count"]} rows skipped (unpaid items, credit notes, missing dates).</p>
{f"<h4>Warnings</h4><ul>{warns}</ul>" if warns else ""}</div></div>
<p class="muted">Metrics are weighted by payment value{"" if weighted else " (no amount column, so every payment counts equally)"}. Method: the open-source Payment Risk plugin by Lars E. Wallin, v{esc(r["tool"]["version"])}.</p></details></section>
<footer>Free and open source, by Lars E. Wallin. More tools and essays on AI in trade credit: <a href="{AUTHOR_URL}" target="_blank" rel="noopener">larsewallin.com</a></footer>
</div>
<script>
(function(){{var tb=document.getElementById('tb'),q=document.getElementById('q'),cnt=document.getElementById('cnt'),f='all';
function apply(){{var s=q.value.trim().toLowerCase(),n=0;tb.querySelectorAll('tr.row').forEach(function(r){{
var ok=(f==='all'||(f==='attn'?r.dataset.a!=='low':r.dataset.h===f))&&(!s||r.dataset.n.indexOf(s)>=0);
r.hidden=!ok;var d=document.getElementById(r.getAttribute('aria-controls'));if(!ok){{d.hidden=true;r.setAttribute('aria-expanded','false')}}if(ok)n++}});
cnt.textContent='('+n+')'}}
document.querySelectorAll('.seg-btns button').forEach(function(b){{b.onclick=function(){{f=b.dataset.f;
document.querySelectorAll('.seg-btns button').forEach(function(x){{x.setAttribute('aria-pressed',x===b)}});apply()}}}});
q.oninput=apply;
function toggle(r){{var d=document.getElementById(r.getAttribute('aria-controls'));d.hidden=!d.hidden;r.setAttribute('aria-expanded',!d.hidden)}}
tb.addEventListener('click',function(e){{var r=e.target.closest('tr.row');if(r)toggle(r)}});
tb.addEventListener('keydown',function(e){{var r=e.target.closest('tr.row');if(r&&(e.key==='Enter'||e.key===' ')){{e.preventDefault();toggle(r)}}}});
apply()}})();
</script>
<script type="application/json" id="data">{embedded}</script>
</body></html>"""
