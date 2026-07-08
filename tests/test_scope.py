"""Spec for the Scope value object (app/telemetry/models.Scope).

Scope is the investigation lens: which environments/tenants to look at and over
what time window. It is persisted per conversation and validated before it ever
reaches the (token-spending) reasoning path. Pure — no I/O.
"""
from datetime import datetime, timedelta, timezone

from app.telemetry.models import MAX_SCOPE_DAYS, Scope

_T0 = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)


def _scope(**kw):
    base = dict(environments=["production"], tenants=[], start=_T0, end=_T0 + timedelta(hours=1))
    base.update(kw)
    return Scope(**base)


def test_defaults_are_empty():
    s = Scope()
    assert s.environments == [] and s.tenants == []
    assert s.start is None and s.end is None
    assert s.has_selection() is False


def test_has_selection_true_with_env_or_tenant():
    assert Scope(environments=["prod"]).has_selection() is True
    assert Scope(tenants=["acme"]).has_selection() is True


def test_valid_scope_has_no_error():
    assert _scope().validation_error() is None


def test_requires_at_least_one_env_or_tenant():
    err = _scope(environments=[], tenants=[]).validation_error()
    assert err and "environment or tenant" in err


def test_requires_a_duration():
    assert _scope(start=None, end=None).validation_error() is not None
    assert _scope(end=None).validation_error() is not None


def test_rejects_end_before_start():
    err = _scope(start=_T0, end=_T0 - timedelta(hours=1)).validation_error()
    assert err is not None


def test_rejects_span_over_seven_days():
    err = _scope(start=_T0, end=_T0 + timedelta(days=MAX_SCOPE_DAYS, seconds=1)).validation_error()
    assert err and "7" in err


def test_accepts_exactly_seven_days():
    assert _scope(start=_T0, end=_T0 + timedelta(days=MAX_SCOPE_DAYS)).validation_error() is None


def test_max_days_is_seven():
    assert MAX_SCOPE_DAYS == 7


def test_round_trips_through_json():
    s = _scope(environments=["prod", "staging"], tenants=["acme"])
    assert Scope.model_validate_json(s.model_dump_json()) == s
