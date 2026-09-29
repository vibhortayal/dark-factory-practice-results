import * as bcrypt from 'bcryptjs';
import { randomBytes } from 'crypto';
import { store } from './models';
import { errors } from './errors';

// Generate a random token
export function generateToken(): string {
  return randomBytes(32).toString('hex');
}

// Validate email format
export function isValidEmail(email: string): boolean {
  const emailRegex = /^[^@]+@[^@]+$/;
  return emailRegex.test(email);
}

// Validate password length
export function isValidPassword(password: string): boolean {
  return password.length >= 8;
}

// Validate handle format
export function isValidHandle(handle: string): boolean {
  const handleRegex = /^[a-z0-9_]{1,20}$/;
  return handleRegex.test(handle);
}

// Derive handle from email
export function deriveHandle(email: string): string {
  const localPart = email.split('@')[0];
  let handle = localPart.toLowerCase().replace(/[^a-z0-9_]/g, '_');
  handle = handle.substring(0, 20);
  return handle;
}

// Verify password
export function verifyPassword(password: string, hash: string): boolean {
  return bcrypt.compareSync(password, hash);
}

// Generate unique ID
export function generateId(prefix: string): string {
  const random = Math.random().toString(36).substring(2, 15);
  return `${prefix}_${random}`;
}

// Signup logic
export function signup(email: string, password: string, display_name: string) {
  // Validation
  if (!isValidEmail(email)) {
    throw errors.validationFailed('Invalid email format');
  }

  if (!isValidPassword(password)) {
    throw errors.validationFailed('Password must be at least 8 characters');
  }

  if (store.getUserByEmail(email)) {
    throw errors.emailTaken();
  }

  const handle = deriveHandle(email);

  if (!isValidHandle(handle)) {
    throw errors.validationFailed('Invalid handle');
  }

  if (store.getUserByHandle(handle)) {
    throw errors.handleTaken();
  }

  // Create user
  const user_id = generateId('u');
  const user = store.createUser(user_id, email, password, display_name, handle);

  // Create token
  const token = generateToken();
  store.createToken(user_id, token);

  return {
    user_id: user.id,
    display_name: user.display_name,
    token
  };
}

// Login logic
export function login(email: string, password: string) {
  const user = store.getUserByEmail(email);

  if (!user || !verifyPassword(password, user.password_hash)) {
    throw errors.unauthenticated();
  }

  // Create new token
  const token = generateToken();
  store.createToken(user.id, token);

  return {
    user_id: user.id,
    display_name: user.display_name,
    token
  };
}
