"""
Payment risk engines, ported from production TypeScript skills:

  analyse_payment_behaviour  <- analyse-payment-behaviour.ts
  analyse_payment_trend      <- analyse-payment-trend.ts

Logic is kept identical to the originals (verified side by side against the
TypeScript in tests/test_parity.py). Differences from the originals:
  - every threshold is a parameter (defaults = production values);
  - a guard so a zero-amount tail of payments cannot produce NaN.

Conventions:
  days_early_late: negative = paid early, positive = paid late (vs due date).
  amounts weight the behaviour metrics; a missing amount weighs 1.

Standard library only.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

# ── Defaults (production values) ──────────────────────────────────────────────

DEFAULTS = {
    # behaviour
    "trend_delta_days": 3.0,          # half-vs-half change in avg days late that counts as a trend
    "at_risk_on_time_below": 0.85,    # deteriorating AND on-time rate below this -> at_risk
    "watch_on_time_below": 0.70,      # on-time rate below this -> watch
    "watch_avg_days_late_above": 15.0,  # avg days late above this -> watch
    "recent_count": 3,                # payments used for the recent on-time rate
    "on_time_grace_days": 0,          # paid up to N days after due still counts as on time
    # trend
    "window_days": 90,                # length of the current and prior comparison windows
    "swing_days": 5.0,                # min change in avg days late to flag deterioration/improvement
    "high_swing_days": 10.0,
    "critical_swing_days": 20.0,
    "volatility_stddev_days": 10.0,   # stddev of days late in the current window that flags volatility
    "critical_volatility_stddev_days": 20.0,
}

MS_PER_DAY = 24 * 60 * 60 * 1000


def js_round1(x: float) -> float:
    """Math.round(x * 10) / 10 exactly as JavaScript does it (half rounds up)."""
    return math.floor(x * 10 + 0.5) / 10


def to_epoch_ms(value) -> float:
    """ISO date (YYYY-MM-DD) or datetime -> UTC epoch ms, like JS new Date('YYYY-MM-DD')."""
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    else:
        s = str(value)
        if len(s) == 10:
            dt = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp() * 1000


def jsum(values) -> float:
    """Plain left-to-right addition, like JS reduce. (Python's sum() uses
    compensated summation for floats, which can flip a rounding at .x5.)"""
    total = 0.0
    for v in values:
        total += v
    return total


def _w(t: dict) -> float:
    """Weight = amount; JS `t.amount ?? 1` (None -> 1, 0 stays 0)."""
    a = t.get("amount")
    return 1.0 if a is None else float(a)


# ── Behaviour ─────────────────────────────────────────────────────────────────

def analyse_payment_behaviour(transactions, cfg: dict | None = None) -> dict:
    """
    transactions: list of dicts with payment_date, days_to_pay, days_early_late,
    on_time (bool), amount.
    Returns on_time_rate, avg_days_early_late, avg_days_to_pay, trend,
    total_transactions, recent_on_time_rate, health.
    """
    c = {**DEFAULTS, **(cfg or {})}

    if not transactions:
        return {
            "on_time_rate": None,
            "avg_days_early_late": None,
            "avg_days_to_pay": None,
            "trend": "insufficient_data",
            "total_transactions": 0,
            "recent_on_time_rate": None,
            "health": "unknown",
        }

    # Stable sort ascending by payment date (JS Array.sort is stable too)
    srt = sorted(transactions, key=lambda t: to_epoch_ms(t["payment_date"]))
    total = len(srt)

    total_amount = jsum(_w(t) for t in srt)
    weighted_on_time = jsum(_w(t) if t.get("on_time") else 0.0 for t in srt)
    on_time_rate = weighted_on_time / total_amount if total_amount > 0 else 0.0

    def wavg(field, rows, denom):
        if denom == 0:
            return None
        return jsum((r.get(field) or 0) * _w(r) for r in rows) / denom

    avg_days_early_late = wavg("days_early_late", srt, total_amount)
    avg_days_to_pay = wavg("days_to_pay", srt, total_amount)

    recent = srt[-max(1, int(c["recent_count"])):]
    recent_amount = jsum(_w(t) for t in recent)
    recent_on_time_rate = (
        jsum(_w(t) if t.get("on_time") else 0.0 for t in recent) / recent_amount
        if recent_amount > 0 else None  # guard: the TS original returns NaN here
    )

    trend = "insufficient_data"
    if total >= 2:
        half = math.ceil(total / 2)
        early, late = srt[:half], srt[half:]
        ea, la = jsum(_w(t) for t in early), jsum(_w(t) for t in late)
        if ea > 0 and la > 0:
            early_avg = jsum(t["days_early_late"] * _w(t) for t in early) / ea
            late_avg = jsum(t["days_early_late"] * _w(t) for t in late) / la
            delta = late_avg - early_avg
            if delta > c["trend_delta_days"]:
                trend = "deteriorating"
            elif delta < -c["trend_delta_days"]:
                trend = "improving"
            else:
                trend = "stable"

    health = "healthy"
    ade = avg_days_early_late if avg_days_early_late is not None else 0.0
    if trend == "deteriorating" and on_time_rate < c["at_risk_on_time_below"]:
        health = "at_risk"
    elif on_time_rate < c["watch_on_time_below"] or ade > c["watch_avg_days_late_above"]:
        health = "watch"
    elif trend == "deteriorating":
        health = "watch"  # deteriorating but still paying well overall

    return {
        "on_time_rate": on_time_rate,
        "avg_days_early_late": js_round1(avg_days_early_late) if avg_days_early_late is not None else None,
        "avg_days_to_pay": js_round1(avg_days_to_pay) if avg_days_to_pay is not None else None,
        "trend": trend,
        "total_transactions": total,
        "recent_on_time_rate": recent_on_time_rate,
        "health": health,
    }


# ── Trend (two adjacent windows) ──────────────────────────────────────────────

def _mean(v):
    return jsum(v) / len(v)


def _pop_stddev(v):
    m = _mean(v)
    return math.sqrt(jsum((x - m) ** 2 for x in v) / len(v))


def analyse_payment_trend(transactions, reference_date=None, cfg: dict | None = None) -> dict:
    """
    Compare avg days late in the current window (last `window_days` up to the
    reference date) with the prior window of the same length. Flags
    deterioration, improvement and volatility independently.
    """
    c = {**DEFAULTS, **(cfg or {})}
    valid = [t for t in (transactions or []) if t.get("days_early_late") is not None]

    now = to_epoch_ms(reference_date) if reference_date is not None else datetime.now(timezone.utc).timestamp() * 1000
    wd = c["window_days"]
    current_start = now - wd * MS_PER_DAY
    prior_start = now - 2 * wd * MS_PER_DAY

    current, prior = [], []
    for t in valid:
        ts = to_epoch_ms(t["payment_date"])
        if current_start <= ts <= now:
            current.append(t["days_early_late"])
        elif prior_start <= ts < current_start:
            prior.append(t["days_early_late"])

    if not current or not prior:
        return {
            "has_sufficient_data": False,
            "current_window_count": len(current),
            "prior_window_count": len(prior),
        }

    cur = js_round1(_mean(current))
    pri = js_round1(_mean(prior))
    swing = cur - pri

    def det_sev(s):
        if s >= c["critical_swing_days"]:
            return {"trend_direction": "sharply_worsening", "severity": "critical"}
        if s >= c["high_swing_days"]:
            return {"trend_direction": "sharply_worsening", "severity": "high"}
        return {"trend_direction": "worsening", "severity": "medium"}

    def imp_sev(s):
        if s >= c["high_swing_days"]:
            return {"trend_direction": "sharply_improving", "severity": "low"}
        return {"trend_direction": "improving", "severity": "info"}

    deterioration = det_sev(swing) if swing >= c["swing_days"] and cur > 0 else None
    improvement = imp_sev(-swing) if -swing >= c["swing_days"] and pri > 0 else None

    sd = js_round1(_pop_stddev(current))
    volatility = (
        {"severity": "critical" if sd >= c["critical_volatility_stddev_days"] else "high",
         "standard_deviation_days": sd}
        if sd >= c["volatility_stddev_days"] else None
    )

    return {
        "has_sufficient_data": True,
        "current_avg_days_late": cur,
        "prior_avg_days_late": pri,
        "current_window_count": len(current),
        "prior_window_count": len(prior),
        "deterioration": deterioration,
        "improvement": improvement,
        "volatility": volatility,
    }
