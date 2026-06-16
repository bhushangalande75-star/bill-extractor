"""
Validation harness: proves the PVC engine reproduces the worked Manoj Sethi
workbook (CA 0033, base month Jan-24).  Run with the five index data-bank PDFs
in the directory given by IDX_DIR (defaults to ./pvc_data).

    python validate_pvc.py /path/to/index/pdfs

Expected output (engine vs workbook):
    9A  labour/P&M/fuel/material : 534737.34   workbook  534737.33
    9B  reinforcement bars       : -135802.16  workbook -135802.16
    9D  other-section steel      : -39055.13   workbook  -39055.12
    GRAND TOTAL PVC              : 359880.05   workbook  359880.05
"""
import os
import sys

import index_bank as ib
import pvc

# Per-agreement base months (one month before each sanction).
BASE = {"Original": "2024-01", "SA-1": "2024-12", "SA-2": "2026-01"}

# Calendar months of each PVC quarter (3-month periods from the Jan-24 base).
Q = {"Q2": ["2024-05", "2024-06", "2024-07"],
     "Q4": ["2024-11", "2024-12", "2025-01"],
     "Q5": ["2025-02", "2025-03", "2025-04"],
     "Q8": ["2025-11", "2025-12", "2026-01"],
     "Q9": ["2026-02", "2026-03", "2026-04"]}

# Gross amounts per work entry, taken from the GPVC statement:
#   (agreement, quarter, balance-for-GPVC, reinforcement, other-section steel)
ENTRIES = [
    ("Original", "Q2", 2654149.48, 477743.59, 0),
    ("Original", "Q4", 4930886.46, 666356.86, 669688.62),
    ("SA-1",     "Q4", 169080.36,  0,          0),
    ("Original", "Q5", 5092444.05, 2345330.83, 196097.5),
    ("SA-1",     "Q5", 530883.84,  0,          0),
    ("Original", "Q8", 2872843.86, 1022928.81, 560110.38),
    ("Original", "Q9", 6922531.8,  118180.9,   2210830.52),
    ("SA-1",     "Q9", 593198.92,  0,          0),
    ("SA-2",     "Q9", 544078.86,  0,          9489.91),
]

# In the final (incomplete) quarter, only Feb-26 was published for these indices
# at billing time; machinery & diesel had the full quarter.
FEB_ONLY = {"labour", "material", "tmt", "steel_other"}


def main(idx_dir):
    paths = {
        "labour": os.path.join(idx_dir, "Index_labor__1_.pdf"),
        "machinery": os.path.join(idx_dir, "Index_Plant___machinery__1_.pdf"),
        "material": os.path.join(idx_dir, "Index_Material__1_.pdf"),
        "diesel": os.path.join(idx_dir, "PPAC__HSD_oil.pdf"),
        "steel": os.path.join(idx_dir, "JPc_other_section_steel.pdf"),
    }
    idx = ib.load_all(paths)

    tot = {"balance": 0.0, "reinf": 0.0, "other": 0.0}
    for ag, q, bal, reinf, other in ENTRIES:
        for kind, gross in [("balance", bal), ("reinf", reinf), ("other", other)]:
            if not gross:
                continue
            for comp, w in pvc.CLASSES[kind].items():
                series = idx[comp]
                base_val = series.get(BASE[ag])
                months = Q[q][:1] if (q == "Q9" and comp in FEB_ONLY) else Q[q]
                avg = pvc.avg_index(series, months)
                if avg is not None:
                    avg = round(avg, 2)
                tot[kind] += pvc.pvc_one(gross, w, base_val, avg)

    grand = sum(tot.values())
    print("CLASSIFICATION TOTALS  (engine vs Manoj workbook)")
    print(f"  9A  labour/P&M/fuel/material : {tot['balance']:12.2f}   workbook  534737.33")
    print(f"  9B  reinforcement bars       : {tot['reinf']:12.2f}   workbook -135802.16")
    print(f"  9D  other-section steel      : {tot['other']:12.2f}   workbook  -39055.12")
    print(f"  {'GRAND TOTAL PVC':29}: {grand:12.2f}   workbook  359880.05")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "pvc_data")
