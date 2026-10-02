'use strict';

/** Handle derived from an email's local part (spec §4). */
function deriveHandle(email) {
  const at = email.indexOf('@');
  const local = at === -1 ? email : email.slice(0, at);
  return Array.from(local.toLowerCase(), (ch) => (/^[a-z0-9_]$/.test(ch) ? ch : '_'))
    .join('')
    .slice(0, 20);
}

module.exports = { deriveHandle };
