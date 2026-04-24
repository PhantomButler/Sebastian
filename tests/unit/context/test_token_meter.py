from sebastian.context.token_meter import ContextTokenMeter
from sebastian.context.usage import TokenUsage


def test_meter_uses_reported_usage_threshold() -> None:
    meter = ContextTokenMeter(context_window=100_000)

    decision = meter.should_compact(usage=TokenUsage(input_tokens=70_000), estimate=None)

    assert decision.should_compact is True
    assert decision.reason == "usage_threshold"


def test_meter_uses_lower_estimate_threshold() -> None:
    meter = ContextTokenMeter(context_window=100_000)

    decision = meter.should_compact(usage=None, estimate=65_000)

    assert decision.should_compact is True
    assert decision.reason == "estimate_threshold"


def test_meter_returns_no_data_reason_when_both_inputs_missing() -> None:
    meter = ContextTokenMeter(context_window=100_000)

    decision = meter.should_compact(usage=None, estimate=None)

    assert decision.should_compact is False
    assert decision.reason == "no_data"
    assert decision.token_count is None


def test_meter_hard_threshold_takes_priority_over_soft() -> None:
    meter = ContextTokenMeter(context_window=100_000)

    decision = meter.should_compact(usage=TokenUsage(input_tokens=86_000), estimate=None)

    assert decision.should_compact is True
    assert decision.reason == "usage_hard"
    assert decision.threshold == 85_000


def test_meter_soft_threshold_triggered_below_hard() -> None:
    meter = ContextTokenMeter(context_window=100_000)

    decision = meter.should_compact(usage=TokenUsage(input_tokens=75_000), estimate=None)

    assert decision.should_compact is True
    assert decision.reason == "usage_threshold"
    assert decision.threshold == 70_000


def test_meter_below_all_thresholds_no_compact() -> None:
    meter = ContextTokenMeter(context_window=100_000)

    decision = meter.should_compact(usage=TokenUsage(input_tokens=50_000), estimate=None)

    assert decision.should_compact is False
    assert decision.reason == "usage_threshold"
