'use strict';

const crypto = require('crypto');

// scrypt, salted per user. N is kept modest so that hashing a few hundred
// fixture users stays far inside the 10 s reset limit on 2 vCPU.
const PARAMS = { N: 4096, r: 8, p: 1 };
const KEYLEN = 32;

function scrypt(password, salt, params) {
  return new Promise((resolve, reject) => {
    crypto.scrypt(
      Buffer.from(password, 'utf8'),
      salt,
      KEYLEN,
      { N: params.N, r: params.r, p: params.p, maxmem: 64 * 1024 * 1024 },
      (err, key) => (err ? reject(err) : resolve(key)),
    );
  });
}

/** Returns a JSON-safe record: {salt, hash, N, r, p}. */
async function hashPassword(password) {
  const salt = crypto.randomBytes(16);
  const key = await scrypt(password, salt, PARAMS);
  return { salt: salt.toString('hex'), hash: key.toString('hex'), ...PARAMS };
}

async function verifyPassword(password, record) {
  const key = await scrypt(password, Buffer.from(record.salt, 'hex'), record);
  const want = Buffer.from(record.hash, 'hex');
  return key.length === want.length && crypto.timingSafeEqual(key, want);
}

/** Shape check for a stored record (used when importing state). */
function isValidRecord(r) {
  return (
    r && typeof r === 'object' &&
    typeof r.salt === 'string' && /^[0-9a-f]{32}$/.test(r.salt) &&
    typeof r.hash === 'string' && /^[0-9a-f]{64}$/.test(r.hash) &&
    Number.isInteger(r.N) && r.N >= 2 && r.N <= 16384 && (r.N & (r.N - 1)) === 0 &&
    Number.isInteger(r.r) && r.r >= 1 && r.r <= 8 &&
    Number.isInteger(r.p) && r.p >= 1 && r.p <= 4
  );
}

module.exports = { hashPassword, verifyPassword, isValidRecord };
