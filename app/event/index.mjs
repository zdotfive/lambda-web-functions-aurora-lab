// Event Function behind a Function URL. Used by event-direct (host = Aurora writer)
// and event-proxy (host = RDS Proxy endpoint): same code, different DB_HOST.
import pg from 'pg';
import { dbConfig, getCustomer, parseRequest, tokenOk } from '../shared/customer.mjs';

// One connection per environment, opened outside the handler and reused.
// An Event Function environment handles one request at a time.
let client;

async function getClient() {
  if (!client) {
    const c = new pg.Client(await dbConfig());
    c.on('error', () => {
      if (client === c) client = undefined;
    });
    await c.connect();
    client = c;
  }
  return client;
}

function json(statusCode, body) {
  return { statusCode, headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) };
}

export const handler = async (event) => {
  if (event.rawPath === '/health') return json(200, { ok: true });
  if (!tokenOk(event.headers?.['x-lab-token'])) return json(401, { error: 'unauthorized' });

  const req = parseRequest(event.rawPath, event.queryStringParameters?.delay_ms);
  if (!req) return json(404, { error: 'not found' });

  try {
    const result = await getCustomer(await getClient(), req.id, req.delayMs);
    return result ? json(200, result) : json(404, { error: 'customer not found' });
  } catch (err) {
    // Drop the connection so the next request reconnects.
    const c = client;
    client = undefined;
    c?.end().catch(() => {});
    return json(500, { error: err.code ?? 'db_error' });
  }
};
