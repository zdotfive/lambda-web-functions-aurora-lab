# Lambda Web Functions in front of Aurora: do you still need RDS Proxy?

A lab that puts the same Node.js 24 service in front of Aurora PostgreSQL in three ways and measures what the database sees under load:

| Variant | Compute | Database connection |
|---|---|---|
| `event-direct` | Lambda Event Function + Function URL | one `pg.Client` per environment, reused |
| `event-proxy` | same function | same code, host is an RDS Proxy endpoint |
| `web-pool` | Lambda Web Function (Express) | one `pg.Pool` shared by the environment |

Region: `eu-west-1`. Infrastructure: AWS CDK (Python, L1 constructs for the Web Function resources). Load: k6 from an EC2 instance in the same VPC.

## Results

Full tables, method and limits: [`results/SUMMARY.md`](results/SUMMARY.md). Raw files for every run: [`results/raw/`](results/raw/).

Headline numbers at 500 virtual users, 100 ms of work while holding the connection (`db.t4g.medium`, `max_connections` 401):

| | environments | DB connections | HTTP 200 | p99 |
|---|---|---|---|---|
| `event-direct` | 283 | 284 | 97.1% | 5,016 ms |
| `event-proxy` | 563 | 390 (held by the proxy) | 99.9% | 1,298 ms |
| `web-pool` (`POOL_MAX` 10) | 12 | 120 | 100.0% | 820 ms |

The Web Function keeps database connections at environments × pool size. In exchange the pool becomes the limit: at 200 users its median latency was 465 ms, against 134 ms for `event-direct`. Doubling `POOL_MAX` from 10 to 20 nearly doubled throughput.

## Layout

```
app/        shared query code, Event Function handler, Web Function (Express) server
infra/      CDK app: LwfNetwork (VPC, loadgen), LwfData (Aurora, RDS Proxy), LwfApp (functions)
load/       k6 script and the load matrix
scripts/    seed, smoke test, orchestration, metrics, summary, leftover check
results/    SUMMARY.md and raw/ (one directory per run)
lab.md      working notes (Italian): docs findings, prices, every problem met
```

## Running it

It creates billable resources: Aurora, RDS Proxy, an interface VPC endpoint, an EC2 instance and Lambda. Deploy takes about 22 minutes (Aurora and the proxy most of it), the seed about 3, the load runs about 3 hours.

```bash
make venv app                 # Python venv for CDK, npm install, app bundle
make deploy                   # three stacks
make shell                    # SSM session on the loadgen, then inside it:
#   git clone <this repo> lab && cd lab
#   make env seed smoke       # .env from stack outputs, 1M customers / 5M orders, same JSON from all variants
scripts/orchestrate.sh        # from the laptop: the matrix, one variant at a time
scripts/extras.sh             # from the laptop: cold spike, pool size, maxEnvironments
make pull-results metrics     # raw files from S3, CloudWatch metrics per run
python scripts/summarize.py results/raw
make destroy leftovers        # destroy, then check that nothing with the lab prefix is left
```

The laptop runs the orchestration. Keep it on power: on battery macOS sleeps even under `caffeinate`, and the runs stall.
