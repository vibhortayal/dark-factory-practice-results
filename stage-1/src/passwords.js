import { scrypt, randomBytes, timingSafeEqual } from 'node:crypto';

// scrypt from the standard library, run on the libuv threadpool (never blocks the event loop).
// The hash string carries its own parameters so cost can differ between seeding and signup.
const run = (password, salt, N, r, p) =>
  new Promise((resolve, reject) =>
    scrypt(password.normalize('NFKC'), salt, 32, { N, r, p, maxmem: 256 * 1024 * 1024 }, (e, k) => (e ? reject(e) : resolve(k))),
  );

export async function hashPassword(password, N = 16384) {
  const salt = randomBytes(16);
  const key = await run(password, salt, N, 8, 1);
  return `scrypt$${N}$8$1$${salt.toString('base64')}$${key.toString('base64')}`;
}

export function validHashFormat(h) {
  if (typeof h !== 'string') return false;
  const parts = h.split('$');
  return parts.length === 6 && parts[0] === 'scrypt' && [1, 2, 3].every((i) => /^\d+$/.test(parts[i]));
}

export async function verifyPassword(password, stored) {
  if (!validHashFormat(stored)) return false;
  const [, N, r, p, salt, hash] = stored.split('$');
  try {
    const expect = Buffer.from(hash, 'base64');
    const got = await run(password, Buffer.from(salt, 'base64'), Number(N), Number(r), Number(p));
    return got.length === expect.length && timingSafeEqual(got, expect);
  } catch {
    return false;
  }
}
