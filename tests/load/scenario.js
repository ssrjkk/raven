import http from 'k6/http';
import { check, sleep } from 'k6';
import { SharedArray } from 'k6/data';

const AUTH_BASE = __ENV.AUTH_BASE || 'http://localhost:8001';
const GATEWAY_BASE = __ENV.GATEWAY_BASE || 'http://localhost:8000';
const MONITOR_BASE = __ENV.MONITOR_BASE || 'http://localhost:8003';

const users = new SharedArray('users', function () {
  const results = [];
  for (let i = 0; i < 50; i++) {
    results.push({ username: `load_${i}_${Date.now()}`, password: 'testpass123' });
  }
  return results;
});

export const options = {
  stages: [
    { duration: '30s', target: 20 },
    { duration: '1m', target: 50 },
    { duration: '30s', target: 100 },
    { duration: '30s', target: 0 },
  ],
  thresholds: {
    http_req_duration: ['p(95)<500'],
    http_req_failed: ['rate<0.05'],
  },
};

function getToken(user) {
  const regRes = http.post(`${AUTH_BASE}/api/v1/auth/register`, JSON.stringify(user), {
    headers: { 'Content-Type': 'application/json' },
  });
  if (regRes.status === 200) {
    return regRes.json().token;
  }
  const loginRes = http.post(`${AUTH_BASE}/api/v1/auth/login`, JSON.stringify(user), {
    headers: { 'Content-Type': 'application/json' },
  });
  return loginRes.json().token;
}

export default function () {
  const user = users[Math.floor(Math.random() * users.length)];
  const token = getToken(user);
  const headers = { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' };

  const health = http.get(`${GATEWAY_BASE}/health`);
  check(health, { 'health ok': (r) => r.status === 200 });

  const monitorRes = http.post(
    `${GATEWAY_BASE}/api/v1/monitors`,
    JSON.stringify({ name: `mon_${__VU}_${__ITER}`, type: 'latency', threshold: 500 }),
    { headers },
  );
  check(monitorRes, { 'monitor created': (r) => r.status === 200 });

  if (monitorRes.status === 200) {
    const monId = monitorRes.json().id;
    const getRes = http.get(`${GATEWAY_BASE}/api/v1/monitors/${monId}`, { headers });
    check(getRes, { 'monitor get': (r) => r.status === 200 });
  }

  sleep(1);
}
