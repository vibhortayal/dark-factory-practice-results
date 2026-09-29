import * as bcrypt from 'bcryptjs';
import { ServiceState, User, Token, Payment, MoneyRequest, Split, Settlement, IdempotencyRecord, Fixture } from './types';

export class Store {
  private state: ServiceState;

  constructor() {
    this.state = {
      currency: 'EUR',
      minor_units: 2,
      users: [],
      tokens: [],
      payments: [],
      requests: [],
      splits: [],
      settlements: [],
      settlement_operator_ids: [],
      idempotency_records: []
    };
  }

  // User management
  createUser(id: string, email: string, password: string, display_name: string, handle: string, balance: number = 0): User {
    const password_hash = bcrypt.hashSync(password, 10);
    const user: User = {
      id,
      email,
      password_hash,
      display_name,
      handle,
      balance,
      created_at: new Date().toISOString()
    };
    this.state.users.push(user);
    return user;
  }

  getUserById(id: string): User | undefined {
    return this.state.users.find(u => u.id === id);
  }

  getUserByEmail(email: string): User | undefined {
    return this.state.users.find(u => u.email === email);
  }

  getUserByHandle(handle: string): User | undefined {
    return this.state.users.find(u => u.handle === handle);
  }

  getUserIdByHandle(handle: string): string | undefined {
    const user = this.getUserByHandle(handle);
    return user?.id;
  }

  getAllUsers(): User[] {
    return this.state.users;
  }

  updateUserBalance(userId: string, delta: number): void {
    const user = this.getUserById(userId);
    if (user) {
      user.balance += delta;
    }
  }

  // Token management
  createToken(user_id: string, token: string): Token {
    const tokenRecord: Token = { user_id, token };
    this.state.tokens.push(tokenRecord);
    return tokenRecord;
  }

  getUserByToken(token: string): User | undefined {
    const tokenRecord = this.state.tokens.find(t => t.token === token);
    if (!tokenRecord) return undefined;
    return this.getUserById(tokenRecord.user_id);
  }

  // Payment management
  createPayment(id: string, from_user_id: string, from_handle: string, to_user_id: string, to_handle: string, amount: number, note: string, visibility: 'public' | 'private', request_id?: string | null, settlement_id?: string | null): Payment {
    const payment: Payment = {
      id,
      from_user_id,
      from_handle,
      to_user_id,
      to_handle,
      amount,
      note,
      visibility,
      request_id: request_id ?? null,
      settlement_id: settlement_id ?? null,
      created_at: new Date().toISOString()
    };
    this.state.payments.push(payment);
    return payment;
  }

  getPaymentById(id: string): Payment | undefined {
    return this.state.payments.find(p => p.id === id);
  }

  getAllPayments(): Payment[] {
    return this.state.payments;
  }

  // Request management
  createRequest(id: string, requester_id: string, requester_handle: string, payer_id: string, payer_handle: string, amount: number, note: string): MoneyRequest {
    const request: MoneyRequest = {
      id,
      requester_id,
      requester_handle,
      payer_id,
      payer_handle,
      amount,
      note,
      status: 'pending',
      payment_id: null,
      created_at: new Date().toISOString()
    };
    this.state.requests.push(request);
    return request;
  }

  getRequestById(id: string): MoneyRequest | undefined {
    return this.state.requests.find(r => r.id === id);
  }

  getRequestsByUser(user_id: string, direction?: 'incoming' | 'outgoing', status?: string): MoneyRequest[] {
    return this.state.requests.filter(r => {
      if (direction === 'incoming' && r.payer_id !== user_id) return false;
      if (direction === 'outgoing' && r.requester_id !== user_id) return false;
      if (direction && direction !== 'incoming' && direction !== 'outgoing') return false;
      if (direction && r.requester_id !== user_id && r.payer_id !== user_id) return false;
      if (status && r.status !== status) return false;
      return r.requester_id === user_id || r.payer_id === user_id;
    });
  }

  updateRequestStatus(id: string, status: string, payment_id?: string): void {
    const request = this.getRequestById(id);
    if (request) {
      request.status = status as any;
      if (payment_id) {
        request.payment_id = payment_id;
      }
    }
  }

  // Split management
  createSplit(id: string, requester_id: string, amount: number, note: string, shares: Array<{ handle: string; amount: number }>, request_ids: string[]): Split {
    const split: Split = {
      id,
      requester_id,
      amount,
      currency: this.state.currency,
      note,
      shares,
      request_ids,
      created_at: new Date().toISOString()
    };
    this.state.splits.push(split);
    return split;
  }

  // Settlement management
  createSettlement(id: string, operator_id: string, payment_ids: string[]): Settlement {
    const settlement: Settlement = {
      id,
      operator_id,
      payment_ids,
      committed_at: new Date().toISOString()
    };
    this.state.settlements.push(settlement);
    return settlement;
  }

  isOperator(user_id: string): boolean {
    return this.state.settlement_operator_ids.includes(user_id);
  }

  // Idempotency
  getIdempotencyRecord(user_id: string, key: string): IdempotencyRecord | undefined {
    return this.state.idempotency_records.find(r => r.user_id === user_id && r.key === key);
  }

  createIdempotencyRecord(key: string, user_id: string, method: string, path: string, body: string, response: unknown, status: number): IdempotencyRecord {
    const record: IdempotencyRecord = {
      key,
      user_id,
      method,
      path,
      body,
      response,
      status
    };
    this.state.idempotency_records.push(record);
    return record;
  }

  // State management
  getState(): ServiceState {
    return JSON.parse(JSON.stringify(this.state));
  }

  setState(newState: ServiceState): void {
    this.state = JSON.parse(JSON.stringify(newState));
  }

  reset(fixture: Fixture): void {
    // Validate balances first
    if (fixture.users) {
      for (const user of fixture.users) {
        if (user.balance < 0) {
          throw new Error('validation_failed');
        }
      }
    }

    const now = new Date().toISOString();
    this.state = {
      currency: fixture.currency,
      minor_units: fixture.minor_units,
      users: [],
      tokens: [],
      payments: [],
      requests: [],
      splits: [],
      settlements: [],
      settlement_operator_ids: fixture.settlement_operator_ids || [],
      idempotency_records: []
    };

    // Add users
    if (fixture.users) {
      for (const user of fixture.users) {
        const password_hash = bcrypt.hashSync(user.password, 10);
        this.state.users.push({
          id: user.id,
          email: user.email,
          password_hash,
          display_name: user.display_name,
          handle: user.handle,
          balance: user.balance,
          created_at: now
        });
      }
    }

    // Add payments
    if (fixture.payments) {
      for (const payment of fixture.payments) {
        const fromUser = this.state.users.find(u => u.id === payment.from_user_id);
        const toUser = this.state.users.find(u => u.id === payment.to_user_id);
        if (fromUser && toUser) {
          this.state.payments.push({
            id: payment.id,
            from_user_id: payment.from_user_id,
            from_handle: fromUser.handle,
            to_user_id: payment.to_user_id,
            to_handle: toUser.handle,
            amount: payment.amount,
            note: payment.note || '',
            visibility: payment.visibility,
            request_id: null,
            settlement_id: null,
            created_at: now
          });
        }
      }
    }

    // Add requests
    if (fixture.requests) {
      for (const req of fixture.requests) {
        const requester = this.state.users.find(u => u.id === req.requester_id);
        const payer = this.state.users.find(u => u.id === req.payer_id);
        if (requester && payer) {
          this.state.requests.push({
            id: req.id,
            requester_id: req.requester_id,
            requester_handle: requester.handle,
            payer_id: req.payer_id,
            payer_handle: payer.handle,
            amount: req.amount,
            note: req.note || '',
            status: req.status,
            payment_id: null,
            created_at: now
          });
        }
      }
    }
  }

  getCurrency(): string {
    return this.state.currency;
  }

  getMinorUnits(): number {
    return this.state.minor_units;
  }

  getPaymentsBySettlementId(settlement_id: string): Payment[] {
    return this.state.payments.filter(p => p.settlement_id === settlement_id);
  }

  getTotalBalance(): number {
    return this.state.users.reduce((sum, user) => sum + user.balance, 0);
  }
}

export const store = new Store();
