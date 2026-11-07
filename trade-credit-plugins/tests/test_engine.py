"""
Unit tests for the payment risk engines. Ported 1:1 from the production
TypeScript test suite (analyse-payment-behaviour.test.ts and
analyse-payment-trend.test.ts), plus tests for the plugin's additions.

Run:  python3 tests/test_engine.py     (no dependencies; pytest also works)
"""

import os
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "plugins", "payment-risk", "skills", "payment-risk-review", "scripts"))

from engine import analyse_payment_behaviour as apb, analyse_payment_trend as apt  # noqa: E402


# ── Behaviour ────────────────────────────────────────────────────────────────

def tx(payment_date, days_early_late, on_time, amount=10_000):
    return {"payment_date": payment_date, "days_to_pay": 30 + days_early_late,
            "days_early_late": days_early_late, "on_time": on_time, "amount": amount}


def test_empty_returns_unknown():
    r = apb([])
    assert r["on_time_rate"] is None and r["avg_days_early_late"] is None
    assert r["recent_on_time_rate"] is None and r["trend"] == "insufficient_data"
    assert r["total_transactions"] == 0 and r["health"] == "unknown"


def test_none_returns_unknown():
    r = apb(None)
    assert r["on_time_rate"] is None and r["health"] == "unknown"


def test_healthy_customer():
    r = apb([tx("2025-01-15", -2, True), tx("2025-02-15", 0, True), tx("2025-03-15", -1, True),
             tx("2025-04-15", -3, True), tx("2025-05-15", 1, True), tx("2025-06-15", -2, True)])
    assert r["on_time_rate"] == 1 and r["health"] == "healthy"
    assert r["trend"] != "deteriorating" and r["total_transactions"] == 6


def test_deteriorating_is_at_risk():
    r = apb([tx("2025-01-01", -1, True), tx("2025-02-01", 0, True), tx("2025-03-01", 5, False),
             tx("2025-04-01", 12, False), tx("2025-05-01", 18, False), tx("2025-06-01", 25, False)])
    assert r["on_time_rate"] < 0.5 and r["trend"] == "deteriorating" and r["health"] == "at_risk"


def test_single_transaction():
    r = apb([tx("2025-06-01", 5, False)])
    assert r["total_transactions"] == 1 and r["on_time_rate"] == 0 and r["trend"] == "insufficient_data"


def test_improving_trend():
    r = apb([tx("2025-01-01", 15, False), tx("2025-02-01", 12, False),
             tx("2025-03-01", -2, True), tx("2025-04-01", -3, True)])
    assert r["trend"] == "improving"


def test_always_late_but_stable_is_watch():
    r = apb([tx("2025-01-01", 20, False), tx("2025-02-01", 18, False),
             tx("2025-03-01", 22, False), tx("2025-04-01", 19, False)])
    assert r["trend"] == "stable" and r["health"] == "watch"


def test_deteriorating_low_on_time_is_at_risk():
    r = apb([tx("2025-01-01", -2, True), tx("2025-02-01", 0, True), tx("2025-03-01", 2, True),
             tx("2025-04-01", 8, False), tx("2025-05-01", 10, False), tx("2025-06-01", 12, False)])
    assert r["trend"] == "deteriorating" and r["health"] == "at_risk"


def test_trend_threshold_boundary():
    assert apb([tx("2025-01-01", 0, True), tx("2025-02-01", 3, True)])["trend"] == "stable"
    assert apb([tx("2025-01-01", 0, True), tx("2025-02-01", 4, True)])["trend"] == "deteriorating"


def test_amount_weighting():
    r = apb([tx("2025-01-01", 0, True, 1_000), tx("2025-02-01", 0, True, 1_000),
             tx("2025-03-01", 30, False, 100_000)])
    assert r["on_time_rate"] < 0.1


def test_recent_on_time_rate_last_three():
    r = apb([tx("2025-01-01", 10, False), tx("2025-02-01", 10, False), tx("2025-03-01", 10, False),
             tx("2025-04-01", 0, True), tx("2025-05-01", 0, True), tx("2025-06-01", 0, True)])
    assert r["recent_on_time_rate"] == 1 and r["on_time_rate"] < 1


# Plugin additions

def test_zero_amount_tail_does_not_produce_nan():
    r = apb([tx("2025-01-01", 0, True), tx("2025-02-01", 5, False, 0), tx("2025-03-01", 5, False, 0),
             tx("2025-04-01", 5, False, 0)])
    assert r["recent_on_time_rate"] is None


def test_thresholds_are_configurable():
    rows = [tx("2025-01-01", 0, True), tx("2025-02-01", 4, True)]
    assert apb(rows)["trend"] == "deteriorating"
    assert apb(rows, {"trend_delta_days": 5})["trend"] == "stable"


# ── Trend ────────────────────────────────────────────────────────────────────

NOW = datetime(2026, 9, 23, tzinfo=timezone.utc)


def t(days_ago, del_):
    return {"payment_date": (NOW - timedelta(days=days_ago)).date().isoformat(), "days_early_late": del_}


def test_trend_no_transactions():
    r = apt([], NOW)
    assert r == {"has_sufficient_data": False, "current_window_count": 0, "prior_window_count": 0}


def test_trend_only_current_window():
    r = apt([t(5, 10), t(10, 12)], NOW)
    assert not r["has_sufficient_data"] and r["current_window_count"] == 2 and r["prior_window_count"] == 0


def test_trend_only_prior_window():
    r = apt([t(100, 10), t(150, 12)], NOW)
    assert not r["has_sufficient_data"] and r["current_window_count"] == 0 and r["prior_window_count"] == 2


def test_swing_5_medium_deterioration():
    r = apt([t(5, 5), t(120, 0)], NOW)
    assert r["has_sufficient_data"]
    assert r["deterioration"] == {"trend_direction": "worsening", "severity": "medium"}
    assert r["improvement"] is None


def test_swing_15_high_deterioration():
    assert apt([t(5, 15), t(120, 0)], NOW)["deterioration"] == {"trend_direction": "sharply_worsening", "severity": "high"}


def test_swing_25_critical_deterioration():
    assert apt([t(5, 25), t(120, 0)], NOW)["deterioration"] == {"trend_direction": "sharply_worsening", "severity": "critical"}


def test_no_deterioration_when_still_early():
    r = apt([t(5, -10), t(120, -20)], NOW)
    assert r["current_avg_days_late"] == -10 and r["deterioration"] is None


def test_small_swing_is_stable():
    r = apt([t(5, 3), t(120, 0)], NOW)
    assert r["deterioration"] is None and r["improvement"] is None


def test_improvement_5_is_info():
    r = apt([t(5, 5), t(120, 10)], NOW)
    assert r["improvement"] == {"trend_direction": "improving", "severity": "info"} and r["deterioration"] is None


def test_improvement_15_is_low():
    assert apt([t(5, 5), t(120, 20)], NOW)["improvement"] == {"trend_direction": "sharply_improving", "severity": "low"}


def test_improvement_capped_at_low():
    assert apt([t(5, 5), t(120, 35)], NOW)["improvement"] == {"trend_direction": "sharply_improving", "severity": "low"}


def test_no_improvement_when_already_early():
    assert apt([t(5, -10), t(120, -2)], NOW)["improvement"] is None


def test_low_stddev_no_volatility():
    assert apt([t(2, 5), t(20, 6), t(45, 4), t(70, 5), t(120, 5)], NOW)["volatility"] is None


def test_volatility_high():
    r = apt([t(2, -15), t(60, 15), t(120, 0)], NOW)
    assert r["volatility"] == {"severity": "high", "standard_deviation_days": 15}


def test_volatility_critical():
    r = apt([t(2, -25), t(60, 25), t(120, 0)], NOW)
    assert r["volatility"] == {"severity": "critical", "standard_deviation_days": 25}


def test_volatility_alongside_deterioration():
    r = apt([t(2, -15), t(60, 25), t(120, 0)], NOW)
    assert r["deterioration"] is not None and r["volatility"] is not None


def test_ignores_null_days_early_late():
    assert apt([t(5, 10), t(6, None), t(120, 0)], NOW)["current_window_count"] == 1


def test_exactly_90_days_is_current_window():
    r = apt([t(90, 8), t(135, 0)], NOW)
    assert r["current_window_count"] == 1 and r["prior_window_count"] == 1


def test_window_is_configurable():
    r = apt([t(50, 8), t(70, 0)], NOW, {"window_days": 60})
    assert r["current_window_count"] == 1 and r["prior_window_count"] == 1


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"FAIL {name}: {e!r}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
