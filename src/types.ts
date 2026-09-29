export type Visibility = 'public' | 'private';
export type RequestStatus = 'pending' | 'paid' | 'declined' | 'cancelled';
export type Direction = 'incoming' | 'outgoing';

export interface User {
  id: string;
  email: string;
  password_hash: string;
  display_name: string;
  handle: string;
  balance: number;
  created_at: string;
}

export interface Token {
  user_id: string;
  token: string;
}

export interface Payment {
  id: string;
  from_user_id: string;
  from_handle: string;
  to_user_id: string;
  to_handle: string;
  amount: number;
  note: string;
  visibility: Visibility;
  request_id: string | null;
  settlement_id: string | null;
  created_at: string;
}

export interface MoneyRequest {
  id: string;
  requester_id: string;
  requester_handle: string;
  payer_id: string;
  payer_handle: string;
  amount: number;
  note: string;
  status: RequestStatus;
  payment_id: string | null;
  created_at: string;
}

export interface Split {
  id: string;
  requester_id: string;
  amount: number;
  currency: string;
  note: string;
  shares: Array<{ handle: string; amount: number }>;
  request_ids: string[];
  created_at: string;
}

export interface Settlement {
  id: string;
  operator_id: string;
  payment_ids: string[];
  committed_at: string;
}

export interface IdempotencyRecord {
  key: string;
  user_id: string;
  method: string;
  path: string;
  body: string;
  response: unknown;
  status: number;
}

export interface ServiceState {
  currency: string;
  minor_units: number;
  users: User[];
  tokens: Token[];
  payments: Payment[];
  requests: MoneyRequest[];
  splits: Split[];
  settlements: Settlement[];
  settlement_operator_ids: string[];
  idempotency_records: IdempotencyRecord[];
}

export interface Fixture {
  currency: string;
  minor_units: number;
  users?: Array<{
    id: string;
    email: string;
    password: string;
    display_name: string;
    handle: string;
    balance: number;
  }>;
  payments?: Array<{
    id: string;
    from_user_id: string;
    to_user_id: string;
    amount: number;
    note?: string;
    visibility: Visibility;
  }>;
  requests?: Array<{
    id: string;
    requester_id: string;
    payer_id: string;
    amount: number;
    note?: string;
    status: RequestStatus;
  }>;
  settlement_operator_ids?: string[];
}

export interface ExportedState {
  track: string;
  format_version: number;
  state: ServiceState;
}

export interface ErrorResponse {
  error: {
    code: string;
    message: string;
  };
}

export interface AuthRequest {
  email: string;
  password: string;
  display_name?: string;
}

export interface PaymentRequest {
  to_handle: string;
  amount: number;
  note?: string;
  visibility?: Visibility;
}

export interface MoneyRequestRequest {
  payer_handle: string;
  amount: number;
  note?: string;
}

export interface PayRequestRequest {
  visibility?: Visibility;
}

export interface SplitRequest {
  amount: number;
  participant_handles: string[];
  note?: string;
}

export interface SettlementRequest {
  transfers: Array<{
    from_handle: string;
    to_handle: string;
    amount: number;
    note?: string;
    visibility?: Visibility;
  }>;
}

export interface ShareInfo {
  handle: string;
  amount: number;
}
