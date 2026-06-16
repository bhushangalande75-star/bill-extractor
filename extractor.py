"""
PDF bill -> structured rows extractor for CR/BSL Civil bills.

The financial numbers are read directly from the PDF tables with pdfplumber.
No AI / LLM touches the amounts, so figures cannot be hallucinated.
"""
import re
import html
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
_DATE = r"(\d{2}/\d{2}/\d{4})"
_AMT_RE = re.compile(r"Bill Amount \(Rs\.\) \(Including Tax \(GST\)\)\s+([\d.]+)")


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


def _cellnum(raw):
    """Parse a cell as a number; if not numeric, return cleaned text (or None)."""
    f = _to_float(raw)
    if f is not None:
        return f
    s = (raw or "").replace("\n", " ").strip() if isinstance(raw, str) else ""
    return s or None


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
    """Return bill metadata from the first page (+ bill amount near the end)."""
    text = pdf.pages[0].extract_text() or ""

    def find(pat):
        m = re.search(pat, text)
        return m.group(1) if m else None

    bill = _BILLNO_RE.search(text)
    ca = _CA_RE.search(text)
    meta = {
        "bill_no": bill.group(1) if bill else None,
        "ca_no": ca.group(1) if ca else None,
        "meas_from": find(r"Measurement Date From\s+" + _DATE),
        "meas_to": find(r"Measurement Date To\s+" + _DATE),
        "bill_date": find(r"Bill Date\s+" + _DATE),
        "bill_amount": None,
    }
    # the GST-inclusive bill amount sits in the summary near the end
    for page in reversed(pdf.pages):
        m = _AMT_RE.search(page.extract_text() or "")
        if m:
            try:
                meta["bill_amount"] = float(m.group(1))
            except ValueError:
                pass
            break
    return meta


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
        meta = _read_meta(pdf)
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
                            "full": {
                                "sr_no": (r[0] or "").replace("\n", " ").strip() if r[0] else "",
                                "base_rate": _cellnum(r[3]),
                                "agmt_rate": _cellnum(r[4]),
                                "orig_qty": _cellnum(r[5]),
                                "curr_qty": _cellnum(r[6]),
                                "qty_upto_last": _cellnum(r[7]),
                                "qty_since_last": _cellnum(r[8]),
                                "qty_upto_date": _cellnum(r[9]),
                                "amt_upto_last": _to_float(r[10]),
                                "amt_since_last": _to_float(r[11]),
                                "amt_incl_spec": _to_float(r[12]),
                                "total_upto_date": _to_float(r[13]),
                                "remarks": (r[14] or "").replace("\n", " ").strip() if len(r) > 14 and r[14] else "",
                            },
                        }
                        rows.append(row)
                        last_item_row = row
                    else:
                        # description sub-row of the current item
                        desc = r[UNIT_COL] if len(r) > UNIT_COL else None
                        if last_item_row is not None and isinstance(desc, str) and desc.strip():
                            if not last_item_row["description"]:
                                last_item_row["description"] = desc.replace("\n", " ").strip()

    for row in rows:
        if row["description"]:
            row["description"] = html.unescape(row["description"])
        if row["full"].get("remarks"):
            row["full"]["remarks"] = html.unescape(row["full"]["remarks"])

    result = dict(meta)
    result["rows"] = rows
    return result


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
