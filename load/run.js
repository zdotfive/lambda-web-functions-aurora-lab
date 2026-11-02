// k6 load script, same for all variants.
// Env: TARGET_URL, VARIANT, VUS, DURATION, DELAY_MS, LAB_TOKEN
//      MODE=constant (default) | spike (0 -> VUS in 30 s, then 2 min at VUS)
import http from 'k6/http';
import { check } from 'k6';
import { Counter, Rate } from 'k6/metrics';

const TARGET_URL = __ENV.TARGET_URL.replace(/\/$/, '');
const VUS = Number(__ENV.VUS ?? 10);
const DELAY_MS = Number(__ENV.DELAY_MS ?? 0);
const MODE = __ENV.MODE ?? 'constant';

const scenarios = {
  constant: {
    main: { executor: 'constant-vus', vus: VUS, duration: __ENV.DURATION ?? '3m' },
  },
  spike: {
    main: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '30s', target: VUS },
        { duration: '2m', target: VUS },
      ],
    },
  },
};

export const options = {
  scenarios: scenarios[MODE],
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
  tags: { variant: __ENV.VARIANT },
  discardResponseBodies: false,
};

const status = {};
for (const code of ['200', '401', '404', '429', '500', '502', '503', '504', 'other']) {
  status[code] = new Counter(`status_${code}`);
}
const errors = new Rate('errors');
// Web Functions say why a request was rejected in the lambda-web-error-type header.
// k6 metrics must be created in the init context, so the documented types are listed up front.
const webErrorTypes = {};
for (const t of [
  'Platform.EndpointRequestThrottle',
  'Platform.AccountRequestThrottle',
  'Platform.EndpointMaxEnvThrottle',
  'Platform.AccountActiveVCPUArm64Throttle',
  'Platform.EndpointConcurrentInitThrottle',
  'other',
]) {
  webErrorTypes[t] = new Counter(`web_error_${t.replace(/\W/g, '_')}`);
}
const seenEnvs = new Set();
const newEnvs = new Counter('env_ids_seen_by_vu');

export default function () {
  const id = 1 + Math.floor(Math.random() * 1000000);
  const res = http.get(`${TARGET_URL}/customer/${id}?delay_ms=${DELAY_MS}`, {
    headers: { 'x-lab-token': __ENV.LAB_TOKEN },
    timeout: '30s',
    // One name for every id: otherwise each URL becomes its own time series and k6 runs out of memory.
    tags: { name: 'GET /customer/:id' },
  });

  const key = String(res.status);
  (status[key] ?? status.other).add(1);
  // A 404 would be a missing customer id: counted on its own, not as an error.
  const ok = res.status === 200 || res.status === 404;
  errors.add(!ok);
  const webError = res.headers['Lambda-Web-Error-Type'];
  if (webError) (webErrorTypes[webError] ?? webErrorTypes.other).add(1);
  check(res, { 'status 200': (r) => r.status === 200 });

  if (res.status === 200) {
    const envId = res.json('envId');
    if (envId && !seenEnvs.has(envId)) {
      seenEnvs.add(envId);
      newEnvs.add(1);
      // One line per (VU, env) pair; distinct envIds are counted after the run from k6.log.
      console.log(`ENV ${envId}`);
    }
  }
}
