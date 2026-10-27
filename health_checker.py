#!/usr/bin/env python3
"""api-health-checker: check the HTTP endpoints you depend on, on a schedule.

Reads a JSON config of endpoints and, for each one, performs a GET request,
measures latency, retries transient failures, and classifies the endpoint as
UP, DEGRADED (slow) or DOWN. Reports as text, JSON or Markdown, and exits
non-zero when anything is DOWN so it plugs into cron, CI or a Docker
HEALTHCHECK.

Standard library only: no dependencies, no installation step.
"""

import argparse
import datetime
import json
import sys
import time
import urllib.error
import urllib.request

UP = "UP"
DEGRADED = "DEGRADED"
DOWN = "DOWN"


def load_config(path):
    """Return (defaults, endpoints) from a JSON config file."""
    with open(path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    defaults = cfg.get("defaults", {}) or {}
    endpoints = cfg.get("endpoints", []) or []
    if not endpoints:
        raise ValueError("config has no endpoints")
    return defaults, endpoints


def _friendly_error(exc):
    if isinstance(exc, urllib.error.URLError) and hasattr(exc, "reason"):
        return str(exc.reason)
    return str(exc)


def check_endpoint(endpoint, defaults):
    """Check one endpoint. Returns a result dict."""
    name = endpoint.get("name") or endpoint.get("url", "?")
    url = endpoint["url"]
    expected = set(endpoint.get("expected_status", defaults.get("expected_status", [200])))
    timeout = endpoint.get("timeout", defaults.get("timeout", 10))
    warn_ms = endpoint.get("warn_latency_ms", defaults.get("warn_latency_ms", 1000))
    max_attempts = 1 + endpoint.get("retries", defaults.get("retries", 1))
    headers = endpoint.get("headers", {}) or {}

    result = {
        "name": name,
        "url": url,
        "expected_status": sorted(expected),
        "warn_latency_ms": warn_ms,
        "attempts": 0,
        "got": None,
        "latency_ms": None,
        "error": None,
        "status": DOWN,
    }

    for _ in range(max_attempts):
        result["attempts"] += 1
        req = urllib.request.Request(url, headers=headers)
        start = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result["latency_ms"] = round((time.perf_counter() - start) * 1000, 1)
                result["got"] = resp.status
                result["error"] = None
        except urllib.error.HTTPError as exc:
            result["latency_ms"] = round((time.perf_counter() - start) * 1000, 1)
            result["got"] = exc.code
            result["error"] = "HTTP %d" % exc.code
        except Exception as exc:  # URLError, timeouts, DNS failures...
            result["got"] = None
            result["latency_ms"] = None
            result["error"] = _friendly_error(exc)
        if result["got"] in expected:
            break  # success, no need to retry

    if result["got"] in expected:
        if result["latency_ms"] is not None and result["latency_ms"] > warn_ms:
            result["status"] = DEGRADED
        else:
            result["status"] = UP
    else:
        result["status"] = DOWN
    return result


def run_checks(defaults, endpoints):
    return [check_endpoint(ep, defaults) for ep in endpoints]


def build_report(results):
    summary = {UP: 0, DEGRADED: 0, DOWN: 0}
    findings = []
    for res in results:
        summary[res["status"]] += 1
        if res["status"] == DOWN:
            if res["error"] and res["got"] is not None:
                detail = "%s (expected %s)" % (res["error"], ",".join(map(str, res["expected_status"])))
            elif res["error"]:
                detail = res["error"]
            else:
                detail = "unexpected status"
            findings.append("DOWN: %s — %s" % (res["name"], detail))
        elif res["status"] == DEGRADED:
            findings.append(
                "DEGRADED: %s — %.1fms exceeds %dms warning threshold"
                % (res["name"], res["latency_ms"], res["warn_latency_ms"])
            )
    return {
        "timestamp": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "summary": summary,
        "total": len(results),
        "results": results,
        "findings": findings,
    }


def _status_line(res):
    latency = "%.1fms" % res["latency_ms"] if res["latency_ms"] is not None else "n/a"
    got = str(res["got"]) if res["got"] is not None else "-"
    attempt_word = "attempt" if res["attempts"] == 1 else "attempts"
    detail = ""
    if res["status"] == DOWN and res["error"]:
        detail = " — %s, expected %s" % (res["error"], ",".join(map(str, res["expected_status"])))
    return "  %-8s %-22s %3s %8s  (%d %s)%s" % (
        res["status"], res["name"][:22], got, latency, res["attempts"], attempt_word, detail
    )


def format_text(report):
    lines = ["api-health-checker — %s" % report["timestamp"]]
    for res in report["results"]:
        lines.append(_status_line(res))
    s = report["summary"]
    lines.append(
        "Summary: %d up, %d degraded, %d down of %d endpoints"
        % (s[UP], s[DEGRADED], s[DOWN], report["total"])
    )
    if report["findings"]:
        lines.append("Findings:")
        lines.extend("  - %s" % f for f in report["findings"])
    return "\n".join(lines)


def format_markdown(report):
    s = report["summary"]
    lines = [
        "# api-health-checker",
        "",
        "Run at `%s`." % report["timestamp"],
        "",
        "| endpoint | status | http | latency | attempts |",
        "|---|---|---|---|---|",
    ]
    for res in report["results"]:
        latency = "%.1fms" % res["latency_ms"] if res["latency_ms"] is not None else "n/a"
        got = str(res["got"]) if res["got"] is not None else "-"
        lines.append(
            "| %s | %s | %s | %s | %d |"
            % (res["name"], res["status"], got, latency, res["attempts"])
        )
    lines.append("")
    lines.append(
        "**Summary:** %d up, %d degraded, %d down of %d endpoints."
        % (s[UP], s[DEGRADED], s[DOWN], report["total"])
    )
    if report["findings"]:
        lines.append("")
        lines.append("## Findings")
        lines.extend("- %s" % f for f in report["findings"])
    return "\n".join(lines)


def format_json(report):
    return json.dumps(report, indent=2)


def overall_exit_code(results):
    """Non-zero when anything is DOWN (degraded is a warning, not a failure)."""
    return 1 if any(res["status"] == DOWN for res in results) else 0


def parse_args(argv):
    ap = argparse.ArgumentParser(description="Check HTTP endpoint health on a schedule.")
    ap.add_argument("--config", default="endpoints.json", help="JSON config file (default: endpoints.json)")
    ap.add_argument("--json", action="store_true", help="JSON output")
    ap.add_argument("--markdown", action="store_true", help="Markdown output")
    ap.add_argument("--output", help="Write the report to this file instead of stdout")
    ap.add_argument("--interval", type=int, default=0,
                    help="Run every N seconds instead of once (monitoring mode)")
    return ap.parse_args(argv)


def run_once(defaults, endpoints, args):
    report = build_report(run_checks(defaults, endpoints))
    if args.json:
        text = format_json(report)
    elif args.markdown:
        text = format_markdown(report)
    else:
        text = format_text(report)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    else:
        print(text)
    return overall_exit_code(report["results"])


def main(argv=None):
    args = parse_args(argv or sys.argv[1:])
    try:
        defaults, endpoints = load_config(args.config)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print("config error: %s" % exc, file=sys.stderr)
        return 2
    if args.interval and args.interval > 0:
        try:
            while True:
                stamp = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
                print("--- cycle at %s ---" % stamp, flush=True)
                run_once(defaults, endpoints, args)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            return 0
    return run_once(defaults, endpoints, args)


if __name__ == "__main__":
    sys.exit(main())
