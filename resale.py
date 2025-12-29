
CATEGORY_VALUES = {
    "clothing": (100, 300),
    "tools": (200, 800),
    "electronics": (150, 600),
    "furniture": (250, 1000),
    "misc": (50, 200),
}

def estimate(tags, unit_size):
    lo = hi = 0
    for t in tags:
        a, b = CATEGORY_VALUES.get(t, (50, 200))
        lo += a
        hi += b
    if "10" in unit_size:
        hi = int(hi * 1.2)
    return lo, hi
