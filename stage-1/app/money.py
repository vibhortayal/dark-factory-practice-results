"""Equal-split arithmetic (spec section 9)."""


def equal_shares(amount, n):
    """Whole-unit shares summing to amount; the first `amount % n` shares get one extra."""
    base, extra = divmod(amount, n)
    return [base + 1 if i < extra else base for i in range(n)]
