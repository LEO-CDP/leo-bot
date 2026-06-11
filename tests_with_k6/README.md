# 🧪 Setup Guide: Install and Run k6 on Ubuntu 22.04

`k6` is a modern open-source load testing tool for testing APIs and backend systems like **LEO BOT**.
This guide explains how to install it securely and run a performance test against your endpoint.

---

## 1. Update your system

Keep your Ubuntu system and package list up to date:

```bash
sudo apt-get update
sudo apt-get upgrade -y
```

---

## 2. Import the official k6 GPG key

To ensure package authenticity, import k6’s signing key:

```bash
sudo gpg -k
sudo gpg --no-default-keyring --keyring /usr/share/keyrings/k6-archive-keyring.gpg --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys C5AD17C747E3415A3642D57D77C6C491D6AC1D69
```

---

## 3. Add the k6 APT repository

This tells Ubuntu where to fetch k6 packages from:

```bash
echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" | sudo tee /etc/apt/sources.list.d/k6.list
```

Then verify:

```bash
cat /etc/apt/sources.list.d/k6.list
```

Expected:

```
deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main
```

---

## 4. Install k6

Run the following commands:

```bash
sudo apt-get update
sudo apt-get install k6 -y
```

---

## 5. Verify installation

Check that k6 is installed correctly:

```bash
k6 version
```

Example output:

```
k6 v0.51.0 (2025-xx-xx)
```

---

## 6. Create and run the LEO BOT load test

Create a new file named `leobot_load_test.js`:

```javascript
import http from 'k6/http';
import { check, sleep } from 'k6';
import { uuidv4 } from 'https://jslib.k6.io/k6-utils/1.2.0/index.js';

// === CONFIGURATION ===
// Adjust virtual users (VUs), duration, and ramp stages as needed.
export const options = {
  stages: [
    { duration: '30s', target: 10 },  // ramp up to 10 users
    { duration: '1m', target: 50 },   // increase to 50 concurrent users
    { duration: '2m', target: 50 },   // sustain load
    { duration: '30s', target: 0 },   // ramp down
  ],
  thresholds: {
    http_req_duration: ['p(95)<8000'], // 95% of requests < 8 seconds
    http_req_failed: ['rate<0.01'],    // less than 1% errors
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
    headers: {
      'Content-Type': 'application/json',
    },
  };

  const res = http.post(url, payload, params);

  // === CHECKS ===
  check(res, {
    'status is 200': (r) => r.status === 200,
    'response time < 8s': (r) => r.timings.duration < 8000,
  });

  // Simulate user think time
  sleep(1 + Math.random() * 2);
}
```

---

## 7. Run the test

Execute:

```bash
k6 run leobot_load_test.js
```

You’ll see live output:

```
running (3m30.0s), 50/50 VUs, 320 complete and 0 interrupted iterations
status is 200..............: 100.00% ✓ 320 ✗ 0
response time < 8s.........: 98.75% ✓ 316 ✗ 4
```

---

## 8. (Optional) Export or visualize results

To export results:

```bash
k6 run --out json=results.json leobot_load_test.js
```

To visualize them:

```bash
xk6-dashboard --input results.json --output report.html
```

---

## 9. (Optional) Uninstall k6

If you ever need to remove it:

```bash
sudo apt-get remove --purge k6 -y
sudo rm /etc/apt/sources.list.d/k6.list
sudo rm /usr/share/keyrings/k6-archive-keyring.gpg
```

---

## ✅ Summary

| Step | Description                      |
| ---- | -------------------------------- |
| 1    | Update Ubuntu system             |
| 2    | Import k6 GPG key                |
| 3    | Add k6 repo                      |
| 4    | Install k6                       |
| 5    | Verify installation              |
| 6    | Create and run LEO BOT load test |
| 7    | Analyze results                  |
| 8    | (Optional) Export or uninstall   |

