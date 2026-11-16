"""
Renders results.json into one self-contained HTML dashboard (no external
files, fonts or libraries, works offline and as an email attachment).
All numbers come from the analysis; this module only formats them.
"""

from __future__ import annotations

import html
import json
import math

AUTHOR_URL = "https://larsewallin.com"
BUCKETS = ["current", "1_30", "31_60", "61_90", "over_90"]
BUCKET_LABEL = {"current": "Current", "1_30": "1–30", "31_60": "31–60", "61_90": "61–90", "over_90": "Over 90"}
SEV = {"critical": ("Critical", "crit", "▲"), "high": ("High", "crit", "●"), "medium": ("Medium", "warn", "●"),
       "low": ("Low", "good", "●"), "none": ("Current", "good", "✓")}
LIMIT = {"over_limit": ("Over limit", "crit"), "near_limit": ("Near limit", "warn")}


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


def full(x) -> str:
    return "–" if x is None else f"{x:,.2f}"


def pct(x) -> str:
    return "–" if x is None else f"{x * 100:.0f}%"


def pct_floor(x) -> str:
    return "–" if x is None else f"{math.floor(x * 100 + 1e-9):.0f}%"


def badge(kind, label, icon="") -> str:
    return f'<span class="badge {kind}">{f"<i aria-hidden=true>{icon}</i>" if icon else ""}{esc(label)}</span>'


def _portfolio_block(cur, p, multi_cur):
    sev = p["severity"]
    attn = sev["critical"] + sev["high"]
    curl = "" if cur == "unknown" else f" {cur}"
    kpis = [
        ("Open balance" + curl, money(p["net_open"]), f'{p["customers"]} customers · {p["open_items"]} open items'),
        ("Past due", pct(p["past_due_share"]), f'{money(p["past_due"])}{curl}'
         + (f' · avg {p["weighted_avg_days_past_due"]:g} days' if p["weighted_avg_days_past_due"] is not None else "")),
        ("Over 90 days", money(p["buckets"]["over_90"]), f'{pct(p["bucket_shares"]["over_90"])} of invoices'),
        ("Need attention", f"{attn}", f'{sev["critical"]} with over-90 balances · {sev["medium"]} at 31–60'
         + (f' · {p["over_limit"]} over limit' if p["with_limit"] else "")),
    ]
    kpi_html = "".join(f'<div class="kpi"><div class="kl">{esc(a)}</div><div class="kv">{esc(b)}</div>'
                       f'<div class="ks">{esc(c)}</div></div>' for a, b, c in kpis)
    segs, legend = [], []
    for k in BUCKETS:
        share = p["bucket_shares"][k]
        if not share:
            continue
        segs.append(f'<div class="seg b-{k}" style="flex:{max(share, 0.004):.4f}" '
                    f'title="{BUCKET_LABEL[k]}: {full(p["buckets"][k])} ({share * 100:.0f}%)"></div>')
        legend.append(f'<span class="lg"><span class="sw b-{k}"></span>{BUCKET_LABEL[k]}'
                      f'{" days" if k != "current" else ""} <b>{share * 100:.0f}%</b> '
                      f'<span class="muted">· {money(p["buckets"][k])}</span></span>')
    conc = (f'Largest customer {pct(p["largest_customer_share"])} of invoices, top 5 {pct(p["top5_share"])}.'
            + (f' Credits and unapplied cash: {full(p["credits"])}.' if p["credits"] else ""))
    title = f'<h2 class="curh">{esc(cur)}</h2>' if multi_cur else ""
    return (f'{title}<section class="kpis">{kpi_html}</section>'
            f'<section class="card"><h2>Open invoices by age</h2><div class="bar" role="img" '
            f'aria-label="Open invoices by days past due">{"".join(segs)}</div>'
            f'<div class="legend">{"".join(legend)}</div><div class="note">{esc(conc)}</div></section>')


def render(r: dict) -> str:
    P = r["portfolio"]
    multi_cur = len(P) > 1
    has_limit = any(c["credit_limit"] for c in r["customers"])
    blocks = "".join(_portfolio_block(cur, p, multi_cur) for cur, p in P.items())

    rows = []
    for i, c in enumerate(r["customers"]):
        lab, cls, icon = SEV[c["severity"]]
        lim = LIMIT.get(c["limit_flag"])
        b = c["buckets"]
        cells = "".join(f'<td class="num{" zero" if not b[k] else ""}">{money(b[k]) if b[k] else "–"}</td>' for k in BUCKETS)
        util = f'{pct_floor(c["utilisation"])}' if c["utilisation"] is not None else "–"
        lim_html = badge(lim[1], lim[0]) if lim else ""
        items = "".join(
            f'<tr><td>{esc(it["invoice"] or "–")}</td><td>{esc(it["due_date"] or "–")}</td>'
            f'<td class="num">{it["days_past_due"] if it["bucket"] != "credit" else "–"}</td>'
            f'<td>{esc(BUCKET_LABEL.get(it["bucket"], "Credit"))}</td><td class="num">{full(it["amount_open"])}</td></tr>'
            for it in c["items"][:25])
        more = f'<p class="muted">{len(c["items"]) - 25} more in open_items.csv</p>' if len(c["items"]) > 25 else ""
        reasons = "".join(f"<li>{esc(x)}</li>" for x in c["reasons"]) or "<li>Nothing past due.</li>"
        facts = [("Net open", full(c["net_open"])), ("Invoices", full(c["gross_open"])),
                 ("Credits", full(c["credits"])), ("Past due", f'{full(c["past_due"])} ({pct(c["past_due_share"])})'),
                 ("Oldest", f'{c["oldest_days_past_due"]} days past due' if c["oldest_days_past_due"] is not None else "–"),
                 ("Weighted avg", f'{c["weighted_avg_days_past_due"]:g} days past due' if c["weighted_avg_days_past_due"] is not None else "–")]
        if c["credit_limit"]:
            facts.append(("Credit limit", f'{full(c["credit_limit"])} · {util} used'))
        if c["currency"]:
            facts.append(("Currency", c["currency"]))
        dl = "".join(f"<dt>{esc(a)}</dt><dd>{esc(v)}</dd>" for a, v in facts)
        detail = (f'<tr class="detail" id="d{i}" hidden><td colspan="{9 + (1 if has_limit else 0)}"><div class="dgrid">'
                  f'<div><h4>Why</h4><ul>{reasons}</ul><dl>{dl}</dl></div>'
                  f'<div><h4>Open items, oldest first</h4><table class="mini"><thead><tr><th>Invoice</th><th>Due</th>'
                  f'<th class="num">Days past due</th><th>Bucket</th><th class="num">Open</th></tr></thead>'
                  f'<tbody>{items}</tbody></table>{more}</div></div></td></tr>')
        cid_html = f"<span class=muted>{esc(c['customer_id'])}</span>" if c["customer_id"] else ""
        name = esc(c["customer"]) + (f' <span class="muted">{esc(c["currency"])}</span>' if multi_cur and c["currency"] else "")
        rows.append(
            f'<tr class="row" tabindex="0" aria-expanded="false" aria-controls="d{i}" data-s="{c["severity"]}" '
            f'data-l="{c["limit_flag"] or ""}" data-n="{esc((c["customer"] + " " + (c["customer_id"] or "")).lower())}">'
            f'<td><span class="caret" aria-hidden="true">›</span>{name}'
            f'{cid_html}</td>'
            f'<td>{badge(cls, lab, icon)} {lim_html}</td><td class="num">{money(c["net_open"])}</td>{cells}'
            f'<td class="num">{pct(c["past_due_share"])}</td>'
            + (f'<td class="num">{util}</td>' if has_limit else "") + f'</tr>{detail}')

    th = [("Customer", ""), ("Worst bucket", ""), ("Open", "num")] + [(BUCKET_LABEL[k], "num") for k in BUCKETS] \
        + [("Past due", "num")] + ([("Limit used", "num")] if has_limit else [])
    head = "".join(f'<th class="{c}">{esc(t)}</th>' for t, c in th)
    cfg = r["config"]
    defs = [
        ("Days past due", f"as-of date ({r['as_of']}) minus due date"
         + (f"; up to {cfg['grace_days']} days past due counts as current" if cfg["grace_days"] else "")),
        ("Buckets", "Current (not yet due), 1–30, 31–60, 61–90, over 90 days past due"),
        ("Worst bucket", "the oldest bucket with a past-due amount: over 90 critical, 61–90 high, 31–60 medium, 1–30 low"),
        ("Credits", "credit notes and unapplied cash (negative amounts) reduce the balance; they are not put in a bucket"),
        ("Limit used", f"net open balance ÷ credit limit; over 100% = over limit, above {cfg['utilisation_high_pct']}% = near limit"),
        ("Currencies", "kept apart and never converted"),
    ]
    dd = "".join(f"<dt>{esc(a)}</dt><dd>{esc(b)}</dd>" for a, b in defs)
    mapping = "".join(f"<li><b>{esc(k)}</b> ← “{esc(v)}”</li>" for k, v in r["read"]["mapping"].items())
    warns = "".join(f"<li>{esc(w)}</li>" for w in r["read"]["warnings"])
    embedded = json.dumps({"as_of": r["as_of"], "portfolio": P}, default=str).replace("</", "<\\/")
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
.b-current{{background:#0ca30c}}.b-1_30{{background:#8cc63f}}.b-31_60{{background:var(--warn)}}.b-61_90{{background:#ef7d22}}.b-over_90{{background:var(--crit)}}
td.zero{{color:var(--muted)}}.curh{{margin:26px 0 -6px;font-size:17px}}.badge+.badge{{margin-left:4px}}
</style></head><body><div class="wrap">
<header><h1>{esc(r["title"])}</h1>
<div class="sub">Aged to {esc(r["as_of"])} ({esc(r["as_of_basis"])}) · source: {esc(r["source_file"])}</div></header>
{blocks}
<section class="card"><div class="tools"><h2 style="margin:0">Customers <span class="muted" id="cnt"></span></h2>
<div class="seg-btns" role="group" aria-label="Filter">
<button data-f="all" aria-pressed="true">All</button><button data-f="pd" aria-pressed="false">Past due</button>
<button data-f="attn" aria-pressed="false">Critical and high</button>
{'<button data-f="lim" aria-pressed="false">Over or near limit</button>' if has_limit else ''}</div>
<input type="search" id="q" placeholder="Search customer" aria-label="Search customer"></div>
<div class="tbl"><table><thead><tr>{head}</tr></thead><tbody id="tb">{"".join(rows)}</tbody></table></div>
<div class="note">Collections priority: worst bucket first, then over-limit accounts, then the largest old balances. Click a customer for the reasons and open items.</div></section>
<section class="card"><details><summary>How this was calculated</summary><div class="cols">
<div><h4>Definitions</h4><dl>{dd}</dl></div>
<div><h4>Data used</h4><ul>{mapping}</ul>
<p class="muted">Date format: {esc(r["read"]["date_order"] or "ISO")} ({esc(r["read"]["date_order_basis"])}).
Amount: {"open amount" if r["read"]["amount_basis"] == "amount_open" else "invoice amount, treated as fully open"}.
{r["read"]["skipped_count"]} of {r["read"]["row_count"]} rows skipped (paid or zero items, totals, missing dates).</p>
{f"<h4>Warnings</h4><ul>{warns}</ul>" if warns else ""}</div></div>
<p class="muted">Method: the open-source AR Aging skill by Lars E. Wallin, v{esc(r["tool"]["version"])}. An aging report shows how old the balances are; it is not a credit rating. Disputes, credit notes not yet issued and agreed extensions can all make an invoice look overdue.</p></details></section>
<footer>Free and open source, by Lars E. Wallin. More tools and essays on AI in trade credit: <a href="{AUTHOR_URL}" target="_blank" rel="noopener">larsewallin.com</a></footer>
</div>
<script>
(function(){{var tb=document.getElementById('tb'),q=document.getElementById('q'),cnt=document.getElementById('cnt'),f='all';
function keep(r){{if(f==='all')return true;if(f==='pd')return r.dataset.s!=='none';if(f==='attn')return r.dataset.s==='critical'||r.dataset.s==='high';return r.dataset.l!==''}}
function apply(){{var s=q.value.trim().toLowerCase(),n=0;tb.querySelectorAll('tr.row').forEach(function(r){{
var ok=keep(r)&&(!s||r.dataset.n.indexOf(s)>=0);
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
