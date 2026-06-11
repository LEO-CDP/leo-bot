import http from 'k6/http';
import { check, sleep } from 'k6';
import { uuidv4 } from 'https://jslib.k6.io/k6-utils/1.2.0/index.js';
import { htmlReport } from 'https://raw.githubusercontent.com/benc-uk/k6-reporter/main/dist/bundle.js';
import { textSummary } from 'https://jslib.k6.io/k6-summary/0.0.2/index.js';

// ===============================
// CONFIGURATION
// ===============================
export const options = {
  stages: [
    { duration: '30s', target: 10 },  // ramp up to 10 users
    { duration: '1m', target: 50 },   // hold 50 concurrent users
    { duration: '2m', target: 50 },   // steady phase
    { duration: '30s', target: 0 },   // ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<8000'], // 95% of requests < 8 seconds
    http_req_failed: ['rate<0.01'],    // < 1% errors allowed
  },
};

// ===============================
// DYNAMIC TEST DATA
// ===============================
const contexts = [
  "Xin chào LEO ; Hôm nay tôi cần hỏi về hệ thống AI của công ty.",
  "Chào bạn ; Tôi đang muốn tìm hiểu tính năng CDP của LEO BOT.",
  "LEO ơi ; Cho tôi biết cách tạo chiến dịch marketing mới nhé.",
  "Hi LEO ; Tôi có thể kết nối CRM với hệ thống LEO CDP không?",
  "LEO ơi ; Gợi ý giúp tôi cách phân tích dữ liệu khách hàng đi."
];

const questions = [
  "Làm sao để xem báo cáo khách hàng?",
  "LEO có thể hỗ trợ viết email marketing không?",
  "Tôi muốn biết khách hàng nào tương tác nhiều nhất tuần này.",
  "Bạn có thể giải thích khái niệm CDP là gì không?",
  "Hãy cho tôi biết cách tích hợp với Zalo OA.",
  "LEO giúp tôi tạo insight khách hàng mới.",
  "Có thể xuất dữ liệu ra file CSV không?",
  "Tính năng phân khúc khách hàng hoạt động ra sao?",
  "LEO hiểu được tiếng Anh chứ?",
  "Tôi muốn xem dữ liệu của chiến dịch quảng cáo Facebook."
];

function randomItem(arr) {
  return arr[Math.floor(Math.random() * arr.length)];
}

// Map to persist visitor IDs across iterations per VU
const vuVisitors = new Map();

// ===============================
// TEST FUNCTION
// ===============================
export default function () {
  const url = 'https://leobot.leocdp.com/_leoai/ask';

  // One visitor ID per VU
  let visitorId = vuVisitors.get(__VU);
  if (!visitorId) {
    visitorId = uuidv4();
    vuVisitors.set(__VU, visitorId);
  }

  const payload = JSON.stringify({
    context: randomItem(contexts),
    question: randomItem(questions),
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
    'response not empty': (r) => r.body && r.body.length > 10,
  });

  // Simulate user “thinking time”
  sleep(2 + Math.random() * 3);
}

// ===============================
// REPORT GENERATION
// ===============================
export function handleSummary(data) {
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  return {
    'stdout': textSummary(data, { indent: ' ', enableColors: true }),
    [`results/ask_question_test_report.html`]: htmlReport(data),
  };
}
