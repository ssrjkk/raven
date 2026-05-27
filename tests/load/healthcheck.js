import http from "k6/http";
import { check, sleep } from "k6";
import { Rate } from "k6/metrics";

const GATEWAY_URL = __ENV.GATEWAY_URL || "http://localhost:8000";
const SERVICE_URLS = {
  auth: __ENV.AUTH_URL || "http://localhost:8001",
  agent: __ENV.AGENT_URL || "http://localhost:8002",
  monitor: __ENV.MONITOR_URL || "http://localhost:8003",
  rag: __ENV.RAG_URL || "http://localhost:8004",
  task: __ENV.TASK_URL || "http://localhost:8005",
  code: __ENV.CODE_URL || "http://localhost:8006",
};

const errorRate = new Rate("errors");

export const options = {
  vus: 5,
  duration: "30s",
  thresholds: {
    errors: ["rate<0.001"],
  },
};

export default function () {
  for (const [name, url] of Object.entries(SERVICE_URLS)) {
    const res = http.get(`${url}/health`);
    errorRate.add(res.status !== 200);
    check(res, {
      [`${name} health`]: (r) => r.status === 200,
    });
  }

  const res = http.get(`${GATEWAY_URL}/health`);
  errorRate.add(res.status !== 200);
  check(res, { "gateway health": (r) => r.status === 200 });

  sleep(1);
}
