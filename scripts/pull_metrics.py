"""Downloads CloudWatch metrics (1-minute granularity) for every run under results/raw/.

For each results/raw/<run>/run.json, writes results/raw/<run>/cloudwatch.json and
cold_starts.json (Event Functions: REPORT lines with Init Duration; Web Function: platform.initReport).

Usage: python scripts/pull_metrics.py results/raw [--force]
"""

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3

REGION = "eu-west-1"
CLUSTER = "lwf-aurora"
WRITER = "lwf-aurora-writer"
PROXY = "lwf-proxy"
EVENT_FUNCTIONS = {"event-direct": "lwf-event-direct", "event-proxy": "lwf-event-proxy"}
WEB_FUNCTION = "lwf-web-pool"

# (namespace, metric, dimensions, statistics)
AURORA = [
    ("AWS/RDS", "DatabaseConnections", {"DBInstanceIdentifier": WRITER}, ["Maximum", "Average"]),
    ("AWS/RDS", "CPUUtilization", {"DBInstanceIdentifier": WRITER}, ["Maximum", "Average"]),
    ("AWS/RDS", "FreeableMemory", {"DBInstanceIdentifier": WRITER}, ["Minimum"]),
]
PROXY_METRICS = [
    ("AWS/RDS", "ClientConnections", {"ProxyName": PROXY}, ["Maximum", "Sum"]),
    ("AWS/RDS", "DatabaseConnections", {"ProxyName": PROXY}, ["Maximum"]),
    ("AWS/RDS", "QueryRequests", {"ProxyName": PROXY}, ["Sum"]),
]


def event_metrics(fn):
    dims = {"FunctionName": fn}
    return [
        ("AWS/Lambda", "ConcurrentExecutions", dims, ["Maximum"]),
        ("AWS/Lambda", "Invocations", dims, ["Sum"]),
        ("AWS/Lambda", "Errors", dims, ["Sum"]),
        ("AWS/Lambda", "Throttles", dims, ["Sum"]),
        ("AWS/Lambda", "Duration", dims, ["Average", "Maximum"]),
    ]


# AWS/Lambda/Web has no latency metric and no revision dimension; latency comes from k6.
WEB_ENDPOINT = "main"
_fn = {"FunctionName": WEB_FUNCTION}
_fn_ep = {"FunctionName": WEB_FUNCTION, "EndpointName": WEB_ENDPOINT}
_usage = {**_fn_ep, "ExecutionRegion": REGION}
WEB_METRICS = [
    ("AWS/Lambda/Web", "ExecutedRequests", _fn_ep, ["Sum"]),
    ("AWS/Lambda/Web", "HTTPResponseStatusClass4XX", _fn_ep, ["Sum"]),
    ("AWS/Lambda/Web", "HTTPResponseStatusClass5XX", _fn_ep, ["Sum"]),
    ("AWS/Lambda/Web", "EnvironmentActiveTime", _fn, ["Sum"]),
    ("AWS/Lambda/Web", "EnvironmentCPUTime", _fn, ["Sum"]),
    ("AWS/Lambda/Web", "EnvironmentMaxMemoryUsage", _fn, ["Maximum"]),
    ("AWS/Lambda/Web", "EnvironmentConcurrentRequests", _fn, ["Maximum", "Average"]),
    ("AWS/Lambda/Web/Usage", "EndpointActiveEnvironments", _usage, ["Maximum"]),
    ("AWS/Lambda/Web/Usage", "EndpointRequestThrottles", _usage, ["Sum"]),
    ("AWS/Lambda/Web/Usage", "AccountRequestThrottles", _usage, ["Sum"]),
    ("AWS/Lambda/Web/Usage", "AccountActiveVCPUArm64Throttles", _usage, ["Sum"]),
    ("AWS/Lambda/Web/Usage", "EndpointActiveEnvironmentThrottles", _usage, ["Sum"]),
]


def metric_queries(specs):
    queries = []
    for i, (ns, name, dims, stats) in enumerate(specs):
        for stat in stats:
            queries.append(
                {
                    "Id": f"m{i}_{stat.lower()}",
                    "Label": f"{ns}|{name}|{','.join(f'{k}={v}' for k, v in dims.items())}|{stat}",
                    "MetricStat": {
                        "Metric": {
                            "Namespace": ns,
                            "MetricName": name,
                            "Dimensions": [{"Name": k, "Value": v} for k, v in dims.items()],
                        },
                        "Period": 60,
                        "Stat": stat,
                    },
                    "ReturnData": True,
                }
            )
    return queries


def fetch(cw, specs, start, end):
    queries = metric_queries(specs)
    out = {}
    for i in range(0, len(queries), 500):
        kwargs = {"MetricDataQueries": queries[i : i + 500], "StartTime": start, "EndTime": end}
        while True:
            res = cw.get_metric_data(**kwargs)
            for r in res["MetricDataResults"]:
                series = out.setdefault(r["Label"], [])
                series.extend(
                    {"ts": t.isoformat(), "value": v} for t, v in zip(r["Timestamps"], r["Values"])
                )
            if "NextToken" not in res:
                break
            kwargs["NextToken"] = res["NextToken"]
    for series in out.values():
        series.sort(key=lambda p: p["ts"])
    return out


EVENT_COLD_STARTS = (
    "filter @type = 'REPORT' and ispresent(@initDuration) "
    "| stats count() as cold_starts, avg(@initDuration) as avg_init_ms, max(@initDuration) as max_init_ms"
)
# Web Functions log one platform.initReport per new environment (seen in the CLI spike).
WEB_COLD_STARTS = (
    "filter type = 'platform.initReport' "
    "| stats count() as cold_starts, avg(record.metrics.totalDurationMs) as avg_init_ms, "
    "max(record.metrics.totalDurationMs) as max_init_ms"
)


def cold_starts(logs, log_group, query, start, end):
    qid = logs.start_query(
        logGroupName=log_group,
        startTime=int(start.timestamp()),
        endTime=int(end.timestamp()),
        queryString=query,
    )["queryId"]
    while True:
        res = logs.get_query_results(queryId=qid)
        if res["status"] in ("Complete", "Failed", "Cancelled", "Timeout"):
            break
        time.sleep(1)
    rows = [{f["field"]: f["value"] for f in row} for row in res.get("results", [])]
    return {"status": res["status"], "rows": rows}


def main():
    root = Path(sys.argv[1])
    force = "--force" in sys.argv
    cw = boto3.client("cloudwatch", region_name=REGION)
    logs = boto3.client("logs", region_name=REGION)

    for run_file in sorted(root.glob("*/run.json")):
        out_dir = run_file.parent
        if (out_dir / "cloudwatch.json").exists() and not force:
            continue
        run = json.loads(run_file.read_text())
        parse = lambda s: datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        # Align to whole minutes so the first and last partial minutes are included.
        start = parse(run["start"]).replace(second=0) - timedelta(minutes=1)
        end = parse(run["end"]).replace(second=0) + timedelta(minutes=2)

        specs = list(AURORA)
        variant = run["variant"]
        if variant in EVENT_FUNCTIONS:
            specs += event_metrics(EVENT_FUNCTIONS[variant])
        if variant == "event-proxy":
            specs += PROXY_METRICS
        if variant == "web-pool":
            specs += WEB_METRICS

        data = {"run": run["run"], "start": start.isoformat(), "end": end.isoformat(),
                "metrics": fetch(cw, specs, start, end)}
        (out_dir / "cloudwatch.json").write_text(json.dumps(data, indent=1))

        # Exact run window: the padded one would overlap the next run on the same function.
        if variant in EVENT_FUNCTIONS:
            log_group, query = f"/aws/lambda/{EVENT_FUNCTIONS[variant]}", EVENT_COLD_STARTS
        else:
            log_group, query = f"/aws/lambda/web/{WEB_FUNCTION}", WEB_COLD_STARTS
        cs = cold_starts(logs, log_group, query, parse(run["start"]), parse(run["end"]))
        (out_dir / "cold_starts.json").write_text(json.dumps(cs, indent=1))
        print(f"{run['run']}: {len(data['metrics'])} series")


if __name__ == "__main__":
    main()
