// Shared by all three variants: same query, same driver, same connection settings.
import { readFileSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import { SecretsManagerClient, GetSecretValueCommand } from '@aws-sdk/client-secrets-manager';

// One id per execution environment, used to count environments from the responses.
export const envId = randomUUID();
export const variant = process.env.VARIANT;

const RDS_CA = readFileSync(new URL('../certs/rds-global-bundle.pem', import.meta.url), 'utf8');

export const CUSTOMER_SQL = `
SELECT c.id, c.name, c.email, c.country, c.created_at,
       COALESCE(o.recent_orders, '[]'::json) AS recent_orders
FROM customers c
LEFT JOIN LATERAL (
  SELECT json_agg(json_build_object('id', x.id, 'amount', x.amount, 'status', x.status,
                                    'created_at', x.created_at)
                  ORDER BY x.created_at DESC) AS recent_orders
  FROM (SELECT id, amount, status, created_at
        FROM orders
        WHERE customer_id = c.id AND created_at > now() - interval '90 days'
        ORDER BY created_at DESC
        LIMIT 20) x
) o ON true
WHERE c.id = $1`;

let configPromise;

// Credentials are read once per environment (cold start) and kept in memory.
export function dbConfig() {
  configPromise ??= new SecretsManagerClient({})
    .send(new GetSecretValueCommand({ SecretId: process.env.DB_SECRET_ARN }))
    .then((res) => {
      const secret = JSON.parse(res.SecretString);
      return {
        host: process.env.DB_HOST,
        port: 5432,
        database: process.env.DB_NAME,
        user: secret.username,
        password: secret.password,
        application_name: `lab-${variant}`,
        ssl: { ca: RDS_CA },
        connectionTimeoutMillis: 5000,
      };
    })
    .catch((err) => {
      configPromise = undefined;
      throw err;
    });
  return configPromise;
}

export function tokenOk(headerValue) {
  return headerValue === process.env.LAB_TOKEN;
}

// `conn` is a pg.Client or a client checked out of a pg.Pool: the sleep and the query
// run on the same connection, so delay_ms keeps that connection busy.
export async function getCustomer(conn, id, delayMs) {
  if (delayMs > 0) {
    await conn.query('SELECT pg_sleep($1::float8 / 1000)', [delayMs]);
  }
  const { rows } = await conn.query(CUSTOMER_SQL, [id]);
  if (rows.length === 0) return null;
  const { recent_orders, ...customer } = rows[0];
  return { customer, recent_orders, variant, envId };
}

export function parseRequest(path, delayParam) {
  const m = /^\/customer\/(\d+)$/.exec(path);
  if (!m) return null;
  const delayMs = Math.max(0, Math.min(Number(delayParam ?? 0) || 0, 5000));
  return { id: Number(m[1]), delayMs };
}
