"""
GCC 46A "Other Works" PVC calculation engine.

PVC for one component in one quarter:
    pvc = gross * weight * (avg_index - base_index) / base_index

where gross is the value of that component's work in the quarter, base_index is
the index for the agreement's base month, and avg_index is the mean of the
component's monthly index over the (available) months of the quarter.

Classifications (component -> weight):
  balance (9A): labour .20, machinery .30, diesel .15, material .20
  reinf   (9B): tmt .85
  other   (9D): labour .10, steel_other .50, machinery .10, diesel .10, material .05
"""

CLASSES = {
    "balance": {"labour": 0.20, "machinery": 0.30, "diesel": 0.15, "material": 0.20},
    "reinf":   {"tmt": 0.85},
    "other":   {"labour": 0.10, "steel_other": 0.50, "machinery": 0.10,
                "diesel": 0.10, "material": 0.05},
}


def quarter_months(base_ym, q):
    """Months of quarter q (1-based) for a contract with the given base month.
    Quarter 1 starts the month after the base month; quarters are 3 months."""
    by, bm = int(base_ym[:4]), int(base_ym[5:])
    start = bm + 1 + 3 * (q - 1)          # 1-based month offset from base year
    out = []
    for k in range(3):
        idx = start + k
        y = by + (idx - 1) // 12
        m = (idx - 1) % 12 + 1
        out.append(f"{y:04d}-{m:02d}")
    return out


def avg_index(series, months):
    """Mean of the index over the months that have published data."""
    vals = [series[m] for m in months if m in series]
    return sum(vals) / len(vals) if vals else None


def pvc_one(gross, weight, base_val, avg_val):
    if not base_val or avg_val is None or not gross:
        return 0.0
    return gross * weight * (avg_val - base_val) / base_val


def pvc_for_entry(gross, kind, months, indices, base_ym):
    """Sum the PVC over all components of one classification for one work entry."""
    total = 0.0
    parts = {}
    for comp, weight in CLASSES[kind].items():
        series = indices[comp]
        base_val = series.get(base_ym)
        avg_val = avg_index(series, months)
        amt = pvc_one(gross, weight, base_val, avg_val)
        parts[comp] = amt
        total += amt
    return total, parts
