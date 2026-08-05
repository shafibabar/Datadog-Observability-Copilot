"""Live Datadog probe — validate the connection and see what your org returns.

Run it on the machine that has your Datadog credentials, AFTER editing .env
(COPILOT_DATA_SOURCE=datadog + a token/keys + DATADOG_SITE + DATADOG_TENANT_TAG
+ DATADOG_METRIC_NAMESPACES):

    python scripts/datadog_probe.py

It makes read-only calls and prints, per step: the exact request, the HTTP status,
and a trimmed response so we can confirm auth, metric-name discovery, the
scope-discovery shape, a metric, and events against YOUR org. It NEVER prints the
credential. Paste the output back and I'll tune app/telemetry/datadog.py to match
your org's actual query/response shape.

Step 2 (metric-name discovery) runs before the metric/tag steps on purpose: those
steps are only meaningful against a metric that is *actually reporting*, and an
inactive metric makes them silently return zero series.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.config import settings  # noqa: E402
from app.monitors.index import build_monitors_index  # noqa: E402
from app.telemetry.datadog import _DEFAULT_METRIC_QUERIES  # noqa: E402
from app.telemetry.namespaces import matches, parse_patterns  # noqa: E402

# Datadog auto-generates these sub-metrics for every distribution/histogram, so one
# logical metric shows up as several names. Reported separately because they inflate
# the in-scope count and crowd out distinct signals in the resolver's top-K.
_STAT_SUFFIXES = (
    ".count", ".sum", ".min", ".max", ".avg", ".median",
    ".95percentile", ".99percentile", ".75percentile", ".90percentile",
)


def _trim(obj, n: int = 1600) -> str:
    s = json.dumps(obj, default=str)
    return s if len(s) <= n else s[:n] + f"  …(+{len(s) - n} chars)"


def _headers() -> tuple[dict, dict]:
    if settings.datadog_access_token:
        return ({"Authorization": "Bearer <redacted>"},
                {"Authorization": f"Bearer {settings.datadog_access_token}"})
    return (
        {"DD-API-KEY": "<redacted>", "DD-APPLICATION-KEY": "<redacted>"},
        {"DD-API-KEY": settings.datadog_api_key, "DD-APPLICATION-KEY": settings.datadog_app_key},
    )


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def _is_stat_submetric(name: str) -> bool:
    return name.endswith(_STAT_SUFFIXES)


def _terraform_metrics(s) -> list[str]:
    """Metric names the local Terraform monitors repo references, if configured."""
    if not s.monitors_repo_path:
        return []
    index = build_monitors_index(s.monitors_repo_path, namespaces=s.datadog_metric_namespaces)
    return sorted(index.metric_queries)


def _sample_metric(s) -> str:
    return next(iter(_terraform_metrics(s)), "")


def _in_scope_names(body, namespaces) -> list[str]:
    if not isinstance(body, dict) or not isinstance(body.get("metrics"), list):
        return []
    return sorted(
        n for n in body["metrics"] if isinstance(n, str) and matches(n, namespaces))


def _first_base_metric(live: list[str]) -> str:
    """A live metric that isn't a statistical sub-metric — the best probe target."""
    return next((n for n in live if not _is_stat_submetric(n)), "")


def _registry_analysis(live: list[str], s, namespaces) -> list[str]:
    """The two questions the raw counts don't answer: how many in-scope names are
    real distinct signals, and do the Terraform-referenced metrics still exist?

    Returns the Terraform metrics confirmed present in the live list — the best
    survey candidates, since a monitor alerts on them.
    """
    if not live:
        print("\n  (no in-scope metric names returned — nothing to analyse)")
        return []
    base = [n for n in live if not _is_stat_submetric(n)]
    print("\n  --- registry analysis ---")
    print(f"  in scope total          : {len(live)}")
    print(f"  distinct base metrics   : {len(base)}")
    print(f"  statistical sub-metrics : {len(live) - len(base)}"
          "   (.count/.sum/.min/.max/… auto-generated per distribution)")
    services = sorted({n.split(".")[1] for n in base if len(n.split(".")) > 1})
    print(f"  services represented    : {len(services)}")
    print(f"  first 12 services       : {services[:12]}")

    tf = _terraform_metrics(s)
    if not tf:
        print("  terraform cross-check   : MONITORS_REPO_PATH not set — skipped")
        return []
    live_set = set(live)
    confirmed = [m for m in tf if m in live_set]
    missing = [m for m in tf if m not in live_set]
    print(f"  terraform metrics       : {len(tf)} extracted")
    print(f"    confirmed in live list: {len(confirmed)}")
    print(f"    NOT in live list      : {len(missing)}"
          "   (in the .tf files but absent from live discovery)")
    if missing:
        print(f"    first 5 not in list   : {missing[:5]}")
    return confirmed


def _series_of(client, query: str, frm: int, to: int) -> tuple[int, list]:
    """Run one timeseries query quietly. Returns (http_status, series list)."""
    try:
        resp = client.get("/api/v1/query", params={"from": frm, "to": to, "query": query})
        if resp.status_code != 200:
            return resp.status_code, []
        body = resp.json()
        return 200, (body.get("series") or []) if isinstance(body, dict) else []
    except Exception:  # noqa: BLE001
        return -1, []


def _points(series: list) -> int:
    return sum(len([p for p in (s.get("pointlist") or []) if p and p[1] is not None])
               for s in series)


def _survey(client, candidates: list[str], frm: int, to: int) -> tuple[str, str]:
    """Query several metrics in several forms over a long window.

    One metric returning nothing proves nothing — it may simply be idle. Surveying
    a spread of metrics, each with the aggregations Datadog needs for different
    metric types, distinguishes "this platform isn't emitting right now" from
    "we're querying it wrong". Returns the first (metric, query) that had data.
    """
    print("\n" + "-" * 70)
    print(f"8. data survey — {len(candidates)} metrics x 3 query forms over the window")
    print("   (a metric can be in the active-metrics list yet have no points in a window)")
    winner = ("", "")
    for metric in candidates:
        results = []
        for form in (f"avg:{metric}{{*}}", f"sum:{metric}{{*}}.as_count()", f"max:{metric}{{*}}"):
            status, series = _series_of(client, form, frm, to)
            n = _points(series)
            results.append(f"{form.split(':', 1)[0]}={'ERR' if status != 200 else f'{len(series)}s/{n}p'}")
            if n and not winner[0]:
                winner = (metric, form)
        print(f"  {metric}\n      {'  '.join(results)}")
    print(f"\n  --> first metric WITH data: {winner[0] or '(none had data)'}")
    return winner


def _tag_survey(client, metric: str, query: str, tag: str, frm: int, to: int) -> None:
    """Group a metric KNOWN to have data by candidate tag keys, and report the tag
    keys actually present. This is what settles DATADOG_TENANT_TAG."""
    print("\n" + "-" * 70)
    print(f"9. tag keys on a metric that HAS data ('{metric}')")
    if not metric:
        print("  skipped — no metric returned data, so grouping proves nothing")
        return
    status, series = _series_of(client, query, frm, to)
    print(f"  ungrouped scope values: {[s.get('scope') for s in series[:3]]}")
    # dict.fromkeys dedupes while keeping order (tag may already be in the list).
    candidates = dict.fromkeys(
        [settings.datadog_env_tag, tag, "env", "kube_namespace", "service", "host",
         "environment", "tenant"])
    for key in candidates:
        status, series = _series_of(client, f"{query} by {{{key}}}", frm, to)
        seen = sorted({t for s in series for t in (s.get("tag_set") or [])})[:6]
        print(f"  by {{{key}}}".ljust(26) + f"-> {len(series)} series  tag_set sample: {seen}")


def _submetric_check(client, live: list[str], frm: int, to: int) -> None:
    """Does the BASE name of a histogram-style metric return data, or only its
    generated .count/.sum siblings? This decides whether excluding sub-metrics from
    the registry is safe or actively removes the only queryable names."""
    print("\n" + "-" * 70)
    print("10. base metric vs generated sub-metric (validates the sub-metric filter)")
    live_set = set(live)
    base = next((n for n in live if not _is_stat_submetric(n)
                 and f"{n}.count" in live_set and f"{n}.sum" in live_set), "")
    if not base:
        print("  no base metric with .count/.sum siblings found in the live list — skipped")
        return
    for name in (base, f"{base}.count", f"{base}.sum", f"{base}.max"):
        status, series = _series_of(client, f"avg:{name}{{*}}", frm, to)
        print(f"  avg:{name}{{*}}\n      -> {'ERR' if status != 200 else f'{len(series)} series / {_points(series)} points'}")
    print("  If the BASE has no data but .count/.sum do, the sub-metric filter must be")
    print("  revisited — those siblings would be the only queryable names.")


def _summarize(body, namespaces, tag) -> None:
    """Print the parts of a response we actually tune the adapter on."""
    if isinstance(body, dict) and "series" in body:
        series = body.get("series") or []
        print(f"  series count: {len(series)}")
        if series:
            first = series[0]
            print(f"  first series keys: {sorted(first.keys())}")
            for k in ("scope", "tag_set", "expression", "metric", "unit"):
                if k in first:
                    print(f"    {k}: {_trim(first[k], 300)}")
            pts = first.get("pointlist") or []
            print(f"    pointlist length: {len(pts)}")
    elif isinstance(body, dict) and "events" in body:
        events = body.get("events") or []
        print(f"  event count: {len(events)}")
        if events:
            print(f"  first event keys: {sorted(events[0].keys())}")
    elif isinstance(body, dict) and isinstance(body.get("metrics"), list):
        names = [n for n in body["metrics"] if isinstance(n, str)]
        in_scope = _in_scope_names(body, namespaces)
        print(f"  metric names returned: {len(names)}")
        print(f"  in scope for {list(namespaces) or '(no filter)'}: {len(in_scope)}")
        print(f"  first 15 in scope: {in_scope[:15]}")
        heads = sorted({n.split(".", 1)[0] for n in names})
        print(f"  namespaces present in the org ({len(heads)}): {heads[:40]}")
    elif isinstance(body, dict) and isinstance(body.get("data"), dict) \
            and "tags" in (body["data"].get("attributes") or {}):
        tags = body["data"]["attributes"]["tags"] or []
        keys = sorted({t.split(":", 1)[0] for t in tags if ":" in t})
        print(f"  distinct tag keys ({len(keys)}): {keys}")
        print(f"  has 'env'? {'env' in keys}   has '{tag}'? {tag in keys}")
    else:
        print(f"  body: {_trim(body)}")


def main() -> int:
    print("=" * 70)
    print("Datadog live probe")
    print("=" * 70)
    print(f"data_source        : {settings.data_source}")
    print(f"datadog_configured : {settings.has_datadog}")
    print(f"site               : {settings.datadog_site}")
    print(f"auth mode          : {'PAT (Bearer)' if settings.datadog_access_token else 'API+APP key pair'}")
    print(f"env tag            : {settings.datadog_env_tag}")
    print(f"tenant tag         : {settings.datadog_tenant_tag}")
    print(f"metric namespaces  : {list(settings.datadog_metric_namespaces)}")
    if not settings.has_datadog:
        print("\n!! No Datadog credential resolved. Edit .env and run scripts/check_env.py first.")
        return 1
    if settings.data_source != "datadog":
        print("\n(note) COPILOT_DATA_SOURCE isn't 'datadog' — the app will still use replay, "
              "but this probe will query Datadog anyway.")

    shown_headers, real_headers = _headers()
    base = f"https://api.{settings.datadog_site}"
    verify = settings.datadog_verify
    print(f"tls verify         : {verify!r}"
          + ("  (CA bundle)" if isinstance(verify, str) else ""))
    client = httpx.Client(base_url=base, headers=real_headers, timeout=15.0, verify=verify)

    now = datetime.now(timezone.utc)
    disc_from, disc_to = _epoch(now - timedelta(hours=4)), _epoch(now)
    tag = settings.datadog_tenant_tag
    namespaces = parse_patterns(settings.datadog_metric_namespaces)

    def probe(title: str, method: str, path: str, params: dict):
        """Run one read-only call, print request + shape summary, return the body."""
        print("\n" + "-" * 70)
        print(title)
        print(f"  {method} {base}{path}")
        if params:
            print(f"  params: { {k: v for k, v in params.items()} }")
        print(f"  headers: {shown_headers}")
        try:
            resp = client.request(method, path, params=params)
            print(f"  -> HTTP {resp.status_code}")
            try:
                body = resp.json()
            except Exception:  # noqa: BLE001
                print(f"  body (text): {resp.text[:400]}")
                return None
            _summarize(body, namespaces, tag)
            return body
        except Exception as exc:  # noqa: BLE001
            print(f"  !! request failed: {type(exc).__name__}: {exc}")
            return None

    # /api/v1/validate only accepts an API key, so a PAT gets 403 here — harmless;
    # the 200s on the query steps below are the real proof the PAT works.
    probe("1. auth (validate — API-key only; 403 with a PAT is expected)",
          "GET", "/api/v1/validate", {})

    # Runs first so every later step can target a metric we KNOW is reporting.
    body = probe(
        f"2. metric-name discovery (active metrics; will be filtered to {list(namespaces)})",
        "GET", "/api/v1/metrics", {"from": _epoch(now - timedelta(hours=24))})
    live = _in_scope_names(body, namespaces)
    confirmed = _registry_analysis(live, settings, namespaces)

    metric = (_first_base_metric(live) or _sample_metric(settings)
              or next(iter(_DEFAULT_METRIC_QUERIES)))
    origin = ("live-discovered" if metric in set(live)
              else "NOT confirmed live — empty series below prove nothing")
    print(f"\n>>> probing tags/queries against '{metric}'  ({origin})")

    probe(f"3. discovery — environments (grouping '{metric}')", "GET", "/api/v1/query",
          {"from": disc_from, "to": disc_to, "query": f"{metric}{{*}} by {{env}}"})
    probe(f"4. discovery — tenants (tag '{tag}')", "GET", "/api/v1/query",
          {"from": disc_from, "to": disc_to, "query": f"{metric}{{*}} by {{{tag}}}"})
    probe(f"5. sample in-scope metric '{metric}'", "GET", "/api/v1/query",
          {"from": disc_from, "to": disc_to, "query": f"avg:{metric}{{*}}"})
    probe("6. events (last hour)", "GET", "/api/v1/events",
          {"start": _epoch(now - timedelta(hours=1)), "end": _epoch(now)})
    probe(f"7. tag KEYS on '{metric}' (is there env / a tenant key?)",
          "GET", f"/api/v2/metrics/{metric}/all-tags", {})

    # A single metric with no points in a 4h window is not evidence of anything.
    # Steps 8-10 widen to 7 days (the Scope max) and across several metrics and
    # query forms, to separate "not emitting" from "queried the wrong way".
    wide_from = _epoch(now - timedelta(days=7))
    base_live = [n for n in live if not _is_stat_submetric(n)]
    candidates = (confirmed or base_live)[:8]
    hit_metric, hit_query = _survey(client, candidates, wide_from, disc_to)
    _tag_survey(client, hit_metric, hit_query or f"avg:{metric}{{*}}", tag, wide_from, disc_to)
    _submetric_check(client, live, wide_from, disc_to)

    client.close()
    print("\n" + "=" * 70)
    print("Done. Paste this whole output back (it contains no credentials).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
