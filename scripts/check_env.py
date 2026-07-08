"""Diagnose local .env loading — safely, without ever printing secret values.

Run it from anywhere:  python scripts/check_env.py

It reports where the app looks for .env, whether that file exists and is well
formed, which keys it defines (secret values shown only as <set, len=N> / <EMPTY>),
and what `Settings` actually resolves. Use it when `curl /api/status` shows
`replay` / no creds and you expected live Datadog.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make the repo importable when run as `python scripts/check_env.py`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Values for these keys are NEVER printed — only presence + length.
SECRET_KEYS = {"ANTHROPIC_API_KEY", "DATADOG_ACCESS_TOKEN", "DATADOG_API_KEY", "DATADOG_APP_KEY"}


def _parse(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, _, val = s.partition("=")
        out[key.strip().replace("export ", "").strip()] = val.strip()
    return out


def main() -> int:
    from app import config

    path = config.DOTENV_PATH
    print("=" * 64)
    print(".env diagnostic")
    print("=" * 64)
    print(f"app looks for .env at : {path}")
    print(f"file exists           : {path.exists()}")
    print(f"dotenv reported loaded: {config.DOTENV_LOADED}")

    if path.exists():
        raw = path.read_bytes()
        print(f"size (bytes)          : {len(raw)}")
        print(f"windows line endings  : {b'\r\n' in raw}   (CRLF can confuse some parsers)")
        print(f"byte-order mark (BOM) : {raw[:3] == b'\xef\xbb\xbf'}")
        print("-" * 64)
        print("keys defined in the file (secret values hidden):")
        for k, v in _parse(raw.decode('utf-8-sig', errors='replace')).items():
            if k in SECRET_KEYS:
                shown = f"<set, len={len(v)}>" if v else "<EMPTY — not filled in>"
            else:
                shown = repr(v)
            print(f"  {k:24} = {shown}")
    else:
        print("\n!! No .env at that path. Create one:  cp .env.example .env  (then edit)")

    print("-" * 64)
    s = config.Settings()
    print("what the app RESOLVES right now:")
    print(f"  data_source          : {s.data_source}   (must be 'datadog' for live)")
    print(f"  datadog_configured   : {s.has_datadog}   (needs a PAT or API+APP key)")
    print(f"  anthropic_configured : {s.has_anthropic}")
    print(f"  llm_backend          : {s.llm_backend}")
    print(f"  datadog_tenant_tag   : {s.datadog_tenant_tag}")
    print(f"  datadog_discovery    : {s.datadog_discovery_metric}")
    print(f"  datadog_tls_verify   : {s.datadog_verify!r}"
          + ("  (CA bundle path)" if isinstance(s.datadog_verify, str) else ""))
    print("=" * 64)

    problems = []
    if not path.exists():
        problems.append("no .env file at the expected path")
    if s.data_source != "datadog":
        problems.append("COPILOT_DATA_SOURCE is not 'datadog' (still replay)")
    if not s.has_datadog:
        problems.append("no Datadog credential resolved (token/keys empty or misnamed)")
    if problems:
        print("LIKELY ISSUE(S):")
        for p in problems:
            print(f"  - {p}")
    else:
        print("OK: live Datadog config looks complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
