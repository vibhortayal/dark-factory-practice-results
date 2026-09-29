const http = require('http');
const { spawn } = require('child_process');

const BASE_URL = 'http://localhost:8080';

// Utility: Make HTTP requests
function makeRequest(method, path, body = null, headers = {}) {
  return new Promise((resolve, reject) => {
    const url = new URL(path, BASE_URL);
    const options = {
      method,
      hostname: url.hostname,
      port: url.port || 80,
      path: url.pathname + url.search,
      headers: {
        'Content-Type': 'application/json',
        ...headers
      }
    };

    const req = http.request(options, (res) => {
      let data = '';
      res.on('data', chunk => { data += chunk; });
      res.on('end', () => {
        try {
          const parsed = data ? JSON.parse(data) : null;
          resolve({ status: res.statusCode, body: parsed, rawBody: data });
        } catch (e) {
          resolve({ status: res.statusCode, body: null, rawBody: data });
        }
      });
    });

    req.on('error', reject);
    if (body) {
      req.write(JSON.stringify(body));
    }
    req.end();
  });
}

async function runTests() {
  console.log('Starting regression tests...\n');
  let passed = 0;
  let failed = 0;

  // Test 1: Idempotency with reordered keys
  console.log('TEST 1: Idempotency with reordered keys');
  try {
    // Reset state
    await makeRequest('POST', '/_test/reset', {
      users: [
        { id: 'u1', email: 'alice@example.com', password: 'password123', display_name: 'Alice', handle: 'alice', balance: 1000 },
        { id: 'u2', email: 'bob@example.com', password: 'password123', display_name: 'Bob', handle: 'bob', balance: 1000 }
      ]
    });

    // Create a payment with original key order
    const body1 = { to_handle: 'bob', amount: 100 };
    const res1 = await makeRequest('POST', '/payments', body1, {
      'Authorization': 'Bearer token_u1',
      'Idempotency-Key': 'idem-key-1'
    });

    if (res1.status !== 201) {
      throw new Error(`Expected 201, got ${res1.status}`);
    }
    const paymentId = res1.body.payment_id;

    // Replay with reordered keys in request body (amount before to_handle)
    const body2 = { amount: 100, to_handle: 'bob' };
    const res2 = await makeRequest('POST', '/payments', body2, {
      'Authorization': 'Bearer token_u1',
      'Idempotency-Key': 'idem-key-1'
    });

    if (res2.status !== 200) {
      throw new Error(`Expected 200 for idempotent replay, got ${res2.status}`);
    }
    if (res2.body.payment_id !== paymentId) {
      throw new Error(`Expected same payment_id, got different`);
    }

    console.log('  ✓ Idempotency with reordered keys works correctly\n');
    passed++;
  } catch (err) {
    console.log(`  ✗ FAILED: ${err.message}\n`);
    failed++;
  }

  // Test 2: Reset with unsupported minor_units value (should reject with 422)
  console.log('TEST 2: Reset with unsupported minor_units (should reject with 422)');
  try {
    // First, set a valid state
    const initialReset = await makeRequest('POST', '/_test/reset', {
      currency: 'USD',
      minor_units: 2,
      users: [
        { id: 'u1', email: 'test@example.com', password: 'password123', display_name: 'Test', handle: 'test', balance: 100 }
      ]
    });

    if (initialReset.status !== 204) {
      throw new Error(`Initial reset failed with status ${initialReset.status}`);
    }

    // Export to verify initial state
    const export1 = await makeRequest('GET', '/_test/export');
    const initialMinorUnits = export1.body.state.minor_units;
    const initialBalance = export1.body.state.users[0].balance;

    // Try to reset with invalid minor_units (e.g., 1, which is not in [0, 2, 3])
    const invalidReset = await makeRequest('POST', '/_test/reset', {
      currency: 'USD',
      minor_units: 1,
      users: [
        { id: 'u1', email: 'test@example.com', password: 'password123', display_name: 'Test', handle: 'test', balance: 999 }
      ]
    });

    if (invalidReset.status !== 422) {
      throw new Error(`Expected 422 for invalid minor_units, got ${invalidReset.status}`);
    }
    if (!invalidReset.body.error.code || !invalidReset.body.error.message.includes('minor_units')) {
      throw new Error(`Expected error about minor_units, got: ${JSON.stringify(invalidReset.body)}`);
    }

    // Verify state was not changed
    const export2 = await makeRequest('GET', '/_test/export');
    const unchangedMinorUnits = export2.body.state.minor_units;
    const unchangedBalance = export2.body.state.users[0].balance;

    if (unchangedMinorUnits !== initialMinorUnits) {
      throw new Error(`State was modified: minor_units changed from ${initialMinorUnits} to ${unchangedMinorUnits}`);
    }
    if (unchangedBalance !== initialBalance) {
      throw new Error(`State was modified: balance changed from ${initialBalance} to ${unchangedBalance}`);
    }

    console.log('  ✓ Invalid minor_units correctly rejected with 422 and state preserved\n');
    passed++;
  } catch (err) {
    console.log(`  ✗ FAILED: ${err.message}\n`);
    failed++;
  }

  // Test 3: Reset with valid minor_units values [0, 2, 3]
  console.log('TEST 3: Reset with valid minor_units values');
  try {
    const validValues = [0, 2, 3];
    for (const value of validValues) {
      const res = await makeRequest('POST', '/_test/reset', {
        currency: 'EUR',
        minor_units: value
      });

      if (res.status !== 204) {
        throw new Error(`Failed to reset with minor_units=${value}, got ${res.status}`);
      }

      const exp = await makeRequest('GET', '/_test/export');
      if (exp.body.state.minor_units !== value) {
        throw new Error(`Expected minor_units=${value}, got ${exp.body.state.minor_units}`);
      }
    }

    console.log('  ✓ All valid minor_units values [0, 2, 3] accepted correctly\n');
    passed++;
  } catch (err) {
    console.log(`  ✗ FAILED: ${err.message}\n`);
    failed++;
  }

  // Test 4: Idempotency with different whitespace
  console.log('TEST 4: Idempotency with different whitespace/formatting');
  try {
    // Reset
    await makeRequest('POST', '/_test/reset', {
      users: [
        { id: 'u1', email: 'alice@example.com', password: 'password123', display_name: 'Alice', handle: 'alice', balance: 1000 },
        { id: 'u2', email: 'bob@example.com', password: 'password123', display_name: 'Bob', handle: 'bob', balance: 1000 }
      ]
    });

    // First request
    const res1 = await makeRequest('POST', '/payments', 
      { to_handle: 'bob', amount: 50, note: 'test' },
      { 'Authorization': 'Bearer token_u1', 'Idempotency-Key': 'idem-key-ws' }
    );

    if (res1.status !== 201) {
      throw new Error(`Expected 201, got ${res1.status}`);
    }

    // Replay with extra spaces/different order but same logical value
    const res2 = await makeRequest('POST', '/payments',
      { amount: 50, note: 'test', to_handle: 'bob' },
      { 'Authorization': 'Bearer token_u1', 'Idempotency-Key': 'idem-key-ws' }
    );

    if (res2.status !== 200) {
      throw new Error(`Expected 200 for idempotent replay, got ${res2.status}`);
    }

    console.log('  ✓ Idempotency with different whitespace/formatting works correctly\n');
    passed++;
  } catch (err) {
    console.log(`  ✗ FAILED: ${err.message}\n`);
    failed++;
  }

  console.log(`\n========================================`);
  console.log(`Tests passed: ${passed}`);
  console.log(`Tests failed: ${failed}`);
  console.log(`========================================\n`);

  process.exit(failed > 0 ? 1 : 0);
}

runTests().catch(err => {
  console.error('Test error:', err);
  process.exit(1);
});
