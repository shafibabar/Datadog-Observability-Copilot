"""Spec for the telemetry domain model, the DataSource interface, and the
ReplayAdapter's canonical deployment-induced latency incident.

Written test-first (TDD red) before the implementation exists.
"""
import pytest

from app.telemetry.base import DataSource
from app.telemetry.models import EventSource, MetricSeries, TelemetryEvent
from app.telemetry.replay import ReplayAdapter


# --- domain model ---------------------------------------------------------

def test_metric_series_aggregates():
    s = MetricSeries(metric="m", unit="ms", points=[])
    s = MetricSeries.model_validate(
        {"metric": "m", "unit": "ms", "points": [
            {"timestamp": "2024-01-15T09:00:00Z", "value": 100.0},
            {"timestamp": "2024-01-15T09:01:00Z", "value": 300.0},
        ]}
    )
    assert s.max_value() == 300.0
    assert s.min_value() == 100.0
    assert s.latest().value == 300.0


def test_telemetry_event_requires_core_fields():
    e = TelemetryEvent(
        id="e1",
        timestamp="2024-01-15T09:02:00Z",
        source=EventSource.DEPLOY,
        title="Deployment initiated",
    )
    assert e.source == EventSource.DEPLOY
    assert e.title


# --- interface ------------------------------------------------------------

def test_replay_adapter_is_a_datasource():
    assert issubclass(ReplayAdapter, DataSource)
    assert isinstance(ReplayAdapter(), DataSource)


def test_replay_source_type():
    assert ReplayAdapter().source_type == "replay"


# --- metrics --------------------------------------------------------------

def test_lists_expected_metrics():
    metrics = ReplayAdapter().list_metrics()
    assert isinstance(metrics, list)
    for expected in ["api.latency.p95", "db.query.latency.p95", "cache.hit_ratio", "api.error_rate"]:
        assert expected in metrics


def test_latency_spikes_during_incident():
    s = ReplayAdapter().get_metric("api.latency.p95")
    assert s.points  # non-empty
    # Latency should spike well above baseline, then recover.
    assert s.max_value() > 400
    assert s.min_value() < 200
    assert s.max_value() > s.min_value() * 2


def test_cache_hit_ratio_declines():
    s = ReplayAdapter().get_metric("cache.hit_ratio")
    assert s.max_value() >= 0.9   # healthy baseline
    assert s.min_value() < 0.8    # declines during incident


def test_error_rate_stays_stable():
    # The story: customers experience *slowness*, not failures.
    s = ReplayAdapter().get_metric("api.error_rate")
    assert s.max_value() < 1.5


def test_unknown_metric_raises():
    with pytest.raises(KeyError):
        ReplayAdapter().get_metric("does.not.exist")


def test_get_metric_window_filters_points():
    a = ReplayAdapter()
    full = a.get_metric("api.latency.p95")
    mid = full.points[len(full.points) // 2].timestamp
    sub = a.get_metric("api.latency.p95", start=mid)
    assert all(p.timestamp >= mid for p in sub.points)
    assert len(sub.points) < len(full.points)


# --- events / timeline ----------------------------------------------------

def test_events_are_ordered_and_complete():
    events = ReplayAdapter().get_events()
    assert len(events) >= 6
    # chronologically ordered
    ts = [e.timestamp for e in events]
    assert ts == sorted(ts)
    # the story starts with a deploy
    assert events[0].source == EventSource.DEPLOY
    # contains a rollback and a customer/support signal
    assert any("rollback" in e.title.lower() for e in events)
    assert any(e.source == EventSource.SUPPORT for e in events)


def test_events_filtered_by_start():
    a = ReplayAdapter()
    events = a.get_events()
    start = events[1].timestamp
    filtered = a.get_events(start=start)
    assert filtered
    assert all(e.timestamp >= start for e in filtered)
    assert len(filtered) < len(events)


def test_time_range_covers_events():
    a = ReplayAdapter()
    start, end = a.time_range()
    events = a.get_events()
    assert start <= events[0].timestamp
    assert end >= events[-1].timestamp
