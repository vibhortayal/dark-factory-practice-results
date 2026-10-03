"""Exact seating planner (spec stage 4).

Input: considered bookings, each with its time interval, party size, current table set
and the list of options it may use (already filtered for capacity, closures and fixed
bookings). Output: the assignment minimising, in order, (1) bookings whose table set
changes, (2) total unused seats, (3) the vector of option ranks in ascending reference
order.

Bookings that cannot influence each other (no overlapping interval with a shared
candidate table) form independent components; because the objective is a lexicographic
sum over bookings, minimising each component on its own is exact. Each component is
searched depth-first in reference order with branch and bound; a node budget turns
an oversized instance into PlanningLimit rather than a slow request.
"""

NODE_BUDGET = 150_000


class PlanningLimit(Exception):
    pass


class Booking:
    """ref, start, end (comparable instants), party, current (frozenset of table ids),
    options: list of (rank, tuple_of_table_ids, capacity) in ascending rank."""

    def __init__(self, ref, start, end, party, current, options):
        self.ref, self.start, self.end, self.party = ref, start, end, party
        self.current, self.options = frozenset(current), options
        self.tables = {t for _, ids, _ in options for t in ids}
        self.min_moved = 0 if any(frozenset(ids) == self.current for _, ids, _ in options) else 1
        self.min_unused = min((cap - party for _, _, cap in options), default=0)


def _interact(a, b):
    return a.start < b.end and b.start < a.end and bool(a.tables & b.tables)


def _components(bookings):
    seen, comps = set(), []
    for i in range(len(bookings)):
        if i in seen:
            continue
        stack, comp = [i], []
        seen.add(i)
        while stack:
            n = stack.pop()
            comp.append(n)
            for m in range(len(bookings)):
                if m not in seen and _interact(bookings[n], bookings[m]):
                    seen.add(m)
                    stack.append(m)
        comps.append(sorted(comp))
    return comps


def _solve(comp, budget):
    k = len(comp)
    lb_moved = [0] * (k + 1)
    lb_unused = [0] * (k + 1)
    for i in range(k - 1, -1, -1):
        lb_moved[i] = lb_moved[i + 1] + comp[i].min_moved
        lb_unused[i] = lb_unused[i + 1] + comp[i].min_unused
    best = {"key": None, "pick": None}
    chosen = []  # (option index tuple) per booking so far

    def walk(i, moved, unused, ranks):
        budget[0] -= 1
        if budget[0] < 0:
            raise PlanningLimit()
        if best["key"] is not None:
            if moved + lb_moved[i] > best["key"][0]:
                return
            if moved + lb_moved[i] == best["key"][0] and unused + lb_unused[i] > best["key"][1]:
                return
        if i == k:
            key = (moved, unused, tuple(ranks))
            if best["key"] is None or key < best["key"]:
                best["key"], best["pick"] = key, list(chosen)
            return
        b = comp[i]
        for rank, ids, cap in b.options:
            if any(c.start < b.end and b.start < c.end and set(ids) & set(cids)
                   for c, cids in chosen_pairs(chosen, comp, i)):
                continue
            chosen.append(ids)
            walk(i + 1, moved + (frozenset(ids) != b.current), unused + cap - b.party, ranks + [rank])
            chosen.pop()

    def chosen_pairs(picked, bookings, upto):
        return ((bookings[j], picked[j]) for j in range(upto))

    walk(0, 0, 0, [])
    return best["pick"]


def solve(bookings):
    """bookings sorted by reference. Returns {ref: table_id_tuple} or None if infeasible."""
    if any(not b.options for b in bookings):
        return None
    budget = [NODE_BUDGET]
    result = {}
    for comp_ix in _components(bookings):
        comp = [bookings[i] for i in comp_ix]
        pick = _solve(comp, budget)
        if pick is None:
            return None
        for b, ids in zip(comp, pick):
            result[b.ref] = ids
    return result
