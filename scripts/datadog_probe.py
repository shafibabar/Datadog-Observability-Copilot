"""Live Datadog probe — validate the connection and see what your org returns.

Run it on the machine that has your Datadog credentials, AFTER editing .env
(COPILOT_DATA_SOURCE=datadog + a token/keys + DATADOG_SITE + DATADOG_TENANT_TAG
+ DATADOG_DISCOVERY_METRIC):

    python scripts/datadog_probe.py

It makes read-only calls and prints, per step: the exact request, the HTTP status,
and a trimmed response so we can confirm auth, the scope-discovery shape, a metric,
and events against YOUR org. It NEVER prints the credential. Paste the output back
and I'll tune app/telemetry/datadog.py to match your org's actual query/response shape.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.config import settings  # noqa: E402
from app.telemetry.datadog import _DEFAULT_METRIC_QUERIES  # noqa: E402


def _trim(obj, n: int = 1600) -> str:
    s = json.dumps(obj, default=str)
    return s if len(s) <= n else s[:n] + f"  …(+{len(s) - n} chars)"


def _headers() -> dict:
    if settings.datadog_access_token:
        return {"Authorization": "Bearer <redacted>"}, {"Authorization": f"Bearer {settings.datadog_access_token}"}
    return (
        {"DD-API-KEY": "<redacted>", "DD-APPLICATION-KEY": "<redacted>"},
        {"DD-API-KEY": settings.datadog_api_key, "DD-APPLICATION-KEY": settings.datadog_app_key},
    )


def _epoch(dt: datetime) -> int:
    return int(dt.timestamp())


def main() -> int:
    print("=" * 70)
    print("Datadog live probe")
    print("=" * 70)
    print(f"data_source        : {settings.data_source}")
    print(f"datadog_configured : {settings.has_datadog}")
    print(f"site               : {settings.datadog_site}")
    print(f"auth mode          : {'PAT (Bearer)' if settings.datadog_access_token else 'API+APP key pair'}")
    print(f"tenant tag         : {settings.datadog_tenant_tag}")
    print(f"discovery metric   : {settings.datadog_discovery_metric}")
    if not settings.has_datadog:
        print("\n!! No Datadog credential resolved. Edit .env and run scripts/check_env.py first.")
        return 1
    if settings.data_source != "datadog":
        print("\n(note) COPILOT_DATA_SOURCE isn't 'datadog' — the app will still use replay, "
              "but this probe will query Datadog anyway.")

    shown_headers, real_headers = _headers()
    base = f"https://api.{settings.datadog_site}"
    client = httpx.Client(base_url=base, headers=real_headers, timeout=15.0)

    now = datetime.now(timezone.utc)
    disc_from, disc_to = _epoch(now - timedelta(hours=4)), _epoch(now)
    tag = settings.datadog_tenant_tag
    metric = settings.datadog_discovery_metric

    steps = [
        ("1. auth (validate)", "GET", "/api/v1/validate", {}),
        ("2. discovery — environments", "GET", "/api/v1/query",
         {"from": disc_from, "to": disc_to, "query": f"{metric}{{*}} by {{env}}"}),
        (f"3. discovery — tenants (tag '{tag}')", "GET", "/api/v1/query",
         {"from": disc_from, "to": disc_to, "query": f"{metric}{{*}} by {{{tag}}}"}),
        ("4. sample golden-signal metric", "GET", "/api/v1/query",
         {"from": disc_from, "to": disc_to, "query": next(iter(_DEFAULT_METRIC_QUERIES.values()))}),
        ("5. events (last hour)", "GET", "/api/v1/events",
         {"start": _epoch(now - timedelta(hours=1)), "end": _epoch(now)}),
        (f"6. tag KEYS on '{metric}' (which tags exist? is there env / a tenant key?)",
         "GET", f"/api/v2/metrics/{metric}/all-tags", {}),
    ]

    for title, method, path, params in steps:
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
            except Exception:
                print(f"  body (text): {resp.text[:400]}")
                continue
            # For query responses, surface the series shape (the bit we tune on).
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
            elif isinstance(body, dict) and isinstance(body.get("data"), dict) \
                    and "tags" in (body["data"].get("attributes") or {}):
                tags = body["data"]["attributes"]["tags"] or []
                keys = sorted({t.split(":", 1)[0] for t in tags if ":" in t})
                print(f"  distinct tag keys ({len(keys)}): {keys}")
                print(f"  has 'env'? {'env' in keys}   has '{tag}'? {tag in keys}")
            else:
                print(f"  body: {_trim(body)}")
        except Exception as exc:  # noqa: BLE001
            print(f"  !! request failed: {type(exc).__name__}: {exc}")

    client.close()
    print("\n" + "=" * 70)
    print("Done. Paste this whole output back (it contains no credentials).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
