import express, { Request, Response, NextFunction } from 'express';
import { store } from './models';
import { errors, sendError, handleError } from './errors';
import { signup, login, generateToken, generateId, isValidEmail, isValidPassword, isValidHandle, deriveHandle } from './auth';
import { User, Fixture, ExportedState, PaymentRequest, MoneyRequestRequest, PayRequestRequest, SplitRequest, SettlementRequest, Payment, MoneyRequest } from './types';
import { formatTimestamp, normalizeJsonBody, validateServiceState } from './utils';

const app = express();
app.use(express.json({ limit: '10mb' }));

const PORT = parseInt(process.env.PORT || '8080', 10);

// Middleware
interface AuthRequest extends Request {
  user?: User;
  idempotencyKey?: string;
}

const authMiddleware = (req: AuthRequest, res: Response, next: NextFunction) => {
  const token = req.headers.authorization?.replace('Bearer ', '');
  if (!token) {
    return sendError(res, 401, 'unauthenticated', 'Missing bearer token');
  }
  const user = store.getUserByToken(token);
  if (!user) {
    return sendError(res, 401, 'unauthenticated', 'Invalid token');
  }
  req.user = user;
  next();
};

const idempotencyMiddleware = (req: AuthRequest, res: Response, next: NextFunction) => {
  if (['POST', 'PUT', 'PATCH'].includes(req.method)) {
    const key = req.headers['idempotency-key'] as string;
    if (key) {
      req.idempotencyKey = key;
    }
  }
  next();
};

app.use(idempotencyMiddleware);

// Health check
app.get('/health', (req, res) => {
  res.json({ status: 'ok' });
});

// Auth endpoints
app.post('/auth/signup', (req: Request, res: Response) => {
  try {
    const { email, password, display_name } = req.body;

    if (!email || !password || !display_name) {
      return sendError(res, 422, 'validation_failed', 'Missing required fields');
    }

    const result = signup(email, password, display_name);
    res.status(201).json(result);
  } catch (error: any) {
    handleError(res, error);
  }
});

app.post('/auth/login', (req: Request, res: Response) => {
  try {
    const { email, password } = req.body;

    if (!email || !password) {
      return sendError(res, 422, 'validation_failed', 'Missing required fields');
    }

    const result = login(email, password);
    res.status(200).json(result);
  } catch (error: any) {
    handleError(res, error);
  }
});

// User endpoints
app.get('/me', authMiddleware, (req: AuthRequest, res: Response) => {
  try {
    if (!req.user) {
      return sendError(res, 401, 'unauthenticated', 'Unauthenticated');
    }

    res.json({
      user_id: req.user.id,
      display_name: req.user.display_name,
      handle: req.user.handle,
      balance: req.user.balance,
      currency: store.getCurrency(),
      minor_units: store.getMinorUnits()
    });
  } catch (error: any) {
    handleError(res, error);
  }
});

// Payments
app.post('/payments', authMiddleware, (req: AuthRequest, res: Response) => {
  try {
    if (!req.user) {
      return sendError(res, 401, 'unauthenticated', 'Unauthenticated');
    }

    const { to_handle, amount, note = '', visibility = 'public' } = req.body;
    const idempotencyKey = req.idempotencyKey;

    // Idempotency check
    if (!idempotencyKey) {
      return sendError(res, 400, 'missing_idempotency_key', 'Idempotency-Key header is required');
    }

    const requestBody = normalizeJsonBody(JSON.stringify(req.body));
    const existingRecord = store.getIdempotencyRecord(req.user.id, idempotencyKey, req.method, '/payments');
    if (existingRecord) {
      if (existingRecord.body !== requestBody) {
        return sendError(res, 409, 'idempotency_key_reuse', 'Idempotency key reuse with different body');
      }
      return res.status(200).json(existingRecord.response);
    }

    // Validation
    if (!to_handle || typeof to_handle !== 'string') {
      return sendError(res, 422, 'validation_failed', 'Invalid to_handle');
    }

    if (typeof amount !== 'number' || !Number.isInteger(amount) || amount < 1 || amount > 1000000000) {
      return sendError(res, 422, 'validation_failed', 'Invalid amount');
    }

    if (typeof note !== 'string' || note.length > 200) {
      return sendError(res, 422, 'validation_failed', 'Invalid note');
    }

    if (visibility !== 'public' && visibility !== 'private') {
      return sendError(res, 422, 'validation_failed', 'Invalid visibility');
    }

    if (to_handle === req.user.handle) {
      return sendError(res, 422, 'self_payment', 'Cannot send payment to yourself');
    }

    const toUser = store.getUserByHandle(to_handle);
    if (!toUser) {
      return sendError(res, 404, 'not_found', 'User not found');
    }

    if (req.user.balance < amount) {
      return sendError(res, 409, 'insufficient_funds', 'Insufficient funds');
    }

    // Create payment
    const payment_id = generateId('p');
    store.updateUserBalance(req.user.id, -amount);
    store.updateUserBalance(toUser.id, amount);

    const payment = store.createPayment(
      payment_id,
      req.user.id,
      req.user.handle,
      toUser.id,
      toUser.handle,
      amount,
      note,
      visibility
    );

    const response = {
      payment_id: payment.id,
      from_user_id: payment.from_user_id,
      from_handle: payment.from_handle,
      to_user_id: payment.to_user_id,
      to_handle: payment.to_handle,
      amount: payment.amount,
      currency: store.getCurrency(),
      note: payment.note,
      visibility: payment.visibility,
      request_id: payment.request_id,
      created_at: payment.created_at
    };

    store.createIdempotencyRecord(idempotencyKey, req.user.id, 'POST', '/payments', requestBody, response, 201);
    res.status(201).json(response);
  } catch (error: any) {
    handleError(res, error);
  }
});

app.get('/activity', authMiddleware, (req: AuthRequest, res: Response) => {
  try {
    if (!req.user) {
      return sendError(res, 401, 'unauthenticated', 'Unauthenticated');
    }

    let limit = 50;
    let offset = 0;

    if (req.query.limit) {
      const limitNum = Number(req.query.limit);
      if (!Number.isInteger(limitNum) || limitNum < 1 || limitNum > 200) {
        return sendError(res, 422, 'validation_failed', 'Invalid limit');
      }
      limit = limitNum;
    }

    if (req.query.offset) {
      const offsetNum = Number(req.query.offset);
      if (!Number.isInteger(offsetNum) || offsetNum < 0) {
        return sendError(res, 422, 'validation_failed', 'Invalid offset');
      }
      offset = offsetNum;
    }

    // Get visible payments
    const allPayments = store.getAllPayments();
    const visiblePayments = allPayments.filter(p => 
      p.visibility === 'public' || p.from_user_id === req.user!.id || p.to_user_id === req.user!.id
    );

    // Sort by created_at descending
    visiblePayments.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

    const payments = visiblePayments.slice(offset, offset + limit);
    const has_more = offset + limit < visiblePayments.length;

    const response = {
      payments: payments.map(p => ({
        payment_id: p.id,
        from_user_id: p.from_user_id,
        from_handle: p.from_handle,
        to_user_id: p.to_user_id,
        to_handle: p.to_handle,
        amount: p.amount,
        currency: store.getCurrency(),
        note: p.note,
        visibility: p.visibility,
        request_id: p.request_id,
        settlement_id: p.settlement_id,
        created_at: p.created_at
      })),
      has_more
    };

    res.json(response);
  } catch (error: any) {
    handleError(res, error);
  }
});

// Requests
app.post('/requests', authMiddleware, (req: AuthRequest, res: Response) => {
  try {
    if (!req.user) {
      return sendError(res, 401, 'unauthenticated', 'Unauthenticated');
    }

    const { payer_handle, amount, note = '' } = req.body;
    const idempotencyKey = req.idempotencyKey;

    if (!idempotencyKey) {
      return sendError(res, 400, 'missing_idempotency_key', 'Idempotency-Key header is required');
    }

    const requestBody = normalizeJsonBody(JSON.stringify(req.body));
    const existingRecord = store.getIdempotencyRecord(req.user.id, idempotencyKey, req.method, '/requests');
    if (existingRecord) {
      if (existingRecord.body !== requestBody) {
        return sendError(res, 409, 'idempotency_key_reuse', 'Idempotency key reuse with different body');
      }
      return res.status(200).json(existingRecord.response);
    }

    // Validation
    if (!payer_handle || typeof payer_handle !== 'string') {
      return sendError(res, 422, 'validation_failed', 'Invalid payer_handle');
    }

    if (typeof amount !== 'number' || !Number.isInteger(amount) || amount < 1 || amount > 1000000000) {
      return sendError(res, 422, 'validation_failed', 'Invalid amount');
    }

    if (typeof note !== 'string' || note.length > 200) {
      return sendError(res, 422, 'validation_failed', 'Invalid note');
    }

    if (payer_handle === req.user.handle) {
      return sendError(res, 422, 'self_request', 'Cannot request payment from yourself');
    }

    const payerUser = store.getUserByHandle(payer_handle);
    if (!payerUser) {
      return sendError(res, 404, 'not_found', 'User not found');
    }

    // Create request
    const request_id = generateId('rq');
    const request = store.createRequest(
      request_id,
      req.user.id,
      req.user.handle,
      payerUser.id,
      payerUser.handle,
      amount,
      note
    );

    const response = {
      request_id: request.id,
      requester_id: request.requester_id,
      requester_handle: request.requester_handle,
      payer_id: request.payer_id,
      payer_handle: request.payer_handle,
      amount: request.amount,
      currency: store.getCurrency(),
      note: request.note,
      status: request.status,
      payment_id: request.payment_id,
      created_at: request.created_at
    };

    store.createIdempotencyRecord(idempotencyKey, req.user.id, 'POST', '/requests', requestBody, response, 201);
    res.status(201).json(response);
  } catch (error: any) {
    handleError(res, error);
  }
});

app.get('/requests', authMiddleware, (req: AuthRequest, res: Response) => {
  try {
    if (!req.user) {
      return sendError(res, 401, 'unauthenticated', 'Unauthenticated');
    }

    let limit = 50;
    let offset = 0;
    let direction: string | undefined = undefined;
    let status: string | undefined = undefined;

    if (req.query.limit) {
      const limitNum = Number(req.query.limit);
      if (!Number.isInteger(limitNum) || limitNum < 1 || limitNum > 200) {
        return sendError(res, 422, 'validation_failed', 'Invalid limit');
      }
      limit = limitNum;
    }

    if (req.query.offset) {
      const offsetNum = Number(req.query.offset);
      if (!Number.isInteger(offsetNum) || offsetNum < 0) {
        return sendError(res, 422, 'validation_failed', 'Invalid offset');
      }
      offset = offsetNum;
    }

    if (req.query.direction) {
      direction = req.query.direction as string;
      if (direction !== 'incoming' && direction !== 'outgoing') {
        return sendError(res, 422, 'validation_failed', 'Invalid direction');
      }
    }

    if (req.query.status) {
      status = req.query.status as string;
      if (status !== 'pending' && status !== 'paid' && status !== 'declined' && status !== 'cancelled') {
        return sendError(res, 422, 'validation_failed', 'Invalid status');
      }
    }

    // Get requests
    let requests = store.getRequestsByUser(req.user.id, direction as any, status);
    
    // Sort by created_at descending
    requests.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

    const pageRequests = requests.slice(offset, offset + limit);
    const has_more = offset + limit < requests.length;

    const response = {
      requests: pageRequests.map(r => ({
        request_id: r.id,
        requester_id: r.requester_id,
        requester_handle: r.requester_handle,
        payer_id: r.payer_id,
        payer_handle: r.payer_handle,
        amount: r.amount,
        currency: store.getCurrency(),
        note: r.note,
        status: r.status,
        payment_id: r.payment_id,
        created_at: r.created_at
      })),
      has_more
    };

    res.json(response);
  } catch (error: any) {
    handleError(res, error);
  }
});

app.post('/requests/:id/pay', authMiddleware, (req: AuthRequest, res: Response) => {
  try {
    if (!req.user) {
      return sendError(res, 401, 'unauthenticated', 'Unauthenticated');
    }

    const { id } = req.params;
    const { visibility = 'public' } = req.body;
    const idempotencyKey = req.idempotencyKey;

    if (!idempotencyKey) {
      return sendError(res, 400, 'missing_idempotency_key', 'Idempotency-Key header is required');
    }

    const requestBody = normalizeJsonBody(JSON.stringify(req.body));
    const existingRecord = store.getIdempotencyRecord(req.user.id, idempotencyKey, req.method, `/requests/${id}/pay`);
    if (existingRecord) {
      if (existingRecord.body !== requestBody) {
        return sendError(res, 409, 'idempotency_key_reuse', 'Idempotency key reuse with different body');
      }
      return res.status(200).json(existingRecord.response);
    }

    // Validation
    if (visibility !== 'public' && visibility !== 'private') {
      return sendError(res, 422, 'validation_failed', 'Invalid visibility');
    }

    const request = store.getRequestById(id);
    if (!request) {
      return sendError(res, 404, 'not_found', 'Request not found');
    }

    if (request.payer_id !== req.user.id) {
      return sendError(res, 403, 'forbidden', 'Only the payer can pay this request');
    }

    if (request.status !== 'pending') {
      return sendError(res, 409, 'request_not_pending', 'Request is not pending');
    }

    if (req.user.balance < request.amount) {
      return sendError(res, 409, 'insufficient_funds', 'Insufficient funds');
    }

    // Create payment
    const payment_id = generateId('p');
    const requesterUser = store.getUserById(request.requester_id);
    if (!requesterUser) {
      return sendError(res, 404, 'not_found', 'Requester not found');
    }

    store.updateUserBalance(req.user.id, -request.amount);
    store.updateUserBalance(requesterUser.id, request.amount);

    const payment = store.createPayment(
      payment_id,
      req.user.id,
      req.user.handle,
      requesterUser.id,
      requesterUser.handle,
      request.amount,
      request.note,
      visibility,
      request.id
    );

    store.updateRequestStatus(request.id, 'paid', payment_id);

    const response = {
      payment_id: payment.id,
      from_user_id: payment.from_user_id,
      from_handle: payment.from_handle,
      to_user_id: payment.to_user_id,
      to_handle: payment.to_handle,
      amount: payment.amount,
      currency: store.getCurrency(),
      note: payment.note,
      visibility: payment.visibility,
      request_id: payment.request_id,
      created_at: payment.created_at
    };

    store.createIdempotencyRecord(idempotencyKey, req.user.id, `POST`, `/requests/${id}/pay`, requestBody, response, 201);
    res.status(201).json(response);
  } catch (error: any) {
    handleError(res, error);
  }
});

app.post('/requests/:id/decline', authMiddleware, (req: AuthRequest, res: Response) => {
  try {
    if (!req.user) {
      return sendError(res, 401, 'unauthenticated', 'Unauthenticated');
    }

    const { id } = req.params;
    const request = store.getRequestById(id);

    if (!request) {
      return sendError(res, 404, 'not_found', 'Request not found');
    }

    if (request.payer_id !== req.user.id) {
      return sendError(res, 403, 'forbidden', 'Only the payer can decline this request');
    }

    if (request.status !== 'pending') {
      return sendError(res, 409, 'request_not_pending', 'Request is not pending');
    }

    store.updateRequestStatus(request.id, 'declined');

    const updatedRequest = store.getRequestById(request.id);
    const response = {
      request_id: updatedRequest!.id,
      requester_id: updatedRequest!.requester_id,
      requester_handle: updatedRequest!.requester_handle,
      payer_id: updatedRequest!.payer_id,
      payer_handle: updatedRequest!.payer_handle,
      amount: updatedRequest!.amount,
      currency: store.getCurrency(),
      note: updatedRequest!.note,
      status: updatedRequest!.status,
      payment_id: updatedRequest!.payment_id,
      created_at: updatedRequest!.created_at
    };

    res.json(response);
  } catch (error: any) {
    handleError(res, error);
  }
});

app.post('/requests/:id/cancel', authMiddleware, (req: AuthRequest, res: Response) => {
  try {
    if (!req.user) {
      return sendError(res, 401, 'unauthenticated', 'Unauthenticated');
    }

    const { id } = req.params;
    const request = store.getRequestById(id);

    if (!request) {
      return sendError(res, 404, 'not_found', 'Request not found');
    }

    if (request.requester_id !== req.user.id) {
      return sendError(res, 403, 'forbidden', 'Only the requester can cancel this request');
    }

    if (request.status !== 'pending') {
      return sendError(res, 409, 'request_not_pending', 'Request is not pending');
    }

    store.updateRequestStatus(request.id, 'cancelled');

    const updatedRequest = store.getRequestById(request.id);
    const response = {
      request_id: updatedRequest!.id,
      requester_id: updatedRequest!.requester_id,
      requester_handle: updatedRequest!.requester_handle,
      payer_id: updatedRequest!.payer_id,
      payer_handle: updatedRequest!.payer_handle,
      amount: updatedRequest!.amount,
      currency: store.getCurrency(),
      note: updatedRequest!.note,
      status: updatedRequest!.status,
      payment_id: updatedRequest!.payment_id,
      created_at: updatedRequest!.created_at
    };

    res.json(response);
  } catch (error: any) {
    handleError(res, error);
  }
});

// Splits
app.post('/splits', authMiddleware, (req: AuthRequest, res: Response) => {
  try {
    if (!req.user) {
      return sendError(res, 401, 'unauthenticated', 'Unauthenticated');
    }

    const { amount, participant_handles, note = '' } = req.body;
    const idempotencyKey = req.idempotencyKey;

    if (!idempotencyKey) {
      return sendError(res, 400, 'missing_idempotency_key', 'Idempotency-Key header is required');
    }

     const requestBody = normalizeJsonBody(JSON.stringify(req.body));
    const existingRecord = store.getIdempotencyRecord(req.user.id, idempotencyKey, req.method, '/splits');
    if (existingRecord) {
      if (existingRecord.body !== requestBody) {
        return sendError(res, 409, 'idempotency_key_reuse', 'Idempotency key reuse with different body');
      }
      return res.status(200).json(existingRecord.response);
    }

    // Validation
    if (typeof amount !== 'number' || !Number.isInteger(amount) || amount < 1 || amount > 1000000000) {
      return sendError(res, 422, 'validation_failed', 'Invalid amount');
    }

    if (!Array.isArray(participant_handles) || participant_handles.length === 0) {
      return sendError(res, 422, 'validation_failed', 'participant_handles must be non-empty array');
    }

    const handlesSet = new Set(participant_handles);
    if (handlesSet.size !== participant_handles.length) {
      return sendError(res, 422, 'validation_failed', 'Duplicate handles in participant_handles');
    }

    if (typeof note !== 'string' || note.length > 200) {
      return sendError(res, 422, 'validation_failed', 'Invalid note');
    }

    // Verify all handles exist
    const users: User[] = [];
    for (const handle of participant_handles) {
      const user = store.getUserByHandle(handle);
      if (!user) {
        return sendError(res, 404, 'not_found', 'User not found');
      }
      users.push(user);
    }

    // Calculate shares
    const n = participant_handles.length;
    const baseShare = Math.floor(amount / n);
    const remainder = amount % n;

    const shares = participant_handles.map((handle, index) => ({
      handle,
      amount: index < remainder ? baseShare + 1 : baseShare
    }));

    // Create requests for non-caller participants
    const request_ids: string[] = [];
    const requestObjs = [];

    for (let i = 0; i < participant_handles.length; i++) {
      const handle = participant_handles[i];
      const user = users[i];
      const share = shares[i].amount;

      if (user.id === req.user.id) {
        // Don't create request for caller
        continue;
      }

      const request_id = generateId('rq');
      const moneyRequest = store.createRequest(
        request_id,
        req.user.id,
        req.user.handle,
        user.id,
        user.handle,
        share,
        note
      );
      request_ids.push(request_id);
      requestObjs.push({
        request_id: moneyRequest.id,
        requester_id: moneyRequest.requester_id,
        requester_handle: moneyRequest.requester_handle,
        payer_id: moneyRequest.payer_id,
        payer_handle: moneyRequest.payer_handle,
        amount: moneyRequest.amount,
        currency: store.getCurrency(),
        note: moneyRequest.note,
        status: moneyRequest.status,
        payment_id: moneyRequest.payment_id,
        created_at: moneyRequest.created_at
      });
    }

    // Create split record
    const split_id = generateId('sp');
    store.createSplit(split_id, req.user.id, amount, note, shares, request_ids);

    const response = {
      split_id,
      amount,
      currency: store.getCurrency(),
      note,
      shares,
      requests: requestObjs,
      created_at: formatTimestamp()
    };

    store.createIdempotencyRecord(idempotencyKey, req.user.id, 'POST', '/splits', requestBody, response, 201);
    res.status(201).json(response);
  } catch (error: any) {
    handleError(res, error);
  }
});

// Settlements
app.post('/settlements', authMiddleware, (req: AuthRequest, res: Response) => {
  try {
    if (!req.user) {
      return sendError(res, 401, 'unauthenticated', 'Unauthenticated');
    }

    const { transfers } = req.body;
    const idempotencyKey = req.idempotencyKey;

    if (!idempotencyKey) {
      return sendError(res, 400, 'missing_idempotency_key', 'Idempotency-Key header is required');
    }

    if (!store.isOperator(req.user.id)) {
      return sendError(res, 403, 'forbidden', 'Only settlement operators can create settlements');
    }

    const requestBody = normalizeJsonBody(JSON.stringify(req.body));
    const existingRecord = store.getIdempotencyRecord(req.user.id, idempotencyKey, req.method, '/settlements');
    if (existingRecord) {
      if (existingRecord.body !== requestBody) {
        return sendError(res, 409, 'idempotency_key_reuse', 'Idempotency key reuse with different body');
      }
      return res.status(200).json(existingRecord.response);
    }

    // Validation
    if (!Array.isArray(transfers) || transfers.length === 0 || transfers.length > 32) {
      return sendError(res, 422, 'validation_failed', 'transfers must be array of 1..32 objects');
    }

    const transfersList: Array<{ from_user: User; to_user: User; amount: number; note: string; visibility: 'public' | 'private' }> = [];

    // Validate and collect transfers
    for (const transfer of transfers) {
      if (!transfer.from_handle || typeof transfer.from_handle !== 'string') {
        return sendError(res, 422, 'validation_failed', 'Invalid from_handle');
      }

      if (!transfer.to_handle || typeof transfer.to_handle !== 'string') {
        return sendError(res, 422, 'validation_failed', 'Invalid to_handle');
      }

      if (typeof transfer.amount !== 'number' || !Number.isInteger(transfer.amount) || transfer.amount < 1 || transfer.amount > 1000000000) {
        return sendError(res, 422, 'validation_failed', 'Invalid amount');
      }

      const note = transfer.note || '';
      if (typeof note !== 'string' || note.length > 200) {
        return sendError(res, 422, 'validation_failed', 'Invalid note');
      }

      const visibility = transfer.visibility || 'public';
      if (visibility !== 'public' && visibility !== 'private') {
        return sendError(res, 422, 'validation_failed', 'Invalid visibility');
      }

      if (transfer.from_handle === transfer.to_handle) {
        return sendError(res, 422, 'self_payment', 'Cannot transfer to yourself');
      }

      const fromUser = store.getUserByHandle(transfer.from_handle);
      if (!fromUser) {
        return sendError(res, 404, 'not_found', 'User not found');
      }

      const toUser = store.getUserByHandle(transfer.to_handle);
      if (!toUser) {
        return sendError(res, 404, 'not_found', 'User not found');
      }

      transfersList.push({
        from_user: fromUser,
        to_user: toUser,
        amount: transfer.amount,
        note,
        visibility
      });
    }

    // Check if settlement is affordable
    const balanceDeltas: { [userId: string]: number } = {};
    for (const transfer of transfersList) {
      if (!balanceDeltas[transfer.from_user.id]) balanceDeltas[transfer.from_user.id] = 0;
      if (!balanceDeltas[transfer.to_user.id]) balanceDeltas[transfer.to_user.id] = 0;
      balanceDeltas[transfer.from_user.id] -= transfer.amount;
      balanceDeltas[transfer.to_user.id] += transfer.amount;
    }

    for (const userId in balanceDeltas) {
      const user = store.getUserById(userId);
      if (user && user.balance + balanceDeltas[userId] < 0) {
        return sendError(res, 409, 'insufficient_funds', 'Settlement would result in negative balance');
      }
    }

    // Execute settlement
    const settlement_id = generateId('st');
    const payment_ids: string[] = [];
    const paymentObjs = [];
    const committedAt = formatTimestamp();

    for (const transfer of transfersList) {
      const payment_id = generateId('p');
      store.updateUserBalance(transfer.from_user.id, -transfer.amount);
      store.updateUserBalance(transfer.to_user.id, transfer.amount);

      const payment = store.createPayment(
        payment_id,
        transfer.from_user.id,
        transfer.from_user.handle,
        transfer.to_user.id,
        transfer.to_user.handle,
        transfer.amount,
        transfer.note,
        transfer.visibility,
        null,
        settlement_id
      );

      // Update payment created_at to match settlement time
      payment.created_at = committedAt;

      payment_ids.push(payment_id);
      paymentObjs.push({
        payment_id: payment.id,
        from_user_id: payment.from_user_id,
        from_handle: payment.from_handle,
        to_user_id: payment.to_user_id,
        to_handle: payment.to_handle,
        amount: payment.amount,
        currency: store.getCurrency(),
        note: payment.note,
        visibility: payment.visibility,
        request_id: null,
        settlement_id: payment.settlement_id,
        created_at: payment.created_at
      });
    }

    store.createSettlement(settlement_id, req.user.id, payment_ids);

    const response = {
      settlement_id,
      committed_at: committedAt,
      payments: paymentObjs
    };

    store.createIdempotencyRecord(idempotencyKey, req.user.id, 'POST', '/settlements', requestBody, response, 201);
    res.status(201).json(response);
  } catch (error: any) {
    handleError(res, error);
  }
});

// Test endpoints
app.post('/_test/reset', (req: Request, res: Response) => {
  try {
    const fixture = req.body as Fixture;

    if (!fixture.currency || typeof fixture.currency !== 'string') {
      return sendError(res, 422, 'validation_failed', 'Invalid currency');
    }

    if (typeof fixture.minor_units !== 'number' || ![0, 2, 3].includes(fixture.minor_units)) {
      return sendError(res, 422, 'validation_failed', 'Invalid minor_units');
    }

    store.reset(fixture);
    res.status(204).send();
  } catch (error: any) {
    if (error.message === 'validation_failed') {
      return sendError(res, 422, 'validation_failed', 'Validation failed');
    }
    handleError(res, error);
  }
});

app.get('/_test/export', (req: Request, res: Response) => {
  try {
    const state = store.getState();
    const response: ExportedState = {
      track: 'pocketful',
      format_version: 1,
      state
    };
    res.json(response);
  } catch (error: any) {
    handleError(res, error);
  }
});

app.post('/_test/import', (req: Request, res: Response) => {
  try {
    const { track, format_version, state } = req.body as ExportedState;

    if (track !== 'pocketful') {
      return sendError(res, 422, 'validation_failed', 'Invalid track');
    }

    if (format_version !== 1) {
      return sendError(res, 422, 'validation_failed', 'Invalid format_version');
    }

    if (!state || !validateServiceState(state)) {
      return sendError(res, 422, 'validation_failed', 'Invalid state');
    }

    store.setState(state);
    res.status(204).send();
  } catch (error: any) {
    handleError(res, error);
  }
});

// Start server
app.listen(PORT, '0.0.0.0', () => {
  console.log(`Pocketful service listening on port ${PORT}`);
});
