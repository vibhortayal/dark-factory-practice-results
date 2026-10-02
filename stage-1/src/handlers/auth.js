'use strict';

const crypto = require('crypto');
const { getState, nextId } = require('../state');
const { invalid, conflict, unauthenticated } = require('../errors');
const { assertTypes, requireField, codePoints } = require('../validation');
const { hashPassword, verifyPassword } = require('../passwords');
const { deriveHandle } = require('../handles');

const EMAIL_RE = /^[^@\s]+@[^@\s]+$/;

function issueToken(state, userId) {
  const token = crypto.randomBytes(32).toString('hex');
  state.tokens.set(token, userId);
  return token;
}

async function signup({ body }) {
  assertTypes(body, { email: 'string', password: 'string', display_name: 'string' });
  const email = requireField(body, 'email');
  const password = requireField(body, 'password');
  const displayName = requireField(body, 'display_name');
  if (!EMAIL_RE.test(email)) throw invalid('email must look like local@domain');
  if (codePoints(password) < 8) throw invalid('password must be at least 8 characters');

  const handle = deriveHandle(email);
  const checkFree = (state) => {
    if (state.byEmail.has(email)) throw conflict('email_taken', 'email already registered');
    if (state.byHandle.has(handle)) throw conflict('handle_taken', 'handle already taken');
  };
  checkFree(getState());
  const hashed = await hashPassword(password);

  // Re-read the state: another signup may have won while we were hashing.
  const state = getState();
  checkFree(state);
  const user = {
    id: nextId(state, 'user', 'u_', state.users),
    email, display_name: displayName, handle, balance: 0, initial_balance: 0, password: hashed,
  };
  state.users.set(user.id, user);
  state.byHandle.set(handle, user);
  state.byEmail.set(email, user);
  return { status: 201, body: { user_id: user.id, display_name: user.display_name, token: issueToken(state, user.id) } };
}

async function login({ body }) {
  assertTypes(body, { email: 'string', password: 'string' });
  const email = requireField(body, 'email');
  const password = requireField(body, 'password');
  const user = getState().byEmail.get(email);
  if (!user || !(await verifyPassword(password, user.password))) throw unauthenticated('wrong email or password');
  const state = getState();
  if (state.users.get(user.id) !== user) throw unauthenticated('wrong email or password');
  return { status: 200, body: { user_id: user.id, display_name: user.display_name, token: issueToken(state, user.id) } };
}

module.exports = { signup, login };
