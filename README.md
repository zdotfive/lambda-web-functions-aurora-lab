# Lambda Web Functions in front of Aurora: do you still need RDS Proxy?

A lab that puts the same Node.js 24 service in front of Aurora PostgreSQL in three ways and measures what the database sees under load:

| Variant | Compute | Database connection |
|---|---|---|
| `event-direct` | Lambda Event Function + Function URL | one `pg.Client` per environment, reused |
| `event-proxy` | same function | same code, host is an RDS Proxy endpoint |
| `web-pool` | Lambda Web Function (Express) | one `pg.Pool` shared by the environment |

Region: `eu-west-1`. Infrastructure: AWS CDK (Python, L1 constructs). Load: k6 from an EC2 instance in the same region.

Status: work in progress. Results will be in [`results/SUMMARY.md`](results/SUMMARY.md), each number linked to the raw file it comes from.
