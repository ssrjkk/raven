import http from "k6/http";
import { check, sleep } from "k6";
import { Rate } from "k6/metrics";

const RAVEN_URL = __ENV.RAVEN_URL || "http://localhost:18888";
const ENDPOINTS = ["/api/health/live", "/api/status", "/api/metrics"];

const errorRate = new Rate("errors");

export const options = {
  vus: 5,
  duration: "30s",
  thresholds: {
    errors: ["rate<0.001"],
  },
};

export default function () {
  for (const path of ENDPOINTS) {
    const res = http.get(`${RAVEN_URL}${path}`);
    errorRate.add(res.status !== 200);
    check(res, {
      [`${path} health`]: (r) => r.status === 200,
    });
  }

  sleep(1);
}