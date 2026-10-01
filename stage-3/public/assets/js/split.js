// Equal-split rule (stage-1 spec section 9). One module, imported by the server ledger and by
// the browser split preview so the two can never disagree.
//
// Shares are whole minor units, sum to `amount`, and differ by at most one unit; the first
// (amount mod n) participants receive the extra unit.
export function equalShares(amount, n) {
  const base = Math.floor(amount / n);
  const extra = amount % n;
  return Array.from({ length: n }, (_, i) => base + (i < extra ? 1 : 0));
}
