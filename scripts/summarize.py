"""Builds the result tables of results/SUMMARY.md from the raw files of each run.

Reads k6.json, run.json, pg_activity.csv, cloudwatch.json and cold_starts.json in every
results/raw/<run>/ directory and prints Markdown tables. Nothing here is typed by hand:
re-running it on the same raw files gives the same tables.

Usage: python scripts/summarize.py results/raw > /tmp/tables.md
"""

import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

# List prices eu-west-1, on-demand, USD (AWS Pricing API, 2026-10-31; see lab.md section 10).
EVENT_REQ = 0.20 / 1e6
EVENT_GB_S = 0.0000133334
EVENT_MEM_GB = 1024 / 1024
WEB_REQ = 0.30 / 1e6
WEB_VCPU_S = 0.0000291572
WEB_GB_S = 0.0000038603

VARIANTS = ["event-direct", "event-proxy", "web-pool"]


def parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)


def load(run_dir):
    run = json.loads((run_dir / "run.json").read_text())
    metrics = json.loads((run_dir / "k6.json").read_text())["metrics"]
    count = lambda k: metrics.get(k, {}).get("count", 0)
    total = sum(count(k) for k in metrics if k.startswith("status_"))
    start, end = parse(run["start"]), parse(run["end"])
    seconds = (end - start).total_seconds()
    dur = metrics["http_req_duration"]

    # Connections the DB sees with this variant's application_name (RDS Proxy passes it through).
    per_ts = Counter()
    with open(run_dir / "pg_activity.csv") as f:
        for row in csv.DictReader(f):
            if row["application_name"] == f"lab-{run['variant']}":
                per_ts[row["ts"]] += int(row["count"])

    # CloudWatch was pulled with padding; keep only the minutes this run touched,
    # so a neighbouring run on the same resources does not leak into the numbers.
    cw = {}
    cw_file = run_dir / "cloudwatch.json"
    if cw_file.exists():
        lo = start.replace(second=0)
        hi = end.replace(second=0)
        for key, points in json.loads(cw_file.read_text())["metrics"].items():
            cw[key] = [p["value"] for p in points if lo <= parse(p["ts"]) <= hi]

    cold = {}
    cs_file = run_dir / "cold_starts.json"
    if cs_file.exists():
        rows = json.loads(cs_file.read_text())["rows"]
        cold = rows[0] if rows else {"cold_starts": "0"}

    return {
        "run": run, "total": total, "rps": total / seconds if seconds else 0,
        "ok": count("status_200") / total * 100 if total else 0,
        "status": {k[7:]: count(k) for k in metrics if k.startswith("status_") and count(k)},
        "web_errors": {k[10:]: count(k) for k in metrics if k.startswith("web_error_") and count(k)},
        "p50": dur["med"], "p95": dur["p(95)"], "p99": dur["p(99)"],
        "db_app_peak": max(per_ts.values(), default=0), "cw": cw, "cold": cold,
    }


def cw_max(r, prefix):
    vals = [v for k, vs in r["cw"].items() if k.startswith(prefix) for v in vs]
    return max(vals) if vals else None


def cw_sum(r, prefix):
    return sum(v for k, vs in r["cw"].items() if k.startswith(prefix) for v in vs)


def fmt(v, digits=0):
    return "n/a" if v is None else f"{v:,.{digits}f}"


def cost_per_million(r):
    """Lambda cost per million requests, computed from CloudWatch metrics x list price."""
    v = r["run"]["variant"]
    if v == "web-pool":
        reqs = cw_sum(r, "AWS/Lambda/Web|ExecutedRequests|")
        cpu_s = cw_sum(r, "AWS/Lambda/Web|EnvironmentCPUTime|") / 1000
        active_s = cw_sum(r, "AWS/Lambda/Web|EnvironmentActiveTime|") / 1000
        mem_gb = (cw_max(r, "AWS/Lambda/Web|EnvironmentMaxMemoryUsage|") or 0) / 1024
        cost = reqs * WEB_REQ + cpu_s * WEB_VCPU_S + active_s * mem_gb * WEB_GB_S
    else:
        fn = f"lwf-{v}"
        inv_key = f"AWS/Lambda|Invocations|FunctionName={fn}|Sum"
        avg_key = f"AWS/Lambda|Duration|FunctionName={fn}|Average"
        invs, avgs = r["cw"].get(inv_key, []), r["cw"].get(avg_key, [])
        reqs = sum(invs)
        gb_s = sum(i * a / 1000 for i, a in zip(invs, avgs)) * EVENT_MEM_GB
        cost = reqs * EVENT_REQ + gb_s * EVENT_GB_S
    return cost / reqs * 1e6 if reqs else None


def row(r, extra=()):
    run = r["run"]
    aurora = cw_max(r, "AWS/RDS|DatabaseConnections|DBInstanceIdentifier")
    cpu = cw_max(r, "AWS/RDS|CPUUtilization|DBInstanceIdentifier=lwf-aurora-writer|Maximum")
    cells = [
        run["variant"], str(run["vus"]), fmt(r["rps"]), f"{r['ok']:.1f}%",
        fmt(r["p50"]), fmt(r["p95"]), fmt(r["p99"]), str(run["distinct_env_ids"]),
        str(r["db_app_peak"]), fmt(aurora), fmt(cpu), r["cold"].get("cold_starts", "n/a"),
    ]
    return "| " + " | ".join(cells + list(extra)) + " |"


HEADER = ("| variant | VUs | req/s | 200 | p50 ms | p95 ms | p99 ms | envIds | DB conns (app) "
          "| Aurora conns max | Aurora CPU max % | cold starts |")
SEP = "|" + "---|" * 12


def errors(r):
    s = {k: v for k, v in r["status"].items() if k != "200"}
    parts = [f"{k}: {v:,}" for k, v in sorted(s.items())]
    parts += [f"{k}: {v:,}" for k, v in sorted(r["web_errors"].items())]
    return ", ".join(parts) or "none"


def main():
    runs = [load(p.parent) for p in sorted(Path(sys.argv[1]).glob("*/k6.json"))]
    by_label = lambda label: [r for r in runs if r["run"]["label"] == label]

    for delay, name in ((0, "Scenario A (delay_ms 0)"), (100, "Scenario B (delay_ms 100)")):
        print(f"### {name}\n\n{HEADER}\n{SEP}")
        for v in VARIANTS:
            for r in sorted(by_label(""), key=lambda r: r["run"]["vus"]):
                if r["run"]["variant"] == v and r["run"]["delay_ms"] == delay:
                    print(row(r))
        print()

    print("### Non-200 responses per run\n\n| run | errors |\n|---|---|")
    for r in runs:
        if r["ok"] < 100:
            print(f"| {r['run']['run'][17:]} | {errors(r)} |")
    print()

    print(f"### Cold spike (0 -> 500 VUs in 30 s, 2 min at 500, delay_ms 100)\n\n{HEADER} avg init ms |\n{SEP}---|")
    for r in by_label("coldspike"):
        print(row(r, [r["cold"].get("avg_init_ms", "n/a")[:5]]))
    print()

    print("### Pool size (web-pool, 200 VUs, delay_ms 100)\n")
    print("| POOL_MAX | req/s | 200 | p50 ms | p95 ms | p99 ms | envIds | DB conns (app) | max envs (CW) |")
    print("|---|---|---|---|---|---|---|---|---|")
    for n in (5, 10, 20):
        for r in by_label(f"pool{n}"):
            envs = cw_max(r, "AWS/Lambda/Web/Usage|EndpointActiveEnvironments|")
            print(f"| {n} | {fmt(r['rps'])} | {r['ok']:.1f}% | {fmt(r['p50'])} | {fmt(r['p95'])} | "
                  f"{fmt(r['p99'])} | {r['run']['distinct_env_ids']} | {r['db_app_peak']} | {fmt(envs)} |")
    print()

    print("### maxEnvironments as a DB guard (web-pool, 500 VUs, delay_ms 100, POOL_MAX 10)\n")
    print("| cap | req/s | 200 | p50 ms | p95 ms | p99 ms | envIds | DB conns (app) | non-200 |")
    print("|---|---|---|---|---|---|---|---|---|")
    for cap in (20, 2):
        for r in by_label(f"maxenv{cap}"):
            print(f"| {cap} | {fmt(r['rps'])} | {r['ok']:.1f}% | {fmt(r['p50'])} | {fmt(r['p95'])} | "
                  f"{fmt(r['p99'])} | {r['run']['distinct_env_ids']} | {r['db_app_peak']} | {errors(r)} |")
    print()

    print("### Lambda cost per million requests (computed from CloudWatch metrics x list price)\n")
    print("| variant | delay_ms | VUs | USD per 1M requests |\n|---|---|---|---|")
    for r in sorted(by_label(""), key=lambda r: (r["run"]["variant"], r["run"]["delay_ms"], r["run"]["vus"])):
        print(f"| {r['run']['variant']} | {r['run']['delay_ms']} | {r['run']['vus']} | {fmt(cost_per_million(r), 2)} |")


if __name__ == "__main__":
    main()
