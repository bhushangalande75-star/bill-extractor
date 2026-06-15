"""
Presets = saved extraction specs. Each preset builds a multi-sheet workbook.

A sheet spec is one of:
  {"title": "...", "type": "bill_summary"}
  {"title": "...", "type": "statement",
     "value_column": "<one of extractor.VALUE_COLUMNS>",   # optional; defaults below
     "select": {"mode": "items", "items": [..]},            # item across every schedule it appears in
        -- or --
     "select": {"mode": "map", "map": {"101": [..], "201": [..]}},  # explicit schedule -> items
     "layout": "combined" | "separate",   # "Sch & Item No" one column, or "Sch" + "Item No"
     "total":  true | false                # add a Total column (sum across bills)
  }

In "map" mode every listed (schedule, item) gets a row even if it wasn't billed
(shown as 0), so the sheet always matches the requested template exactly.
"""

DEFAULT_VALUE = "Amount Since last Bill including special condition"

# The full CA 63-2022 statement the user described.
CA63_FULL = {
    "name": "CA 63-2022 — full statement set",
    "sheets": [
        {
            "title": "Bill Summary",
            "type": "bill_summary",
        },
        {
            "title": "Cement 033062",
            "type": "statement",
            "select": {"mode": "items", "items": ["033062"]},
            "layout": "combined",
            "total": False,
        },
        {
            "title": "Steel & Cement",
            "type": "statement",
            "select": {"mode": "items", "items": [
                "033062", "045014", "081031", "081032", "081140",
                "081293", "081360", "081370", "083050",
            ]},
            "layout": "combined",
            "total": False,
        },
        {
            "title": "Schedule-wise items",
            "type": "statement",
            "select": {"mode": "map", "map": {
                "101": ["011051", "011052", "042025", "042042", "042029", "042030",
                        "098083", "099181", "099182", "099183", "099184", "099185"],
                "102": ["275190"],
                "201": ["095027", "099045", "099200", "131156", "171621", "171631"],
                "202": ["278070"],
                "301": ["011051", "011052", "014110", "021070", "092050", "137010", "181040"],
                "302": ["272030"],
            }},
            "layout": "combined",
            "total": False,
        },
        {
            "title": "Sch101 set A (with total)",
            "type": "statement",
            "select": {"mode": "map", "map": {
                "101": ["043015", "078150", "134011", "134041", "151181",
                        "182013", "155200", "182033", "183030", "185010"],
            }},
            "layout": "combined",
            "total": True,
        },
        {
            "title": "Sch101 set B (split cols)",
            "type": "statement",
            "select": {"mode": "map", "map": {
                "101": ["098022", "098030", "098040"],
            }},
            "layout": "separate",
            "total": True,
        },
        {
            "title": "Sch101 set C (split cols)",
            "type": "statement",
            "select": {"mode": "map", "map": {
                "101": ["108161", "131102", "131103"],
            }},
            "layout": "separate",
            "total": True,
        },
    ],
}

PRESETS = {"ca63_full": CA63_FULL}


def list_presets():
    return [{"id": pid, "name": p["name"], "sheets": len(p["sheets"])}
            for pid, p in PRESETS.items()]


def get_preset(pid):
    return PRESETS.get(pid)
