import http from "k6/http";
import { check, sleep } from "k6";
import { Rate, Trend } from "k6/metrics";
import crypto from "k6/crypto";

const BASE_URL = __ENV.BASE_URL || "http://localhost:8000";
const AUTH_TOKEN = __ENV.AUTH_TOKEN || "test-token";

const errorRate = new Rate("errors");
const latency = new Trend("request_duration_ms");

export const options = {
  stages: [
    { duration: "30s", target: 10 },   // ramp-up
    { duration: "1m", target: 50 },     // steady moderate
    { duration: "30s", target: 100 },   // peak
    { duration: "30s", target: 50 },    // scale down
    { duration: "30s", target: 0 },     // cool down
  ],
  thresholds: {
    errors: ["rate<0.001"],             // <0.1% error rate
    http_req_duration: ["p(95)<200"],   // p95 <200ms
  },
};

function randomId(): string {
  return crypto.randomBytes(9).hex();
}

export default function () {
  const headers = {
    "Content-Type": "application/json",
    "Authorization": `Bearer ${AUTH_TOKEN}`,
    "X-Idempotency-Key": randomId(),
    "X-Correlation-Id": randomId(),
  };

  // GET /health — gateway
  {
    const res = http.get(`${BASE_URL}/health`, { headers });
    latency.add(res.timings.duration);
    errorRate.add(res.status !== 200);
    check(res, {
      "health status 200": (r) => r.status === 200,
      "health response <200ms": (r) => r.timings.duration < 200,
    });
  }

  sleep(0.5);

  // POST /api/v1/auth/login
  {
    const payload = JSON.stringify({
      username: `loadtest-${randomId()}`,
      password: "test-password-123",
    });
    const res = http.post(`${BASE_URL}/api/v1/auth/login`, payload, { headers });
    latency.add(res.timings.duration);
    errorRate.add(res.status !== 200 && res.status !== 201);
    check(res, {
      "auth login ok": (r) => r.status === 200 || r.status === 201,
    });
  }

  sleep(0.5);

  // POST /api/v1/monitors — monitor-engine
  {
    const payload = JSON.stringify({
      name: `loadtest-monitor-${randomId()}`,
      url: "https://httpbin.org/status/200",
      interval_seconds: 300,
    });
    const res = http.post(`${BASE_URL}/api/v1/monitors`, payload, { headers });
    latency.add(res.timings.duration);
    errorRate.add(res.status !== 200 && res.status !== 201);
    check(res, {
      "monitor create ok": (r) => r.status === 200 || r.status === 201,
    });
  }

  sleep(0.5);

  // GET /api/v1/rag/search — rag-service
  {
    const res = http.get(`${BASE_URL}/api/v1/rag/search?q=test+query&limit=5`, { headers });
    latency.add(res.timings.duration);
    errorRate.add(res.status !== 200);
    check(res, {
      "rag search ok": (r) => r.status === 200,
    });
  }

  sleep(1);
}
