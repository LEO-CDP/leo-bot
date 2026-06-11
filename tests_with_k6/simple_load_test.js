import http from 'k6/http';
import { check, sleep } from 'k6';
import { uuidv4 } from 'https://jslib.k6.io/k6-utils/1.2.0/index.js';
import { htmlReport } from 'https://raw.githubusercontent.com/benc-uk/k6-reporter/main/dist/bundle.js';
import { textSummary } from 'https://jslib.k6.io/k6-summary/0.0.2/index.js';

// === CONFIGURATION ===
export const options = {
  stages: [
    { duration: '30s', target: 10 },
    { duration: '1m', target: 50 },
    { duration: '2m', target: 50 },
    { duration: '30s', target: 0 },
  ],
  thresholds: {
    http_req_duration: ['p(95)<8000'],
    http_req_failed: ['rate<0.01'],
  },
};

// === TEST FUNCTION ===
export default function () {
  const url = 'https://leobot.leocdp.com/_leoai/ask';
  const visitorId = uuidv4();

  const payload = JSON.stringify({
    context: 'hi  ; Chào bạn Thomas! Hôm nay bạn cần LEO hỗ trợ gì nè? 😊  ; ',
    question: 'hi',
    visitor_id: visitorId,
    answer_in_language: 'Vietnamese',
    answer_in_format: 'html',
  });

  const params = {
    headers: { 'Content-Type': 'application/json' },
  };

  const res = http.post(url, payload, params);

  check(res, {
    'status is 200': (r) => r.status === 200,
    'response time < 8s': (r) => r.timings.duration < 8000,
  });

  sleep(1 + Math.random() * 2);
}

// === SUMMARY REPORT ===
export function handleSummary(data) {
  return {
    'stdout': textSummary(data, { indent: ' ', enableColors: true }),
    'results/simple_load_test_report.html': htmlReport(data),
  };
}
