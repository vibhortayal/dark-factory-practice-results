"""The planner against an independent brute-force oracle on random instances."""
import itertools
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.planner import Booking, solve  # noqa: E402


def brute(bookings):
    """Enumerate every combination of options; lexicographic minimum of (moved, unused, ranks)."""
    best = None
    for combo in itertools.product(*[b.options for b in bookings]):
        ok = True
        for i, j in itertools.combinations(range(len(bookings)), 2):
            a, b = bookings[i], bookings[j]
            if a.start < b.end and b.start < a.end and set(combo[i][1]) & set(combo[j][1]):
                ok = False
                break
        if not ok:
            continue
        moved = sum(frozenset(c[1]) != b.current for c, b in zip(combo, bookings))
        unused = sum(c[2] - b.party for c, b in zip(combo, bookings))
        key = (moved, unused, tuple(c[0] for c in combo))
        if best is None or key < best[0]:
            best = (key, {b.ref: c[1] for c, b in zip(combo, bookings)})
    return None if best is None else best[1]


class PlannerOracle(unittest.TestCase):
    def test_random_instances(self):
        rng = random.Random(4)
        for n in range(400):
            tables = [f"t{i}" for i in range(rng.randint(2, 6))]
            caps = {t: rng.randint(1, 8) for t in tables}
            sets = [(t,) for t in tables] + [tuple(p) for p in rng.sample(list(itertools.combinations(tables, 2)),
                                                                           min(4, len(tables) * (len(tables) - 1) // 2))]
            bookings = []
            for k in range(rng.randint(0, 6)):
                party = rng.randint(1, 10)
                s = rng.randint(0, 6)
                opts = [(r, ids, sum(caps[t] for t in ids)) for r, ids in enumerate(sets)
                        if sum(caps[t] for t in ids) >= party and rng.random() < 0.8]
                cur = rng.choice(sets)
                bookings.append(Booking(f"R{k:02d}", s, s + rng.randint(1, 4), party, cur, opts))
            expected, got = brute(bookings), solve(bookings)
            self.assertEqual(got, expected, f"instance {n}")

    def test_limit_instance_is_fast(self):
        import time
        tables = [f"t{i}" for i in range(6)]
        sets = [(t,) for t in tables] + [("t0", "t1"), ("t1", "t2"), ("t2", "t3"), ("t4", "t5")]
        bookings = [Booking(f"R{k}", 0, 3, 2, sets[k], [(r, ids, 4 * len(ids)) for r, ids in enumerate(sets)]) for k in range(6)]
        t = time.time()
        self.assertEqual(len(solve(bookings)), 6)
        self.assertLess(time.time() - t, 2)


if __name__ == "__main__":
    unittest.main()
