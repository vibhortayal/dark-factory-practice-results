const http = require('http');
const crypto = require('crypto');
const bcrypt = require('bcryptjs');

// In-memory state
let state = {
  currency: "EUR",
  minor_units: 2,
  users: {}, // id -> user
  emails: {}, // email -> user_id
  handles: {}, // handle -> user_id
  tokens: {}, // token -> user_id
  payments: {}, // id -> payment
  requests: {}, // id -> request
  splits: {}, // id -> split
  settlement_operators: new Set(), // user_id strings
  idempotency_keys: {} // user_id:key -> { bodyHash, response: { status, body } }
};

// Reset state helper
function resetState(fixture = {}) {
  const users = {};
  const emails = {};
  const handles = {};
  const tokens = {};
  const payments = {};
  const requests = {};
  const splits = {};
  const settlement_operators = new Set();
  const idempotency_keys = {};

  const currency = fixture.currency || "EUR";
  const minor_units = fixture.minor_units !== undefined ? fixture.minor_units : 2;

  if (fixture.users) {
    for (const u of fixture.users) {
      if (u.balance < 0) {
        throw new Error("negative_balance");
      }
      // Validate handle format
      if (!/^[a-z0-9_]{1,20}$/.test(u.handle)) {
        throw new Error("invalid_handle_format");
      }
      users[u.id] = {
        id: u.id,
        email: u.email,
        passwordHash: bcrypt.hashSync(u.password, 10),
        display_name: u.display_name,
        handle: u.handle,
        balance: u.balance
      };
      emails[u.email.toLowerCase()] = u.id;
      handles[u.handle.toLowerCase()] = u.id;
      // Pre-seed a token for seeded users
      const token = `token_${u.id}`;
      tokens[token] = u.id;
    }
  }

  if (fixture.payments) {
    for (const p of fixture.payments) {
      payments[p.id] = {
        payment_id: p.id,
        from_user_id: p.from_user_id,
        from_handle: users[p.from_user_id]?.handle || "",
        to_user_id: p.to_user_id,
        to_handle: users[p.to_user_id]?.handle || "",
        amount: p.amount,
        currency,
        note: p.note || "",
        visibility: p.visibility || "public",
        request_id: p.request_id || null,
        settlement_id: p.settlement_id || null,
        created_at: p.created_at || getCurrentTimestamp()
      };
    }
  }

  if (fixture.requests) {
    for (const r of fixture.requests) {
      requests[r.id] = {
        request_id: r.id,
        requester_id: r.requester_id,
        requester_handle: users[r.requester_id]?.handle || "",
        payer_id: r.payer_id,
        payer_handle: users[r.payer_id]?.handle || "",
        amount: r.amount,
        currency,
        note: r.note || "",
        status: r.status || "pending",
        payment_id: r.payment_id || null,
        created_at: r.created_at || getCurrentTimestamp()
      };
    }
  }

  if (fixture.settlement_operator_ids) {
    for (const opId of fixture.settlement_operator_ids) {
      settlement_operators.add(opId);
    }
  }

  state = {
    currency,
    minor_units,
    users,
    emails,
    handles,
    tokens,
    payments,
    requests,
    splits,
    settlement_operators,
    idempotency_keys
  };
}

// Helper: Generate RFC 3339 timestamp with explicit offset
function getCurrentTimestamp() {
  const now = new Date();
  const iso = now.toISOString();
  // Replace Z with +00:00 for explicit offset format
  return iso.replace('Z', '+00:00');
}

// Ensure first initialization
resetState();

// Utility: Response helper
function sendJSON(res, status, data) {
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' });
  res.end(JSON.stringify(data));
}

function sendError(res, status, code, message = "An error occurred") {
  sendJSON(res, status, { error: { code, message } });
}

// Utility: Body Parser
function parseBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => {
      if (!body) {
        resolve(null);
        return;
      }
      try {
        const parsed = JSON.parse(body);
        resolve(parsed);
      } catch (err) {
        reject(err);
      }
    });
  });
}

// Derive Handle
function deriveHandle(email) {
  const localPart = email.split('@')[0].toLowerCase();
  const replaced = localPart.replace(/[^a-z0-9_]/g, '_');
  return replaced.slice(0, 20);
}

// Helper: authenticate bearer token
function authenticate(req) {
  const authHeader = req.headers['authorization'];
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return null;
  }
  const token = authHeader.substring(7);
  const userId = state.tokens[token];
  if (!userId) return null;
  return state.users[userId];
}

// Main Request Handler
const server = http.createServer(async (req, res) => {
  const parsedUrl = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  const pathname = parsedUrl.pathname;
  const method = req.method;

  // 1. Health check
  if (method === 'GET' && pathname === '/health') {
    return sendJSON(res, 200, { status: "ok" });
  }

  // 2. Reset and seed
  if (method === 'POST' && pathname === '/_test/reset') {
    try {
      const body = await parseBody(req);
      resetState(body || {});
      res.writeHead(204);
      return res.end();
    } catch (err) {
      if (err.message === 'negative_balance' || err.message === 'invalid_handle_format') {
        return sendError(res, 422, "validation_failed", err.message === 'negative_balance' ? "Balance cannot be negative" : "Invalid handle format");
      }
      return sendError(res, 400, "malformed_request", "Unparseable body or incorrect types");
    }
  }

  // 3. Export
  if (method === 'GET' && pathname === '/_test/export') {
    const exportedState = {
      currency: state.currency,
      minor_units: state.minor_units,
      users: Object.values(state.users),
      emails: state.emails,
      handles: state.handles,
      tokens: state.tokens,
      payments: Object.values(state.payments),
      requests: Object.values(state.requests),
      splits: Object.values(state.splits),
      settlement_operators: Array.from(state.settlement_operators),
      idempotency_keys: state.idempotency_keys
    };
    return sendJSON(res, 200, {
      track: "pocketful",
      format_version: 1,
      state: exportedState
    });
  }

  // 4. Import
  if (method === 'POST' && pathname === '/_test/import') {
    try {
      const body = await parseBody(req);
      if (!body || body.track !== "pocketful" || body.format_version !== 1 || !body.state) {
        return sendError(res, 422, "validation_failed", "Invalid import track/format/state");
      }
      const s = body.state;
      state.currency = s.currency;
      state.minor_units = s.minor_units;
      state.users = {};
      for (const u of s.users) {
        state.users[u.id] = u;
      }
      state.emails = s.emails;
      state.handles = s.handles;
      state.tokens = s.tokens;
      state.payments = {};
      for (const p of s.payments) {
        state.payments[p.payment_id] = p;
      }
      state.requests = {};
      for (const r of s.requests) {
        state.requests[r.request_id] = r;
      }
      state.splits = {};
      for (const sp of s.splits) {
        state.splits[sp.split_id] = sp;
      }
      state.settlement_operators = new Set(s.settlement_operators);
      state.idempotency_keys = s.idempotency_keys;

      res.writeHead(204);
      return res.end();
    } catch (err) {
      return sendError(res, 400, "malformed_request", "Unparseable body");
    }
  }

  // 5. Auth signup
  if (method === 'POST' && pathname === '/auth/signup') {
    try {
      const body = await parseBody(req);
      if (!body || typeof body.email !== 'string' || typeof body.password !== 'string' || typeof body.display_name !== 'string') {
        return sendError(res, 422, "validation_failed", "Missing/invalid fields");
      }
      if (body.password.length < 8) {
        return sendError(res, 422, "validation_failed", "Password too short");
      }
      if (!/^[^@]+@[^@]+$/.test(body.email)) {
        return sendError(res, 422, "validation_failed", "Invalid email format");
      }
      const emailLower = body.email.toLowerCase();
      if (state.emails[emailLower]) {
        return sendError(res, 409, "email_taken", "Email already registered");
      }
      const derived = deriveHandle(body.email);
      if (state.handles[derived]) {
        return sendError(res, 409, "handle_taken", "The derived handle is already taken");
      }

      const user_id = `u_${crypto.randomUUID()}`;
      const token = `token_${crypto.randomUUID()}`;
      const passwordHash = bcrypt.hashSync(body.password, 10);

      const newUser = {
        id: user_id,
        email: body.email,
        passwordHash,
        display_name: body.display_name,
        handle: derived,
        balance: 0
      };

      state.users[user_id] = newUser;
      state.emails[emailLower] = user_id;
      state.handles[derived] = user_id;
      state.tokens[token] = user_id;

      return sendJSON(res, 201, {
        user_id,
        display_name: body.display_name,
        token
      });
    } catch (err) {
      return sendError(res, 400, "malformed_request", "Unparseable request body");
    }
  }

  // 6. Auth login
  if (method === 'POST' && pathname === '/auth/login') {
    try {
      const body = await parseBody(req);
      if (!body || typeof body.email !== 'string' || typeof body.password !== 'string') {
        return sendError(res, 422, "validation_failed", "Missing/invalid fields");
      }
      const emailLower = body.email.toLowerCase();
      const userId = state.emails[emailLower];
      if (!userId) {
        return sendError(res, 401, "unauthenticated", "Invalid email or password");
      }
      const user = state.users[userId];
      if (!bcrypt.compareSync(body.password, user.passwordHash)) {
        return sendError(res, 401, "unauthenticated", "Invalid email or password");
      }

      const token = `token_${crypto.randomUUID()}`;
      state.tokens[token] = userId;

      return sendJSON(res, 200, {
        user_id: userId,
        display_name: user.display_name,
        token
      });
    } catch (err) {
      return sendError(res, 400, "malformed_request", "Unparseable request body");
    }
  }

  // Authentication Required endpoints beyond this point
  const user = authenticate(req);
  if (!user) {
    return sendError(res, 401, "unauthenticated", "Missing or invalid bearer token");
  }

  // Handle Idempotency for POST paths
  const idempotentPaths = [
    '/payments',
    '/requests',
    '/splits',
    '/settlements'
  ];
  const isIdempotentPath = idempotentPaths.includes(pathname) || (pathname.startsWith('/requests/') && pathname.endsWith('/pay'));

  let idempotencyKey = null;
  let bodyObj = null;
  let bodyString = '';

  if (method === 'POST' && isIdempotentPath) {
    idempotencyKey = req.headers['idempotency-key'];
    if (idempotencyKey === undefined) {
      return sendError(res, 400, "missing_idempotency_key", "Idempotency-Key header is absent");
    }
    if (idempotencyKey === "" || idempotencyKey.length < 1 || idempotencyKey.length > 255) {
      return sendError(res, 422, "validation_failed", "Invalid Idempotency-Key length");
    }

    // Read body and hash it to identify replays
    try {
      bodyObj = await parseBody(req);
      bodyString = bodyObj ? JSON.stringify(bodyObj) : '';
    } catch (err) {
      return sendError(res, 400, "malformed_request", "Unparseable body");
    }

    const keyLookup = `${user.id}:${idempotencyKey}`;
    const previous = state.idempotency_keys[keyLookup];
    if (previous) {
      if (previous.bodyString === bodyString) {
        res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
        return res.end(JSON.stringify(previous.responseBody));
      } else {
        return sendError(res, 409, "idempotency_key_reuse", "Idempotency key reused with different request body");
      }
    }
  }

  // Register idempotency helper
  function saveIdempotency(status, body) {
    if (idempotencyKey && status >= 200 && status < 300) {
      const keyLookup = `${user.id}:${idempotencyKey}`;
      state.idempotency_keys[keyLookup] = {
        bodyString,
        responseBody: body
      };
    }
  }

  // GET /me
  if (method === 'GET' && pathname === '/me') {
    return sendJSON(res, 200, {
      user_id: user.id,
      display_name: user.display_name,
      handle: user.handle,
      balance: user.balance,
      currency: state.currency,
      minor_units: state.minor_units
    });
  }

  // POST /payments
  if (method === 'POST' && pathname === '/payments') {
    if (!bodyObj || typeof bodyObj.to_handle !== 'string' || bodyObj.amount === undefined) {
      return sendError(res, 422, "validation_failed", "Missing required fields");
    }
    const amount = bodyObj.amount;
    if (typeof amount !== 'number' || amount < 1 || amount > 1000000000 || !Number.isInteger(amount)) {
      return sendError(res, 422, "validation_failed", "Invalid amount");
    }
    const toHandleLower = bodyObj.to_handle.toLowerCase();
    if (toHandleLower === user.handle.toLowerCase()) {
      return sendError(res, 422, "self_payment", "Cannot pay yourself");
    }
    const toUserId = state.handles[toHandleLower];
    if (!toUserId) {
      return sendError(res, 404, "not_found", "Recipient handle not found");
    }
    if (bodyObj.note !== undefined && (typeof bodyObj.note !== 'string' || bodyObj.note.length > 200)) {
      return sendError(res, 422, "validation_failed", "Invalid note");
    }
    if (bodyObj.visibility !== undefined && bodyObj.visibility !== 'public' && bodyObj.visibility !== 'private') {
      return sendError(res, 422, "validation_failed", "Invalid visibility");
    }

    if (user.balance < amount) {
      return sendError(res, 409, "insufficient_funds", "Insufficient funds");
    }

    user.balance -= amount;
    state.users[toUserId].balance += amount;

    const payment_id = `p_${crypto.randomUUID()}`;
    const payment = {
      payment_id,
      from_user_id: user.id,
      from_handle: user.handle,
      to_user_id: toUserId,
      to_handle: state.users[toUserId].handle,
      amount,
      currency: state.currency,
      note: bodyObj.note || "",
      visibility: bodyObj.visibility || "public",
      request_id: null,
      settlement_id: null,
      created_at: getCurrentTimestamp()
    };

    state.payments[payment_id] = payment;
    saveIdempotency(201, payment);
    return sendJSON(res, 201, payment);
  }

  // POST /requests
  if (method === 'POST' && pathname === '/requests') {
    if (!bodyObj || typeof bodyObj.payer_handle !== 'string' || bodyObj.amount === undefined) {
      return sendError(res, 422, "validation_failed", "Missing required fields");
    }
    const amount = bodyObj.amount;
    if (typeof amount !== 'number' || amount < 1 || amount > 1000000000 || !Number.isInteger(amount)) {
      return sendError(res, 422, "validation_failed", "Invalid amount");
    }
    const payerHandleLower = bodyObj.payer_handle.toLowerCase();
    if (payerHandleLower === user.handle.toLowerCase()) {
      return sendError(res, 422, "self_request", "Cannot request from yourself");
    }
    const payerUserId = state.handles[payerHandleLower];
    if (!payerUserId) {
      return sendError(res, 404, "not_found", "Payer handle not found");
    }
    if (bodyObj.note !== undefined && (typeof bodyObj.note !== 'string' || bodyObj.note.length > 200)) {
      return sendError(res, 422, "validation_failed", "Invalid note");
    }

    const request_id = `rq_${crypto.randomUUID()}`;
    const request = {
      request_id,
      requester_id: user.id,
      requester_handle: user.handle,
      payer_id: payerUserId,
      payer_handle: state.users[payerUserId].handle,
      amount,
      currency: state.currency,
      note: bodyObj.note || "",
      status: "pending",
      payment_id: null,
      created_at: getCurrentTimestamp()
    };

    state.requests[request_id] = request;
    saveIdempotency(201, request);
    return sendJSON(res, 201, request);
  }

  // POST /requests/{id}/pay
  if (method === 'POST' && pathname.startsWith('/requests/') && pathname.endsWith('/pay')) {
    const parts = pathname.split('/');
    const requestId = parts[2];
    const request = state.requests[requestId];
    if (!request) {
      return sendError(res, 404, "not_found", "Request not found");
    }
    if (request.payer_id !== user.id) {
      return sendError(res, 403, "forbidden", "Only the payer can pay this request");
    }
    if (request.status !== 'pending') {
      return sendError(res, 409, "request_not_pending", "Request is not pending");
    }
    if (bodyObj && bodyObj.visibility !== undefined && bodyObj.visibility !== 'public' && bodyObj.visibility !== 'private') {
      return sendError(res, 422, "validation_failed", "Invalid visibility");
    }

    if (user.balance < request.amount) {
      return sendError(res, 409, "insufficient_funds", "Insufficient funds");
    }

    user.balance -= request.amount;
    state.users[request.requester_id].balance += request.amount;

    const payment_id = `p_${crypto.randomUUID()}`;
    const payment = {
      payment_id,
      from_user_id: user.id,
      from_handle: user.handle,
      to_user_id: request.requester_id,
      to_handle: request.requester_handle,
      amount: request.amount,
      currency: state.currency,
      note: request.note,
      visibility: (bodyObj && bodyObj.visibility) || "public",
      request_id: request.request_id,
      settlement_id: null,
      created_at: getCurrentTimestamp()
    };

    request.status = "paid";
    request.payment_id = payment_id;
    state.payments[payment_id] = payment;

    saveIdempotency(201, payment);
    return sendJSON(res, 201, payment);
  }

  // POST /requests/{id}/decline
  if (method === 'POST' && pathname.startsWith('/requests/') && pathname.endsWith('/decline')) {
    const parts = pathname.split('/');
    const requestId = parts[2];
    const request = state.requests[requestId];
    if (!request) {
      return sendError(res, 404, "not_found", "Request not found");
    }
    if (request.payer_id !== user.id) {
      return sendError(res, 403, "forbidden", "Only the payer can decline this request");
    }
    if (request.status === 'declined') {
      return sendJSON(res, 200, request);
    }
    if (request.status !== 'pending') {
      return sendError(res, 409, "request_not_pending", "Request is not pending");
    }

    request.status = "declined";
    return sendJSON(res, 200, request);
  }

  // POST /requests/{id}/cancel
  if (method === 'POST' && pathname.startsWith('/requests/') && pathname.endsWith('/cancel')) {
    const parts = pathname.split('/');
    const requestId = parts[2];
    const request = state.requests[requestId];
    if (!request) {
      return sendError(res, 404, "not_found", "Request not found");
    }
    if (request.requester_id !== user.id) {
      return sendError(res, 403, "forbidden", "Only the requester can cancel this request");
    }
    if (request.status === 'cancelled') {
      return sendJSON(res, 200, request);
    }
    if (request.status !== 'pending') {
      return sendError(res, 409, "request_not_pending", "Request is not pending");
    }

    request.status = "cancelled";
    return sendJSON(res, 200, request);
  }

  // GET /requests
  if (method === 'GET' && pathname === '/requests') {
    const direction = parsedUrl.searchParams.get('direction');
    const status = parsedUrl.searchParams.get('status');
    const limitStr = parsedUrl.searchParams.get('limit') || '50';
    const offsetStr = parsedUrl.searchParams.get('offset') || '0';

    if (direction && direction !== 'incoming' && direction !== 'outgoing') {
      return sendError(res, 422, "validation_failed", "Invalid direction");
    }
    if (status && !['pending', 'paid', 'declined', 'cancelled'].includes(status)) {
      return sendError(res, 422, "validation_failed", "Invalid status");
    }

    if (!/^\d+$/.test(limitStr) || !/^\d+$/.test(offsetStr)) {
      return sendError(res, 422, "validation_failed", "Invalid pagination format");
    }
    const limit = parseInt(limitStr, 10);
    const offset = parseInt(offsetStr, 10);

    if (limit < 1 || limit > 200 || offset < 0) {
      return sendError(res, 422, "validation_failed", "Pagination bounds exceeded");
    }

    let list = Object.values(state.requests).filter(r => {
      const isRequester = r.requester_id === user.id;
      const isPayer = r.payer_id === user.id;
      if (!isRequester && !isPayer) return false;

      if (direction === 'incoming' && !isPayer) return false;
      if (direction === 'outgoing' && !isRequester) return false;
      if (status && r.status !== status) return false;

      return true;
    });

    list.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

    const paginated = list.slice(offset, offset + limit);
    const has_more = list.length > offset + limit;

    return sendJSON(res, 200, {
      requests: paginated,
      has_more
    });
  }

  // POST /splits
  if (method === 'POST' && pathname === '/splits') {
    if (!bodyObj || bodyObj.amount === undefined || !Array.isArray(bodyObj.participant_handles)) {
      return sendError(res, 422, "validation_failed", "Missing/invalid fields");
    }
    const amount = bodyObj.amount;
    if (typeof amount !== 'number' || amount < 1 || amount > 1000000000 || !Number.isInteger(amount)) {
      return sendError(res, 422, "validation_failed", "Invalid amount");
    }
    const handlesList = bodyObj.participant_handles;
    if (handlesList.length === 0) {
      return sendError(res, 422, "validation_failed", "Participant handles cannot be empty");
    }

    const uniqueHandles = new Set(handlesList.map(h => h.toLowerCase()));
    if (uniqueHandles.size !== handlesList.length) {
      return sendError(res, 422, "validation_failed", "Duplicate participant handles");
    }

    for (const h of handlesList) {
      if (!state.handles[h.toLowerCase()]) {
        return sendError(res, 404, "not_found", `Handle ${h} not found`);
      }
    }

    if (bodyObj.note !== undefined && (typeof bodyObj.note !== 'string' || bodyObj.note.length > 200)) {
      return sendError(res, 422, "validation_failed", "Invalid note");
    }

    const n = handlesList.length;
    const baseShare = Math.floor(amount / n);
    const remainder = amount % n;

    const shares = [];
    for (let i = 0; i < n; i++) {
      const handle = handlesList[i];
      const shareAmount = baseShare + (i < remainder ? 1 : 0);
      shares.push({ handle, amount: shareAmount });
    }

    const splitRequests = [];
    const created_at = getCurrentTimestamp();

    for (const share of shares) {
      if (share.handle.toLowerCase() === user.handle.toLowerCase()) {
        continue;
      }
      const payerUserId = state.handles[share.handle.toLowerCase()];
      const request_id = `rq_${crypto.randomUUID()}`;
      const request = {
        request_id,
        requester_id: user.id,
        requester_handle: user.handle,
        payer_id: payerUserId,
        payer_handle: state.users[payerUserId].handle,
        amount: share.amount,
        currency: state.currency,
        note: bodyObj.note || "",
        status: "pending",
        payment_id: null,
        created_at
      };
      state.requests[request_id] = request;
      splitRequests.push(request);
    }

    const split_id = `sp_${crypto.randomUUID()}`;
    const splitResult = {
      split_id,
      amount,
      currency: state.currency,
      note: bodyObj.note || "",
      shares,
      requests: splitRequests,
      created_at
    };

    state.splits[split_id] = splitResult;
    saveIdempotency(201, splitResult);
    return sendJSON(res, 201, splitResult);
  }

  // GET /activity
  if (method === 'GET' && pathname === '/activity') {
    const limitStr = parsedUrl.searchParams.get('limit') || '50';
    const offsetStr = parsedUrl.searchParams.get('offset') || '0';

    if (!/^\d+$/.test(limitStr) || !/^\d+$/.test(offsetStr)) {
      return sendError(res, 422, "validation_failed", "Invalid pagination format");
    }
    const limit = parseInt(limitStr, 10);
    const offset = parseInt(offsetStr, 10);

    if (limit < 1 || limit > 200 || offset < 0) {
      return sendError(res, 422, "validation_failed", "Pagination bounds exceeded");
    }

    const list = Object.values(state.payments).filter(p => {
      if (p.visibility === 'public') return true;
      if (p.from_user_id === user.id || p.to_user_id === user.id) return true;
      return false;
    });

    list.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));

    const paginated = list.slice(offset, offset + limit);
    const has_more = list.length > offset + limit;

    return sendJSON(res, 200, {
      payments: paginated,
      has_more
    });
  }

  // POST /settlements
  if (method === 'POST' && pathname === '/settlements') {
    if (!state.settlement_operators.has(user.id)) {
      return sendError(res, 403, "forbidden", "Only authorized operators can submit settlements");
    }

    if (!bodyObj || !Array.isArray(bodyObj.transfers)) {
      return sendError(res, 422, "validation_failed", "Missing/invalid fields");
    }
    const transfers = bodyObj.transfers;
    if (transfers.length < 1 || transfers.length > 32) {
      return sendError(res, 422, "validation_failed", "Batch must have 1..32 transfers");
    }

    const validatedTransfers = [];
    for (const t of transfers) {
      if (!t || typeof t.from_handle !== 'string' || typeof t.to_handle !== 'string' || t.amount === undefined) {
        return sendError(res, 422, "validation_failed", "Malformed transfer object");
      }
      const amount = t.amount;
      if (typeof amount !== 'number' || amount < 1 || amount > 1000000000 || !Number.isInteger(amount)) {
        return sendError(res, 422, "validation_failed", "Invalid amount in transfer");
      }
      const fromHandleLower = t.from_handle.toLowerCase();
      const toHandleLower = t.to_handle.toLowerCase();
      if (fromHandleLower === toHandleLower) {
        return sendError(res, 422, "self_payment", "Cannot pay yourself");
      }
      const fromUserId = state.handles[fromHandleLower];
      const toUserId = state.handles[toHandleLower];
      if (!fromUserId || !toUserId) {
        return sendError(res, 404, "not_found", "Handle not found");
      }
      validatedTransfers.push({
        fromUserId,
        fromHandle: state.users[fromUserId].handle,
        toUserId,
        toHandle: state.users[toUserId].handle,
        amount,
        note: t.note || "",
        visibility: t.visibility || "public"
      });
    }

    const balanceChanges = {};
    for (const vt of validatedTransfers) {
      balanceChanges[vt.fromUserId] = (balanceChanges[vt.fromUserId] || 0) - vt.amount;
      balanceChanges[vt.toUserId] = (balanceChanges[vt.toUserId] || 0) + vt.amount;
    }

    for (const [userId, change] of Object.entries(balanceChanges)) {
      const currentBalance = state.users[userId].balance;
      if (currentBalance + change < 0) {
        return sendError(res, 409, "insufficient_funds", "Settlement cannot leave any balance negative");
      }
    }

    const settlement_id = `set_${crypto.randomUUID()}`;
    const committed_at = getCurrentTimestamp();
    const settlementPayments = [];

    for (const vt of validatedTransfers) {
      state.users[vt.fromUserId].balance -= vt.amount;
      state.users[vt.toUserId].balance += vt.amount;

      const payment_id = `p_${crypto.randomUUID()}`;
      const payment = {
        payment_id,
        from_user_id: vt.fromUserId,
        from_handle: vt.fromHandle,
        to_user_id: vt.toUserId,
        to_handle: vt.toHandle,
        amount: vt.amount,
        currency: state.currency,
        note: vt.note,
        visibility: vt.visibility,
        request_id: null,
        settlement_id,
        created_at: committed_at
      };
      state.payments[payment_id] = payment;
      settlementPayments.push(payment);
    }

    const responsePayload = {
      settlement_id,
      committed_at,
      payments: settlementPayments
    };

    saveIdempotency(201, responsePayload);
    return sendJSON(res, 201, responsePayload);
  }

  return sendError(res, 404, "not_found", "Route not found");
});

const port = process.env.PORT || 8080;
server.listen(port, '0.0.0.0', () => {
  console.log(`Server listening on port ${port}`);
});
