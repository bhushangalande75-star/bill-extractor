"""
PDF bill -> structured rows extractor for CR/BSL Civil bills.

The financial numbers are read directly from the PDF tables with pdfplumber.
No AI / LLM touches the amounts, so figures cannot be hallucinated.
"""
import re
import pdfplumber

# Column index -> human name, based on the standard CR/BSL item-wise bill layout.
# pdfplumber returns 15 columns per item row; these are the amount columns.
VALUE_COLUMNS = {
    "Amount up to last Bill": 10,
    "Amount Since last Bill": 11,
    "Amount Since last Bill including special condition": 12,
    "Total Up to Date Amount": 13,
}
DEFAULT_VALUE_COLUMN = "Amount Since last Bill including special condition"

ITEM_COL = 1
UNIT_COL = 2
MIN_ITEM_LEN = 5  # USSOR/SOR item numbers are at least 5 digits

# These bills are digitally generated with ruled borders, so the "lines"
# strategy is both faster and more accurate than pdfplumber's default.
TABLE_SETTINGS = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}

_SCHED_RE = re.compile(r"Schedule\s+(\d{2,3})\b")
_BILLNO_RE = re.compile(r"/(B\d+)\b")
_CA_RE = re.compile(r"(CR/[A-Z]+/[A-Za-z]+/\d{4}/\d{3,4})")


def _norm_item(raw):
    """'0330\\n62\\n(G)' -> '033062'."""
    if not raw:
        return None
    digits = re.sub(r"[^0-9]", "", str(raw).replace("(G)", ""))
    return digits or None


def _to_float(raw):
    if raw is None:
        return None
    s = str(raw).replace("\n", "").replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _is_schedule_header(joined):
    """Distinguish a real schedule header row from anything else."""
    if "Total (" in joined:          # this is a schedule total row, not a header
        return None
    m = _SCHED_RE.search(joined)
    if not m:
        return None
    if any(k in joined for k in ("Repair", "Bhusawal", "Improvement", "Improvemnt",
                                 "facilitated", "PF surface")):
        return m.group(1)
    return None


def _read_meta(pdf):
    """Return (bill_no, ca_no) from the first page text."""
    text = pdf.pages[0].extract_text() or ""
    bill = _BILLNO_RE.search(text)
    ca = _CA_RE.search(text)
    return (bill.group(1) if bill else None,
            ca.group(1) if ca else None)


def extract_rows(filepath):
    """
    Parse one bill PDF.

    Returns dict:
      {
        "bill_no": "B5",
        "ca_no": "CR/BSL/Civil/2022/0063",
        "rows": [ {schedule, item, unit, description, values:{col_name: float}} , ... ]
      }
    """
    rows = []
    cur_sched = None
    last_item_row = None  # to attach the description sub-row that follows an item

    with pdfplumber.open(filepath) as pdf:
        bill_no, ca_no = _read_meta(pdf)
        for page in pdf.pages:
            for table in page.extract_tables(table_settings=TABLE_SETTINGS):
                for r in table:
                    cells = [c for c in r if isinstance(c, str)]
                    joined = " ".join(cells)

                    sched = _is_schedule_header(joined)
                    if sched:
                        cur_sched = sched
                        last_item_row = None
                        continue

                    if len(r) < 14:
                        # likely a description-only sub-row; attach to previous item
                        desc = (r[UNIT_COL] if len(r) > UNIT_COL else None)
                        if last_item_row is not None and isinstance(desc, str) and desc.strip():
                            if not last_item_row["description"]:
                                last_item_row["description"] = desc.replace("\n", " ").strip()
                        continue

                    item = _norm_item(r[ITEM_COL])
                    if item and len(item) >= MIN_ITEM_LEN:
                        values = {name: _to_float(r[idx]) for name, idx in VALUE_COLUMNS.items()}
                        row = {
                            "schedule": cur_sched,
                            "item": item,
                            "unit": (r[UNIT_COL] or "").replace("\n", " ").strip(),
                            "description": "",
                            "values": values,
                        }
                        rows.append(row)
                        last_item_row = row
                    else:
                        # description sub-row of the current item
                        desc = r[UNIT_COL] if len(r) > UNIT_COL else None
                        if last_item_row is not None and isinstance(desc, str) and desc.strip():
                            if not last_item_row["description"]:
                                last_item_row["description"] = desc.replace("\n", " ").strip()

    return {"bill_no": bill_no, "ca_no": ca_no, "rows": rows}


def summarize(parsed_bills):
    """
    Build the filter inventory from already-parsed bills (parse once, reuse).

    Each item in parsed_bills is the dict returned by extract_rows(), with an
    extra "file" key holding the original filename.

    Returns:
      {
        "bills":   [ {"file": name, "bill_no": "B5"} , ... ],
        "ca_no":   "CR/BSL/Civil/2022/0063",
        "schedules": ["101","201","301", ...],
        "items":   [ {"item":"033062","description":"OPC 53 grade",
                      "schedules":["101","201","301"]} , ... ],
        "value_columns": [ ...names... ]
      }
    """
    bills = []
    ca_no = None
    item_map = {}        # item -> {"description":..., "schedules":set()}
    schedules = set()

    for idx, parsed in enumerate(parsed_bills, start=1):
        ca_no = ca_no or parsed.get("ca_no")
        bills.append({"file": parsed.get("file", f"bill{idx}.pdf"),
                      "bill_no": parsed.get("bill_no") or f"B{idx}"})
        for row in parsed["rows"]:
            schedules.add(row["schedule"])
            entry = item_map.setdefault(row["item"], {"description": "", "schedules": set()})
            if not entry["description"] and row["description"]:
                entry["description"] = row["description"][:60]
            if row["schedule"]:
                entry["schedules"].add(row["schedule"])

    items = [
        {"item": it, "description": d["description"], "schedules": sorted(d["schedules"])}
        for it, d in sorted(item_map.items())
    ]
    return {
        "bills": bills,
        "ca_no": ca_no,
        "schedules": sorted(s for s in schedules if s),
        "items": items,
        "value_columns": list(VALUE_COLUMNS.keys()),
    }
