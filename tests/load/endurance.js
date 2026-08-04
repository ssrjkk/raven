import http from "k6/http";
import { check, sleep } from "k6";
import { Rate } from "k6/metrics";
import crypto from "k6/crypto";

const GATEWAY = __ENV.GATEWAY_URL || "http://localhost:8000";

const errorRate = new Rate("errors");

export const options = {
  stages: [
    { duration: "2m", target: 200 },
    { duration: "5m", target: 200 },
    { duration: "2m", target: 0 },
  ],
  thresholds: {
    errors: ["rate<0.001"],
    http_req_duration: ["p(95)<500"],
  },
};

function randomId() {
  return crypto.randomBytes(9).hex();
}

export default function () {
  const headers = {
    "Content-Type": "application/json",
    "X-Idempotency-Key": randomId(),
    "X-Correlation-Id": randomId(),
  };

  // Simulate a multi-step conversation flow
  // Step 1: Auth
  const loginPayload = JSON.stringify({
    username: `perfuser-${randomId()}`,
    password: "pass",
  });
  let res = http.post(`${GATEWAY}/api/v1/auth/login`, loginPayload, { headers });
  errorRate.add(res.status !== 200);
  check(res, { "login ok": (r) => r.status === 200 });

  // Step 2: Create monitor
  const monitorPayload = JSON.stringify({
    name: `perf-mon-${randomId()}`,
    url: "https://example.com",
    interval_seconds: 60,
  });
  res = http.post(`${GATEWAY}/api/v1/monitors`, monitorPayload, { headers });
  errorRate.add(res.status !== 201);
  check(res, { "monitor created": (r) => r.status === 201 });

  // Step 3: RAG search
  res = http.get(`${GATEWAY}/api/v1/rag/search?q=performance+test`, { headers });
  errorRate.add(res.status !== 200);
  check(res, { "rag search ok": (r) => r.status === 200 });

  // Step 4: Create task
  const taskPayload = JSON.stringify({
    type: "analysis",
    input: "Analyze performance test results",
  });
  res = http.post(`${GATEWAY}/api/v1/tasks`, taskPayload, { headers });
  errorRate.add(res.status !== 201);
  check(res, { "task created": (r) => r.status === 201 });

  sleep(1);
}
