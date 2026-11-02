// Web Function: one environment serves many requests at once and shares one pg.Pool.
import express from 'express';
import pg from 'pg';
import { dbConfig, getCustomer, parseRequest, tokenOk } from '../shared/customer.mjs';

const POOL_MAX = Number(process.env.POOL_MAX ?? 10);

let poolPromise;

function getPool() {
  poolPromise ??= dbConfig()
    .then((config) => {
      const pool = new pg.Pool({ ...config, max: POOL_MAX });
      // An idle client that errors is removed from the pool; without a listener the process would exit.
      pool.on('error', () => {});
      return pool;
    })
    .catch((err) => {
      poolPromise = undefined;
      throw err;
    });
  return poolPromise;
}

const app = express();

app.get('/health', (_req, res) => res.json({ ok: true }));

app.get('/customer/:id', async (req, res) => {
  if (!tokenOk(req.get('x-lab-token'))) return res.status(401).json({ error: 'unauthorized' });

  const parsed = parseRequest(req.path, req.query.delay_ms);
  if (!parsed) return res.status(404).json({ error: 'not found' });

  let conn;
  try {
    conn = await (await getPool()).connect();
    const result = await getCustomer(conn, parsed.id, parsed.delayMs);
    conn.release();
    return result ? res.json(result) : res.status(404).json({ error: 'customer not found' });
  } catch (err) {
    // Passing the error destroys the connection instead of returning it to the pool.
    conn?.release(err);
    return res.status(500).json({ error: err.code ?? 'db_error' });
  }
});

app.use((_req, res) => res.status(404).json({ error: 'not found' }));

// Lambda sets AWS_LAMBDA_HTTP_ENDPOINT as host:port and the server must bind exactly that address.
const [host, port] = (process.env.AWS_LAMBDA_HTTP_ENDPOINT ?? '127.0.0.1:8080').split(':');
app.listen(Number(port), host);
