"""
Build the bill-wise statement workbook from parsed bills + a filter config.

Output mirrors the railway "STATEMENT SHOWING BILL WISE ... CONSUMPTION" format:
rows grouped by schedule, one column per bill, plus a Total column and a
grand TOTAL row.
"""
import io
import re
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

TEAL = "14B8A6"
TEAL_DARK = "0F766E"
LIGHT = "E1F5EE"
WHITE = "FFFFFF"

_thin = Side(style="thin", color="C9D6D1")
BORDER = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)


def _bill_sort_key(b):
    m = re.search(r"\d+", b.get("bill_no") or "")
    return int(m.group()) if m else 999


def build_workbook(parsed_bills, config):
    """
    parsed_bills: list of dicts from extractor.extract_rows()
    config: {
        "value_column": str,
        "items":     [str, ...],          # item numbers to include
        "schedules": [str, ...] or [],     # empty => all schedules present
        "title":     str (optional),
        "ca_no":     str (optional),
    }
    Returns an in-memory .xlsx (BytesIO).
    """
    value_col = config["value_column"]
    want_items = list(dict.fromkeys(config["items"]))          # preserve order, dedupe
    want_scheds = set(config.get("schedules") or [])

    bills = sorted(parsed_bills, key=_bill_sort_key)
    bill_labels = [b.get("bill_no") or f"B{i+1}" for i, b in enumerate(bills)]

    # lookup[(schedule, item)][bill_label] = value
    lookup = {}
    scheds_present = set()
    for b, label in zip(bills, bill_labels):
        for row in b["rows"]:
            scheds_present.add(row["schedule"])
            key = (row["schedule"], row["item"])
            val = row["values"].get(value_col)
            if val is not None:
                lookup.setdefault(key, {})
                lookup[key][label] = lookup[key].get(label, 0.0) + val

    scheds = sorted(s for s in scheds_present if s and (not want_scheds or s in want_scheds))

    wb = Workbook()
    ws = wb.active
    ws.title = "Bill-wise Statement"

    ncols = 2 + len(bill_labels) + 1   # Sch&Item | bills... | Total
    last_col = ncols

    # ---- title block ----
    ws.cell(1, 1, config.get("title") or "STATEMENT SHOWING BILL-WISE AMOUNT")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last_col)
    ws.cell(1, 1).font = Font(bold=True, size=13, color=TEAL_DARK)
    ws.cell(1, 1).alignment = Alignment(horizontal="center")

    ws.cell(2, 1, f"CA No.: {config.get('ca_no') or '-'}    |    Value: {value_col}")
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=last_col)
    ws.cell(2, 1).font = Font(italic=True, size=10, color="555555")
    ws.cell(2, 1).alignment = Alignment(horizontal="center")

    # ---- header row ----
    hdr = 4
    headers = ["SN", "Sch & Item No"] + bill_labels + ["Total"]
    for c, h in enumerate(headers, start=1):
        cell = ws.cell(hdr, c, h)
        cell.font = Font(bold=True, color=WHITE)
        cell.fill = PatternFill("solid", fgColor=TEAL)
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = BORDER

    r = hdr + 1
    sn = 0
    col_totals = {label: 0.0 for label in bill_labels}
    grand_total = 0.0

    for sched in scheds:
        items_here = [it for it in want_items if (sched, it) in lookup]
        if not items_here:
            continue  # no selected item in this schedule -> no header

        # schedule sub-header
        scell = ws.cell(r, 2, f"SCH-{sched}")
        scell.font = Font(bold=True, color=TEAL_DARK)
        for c in range(1, last_col + 1):
            ws.cell(r, c).fill = PatternFill("solid", fgColor=LIGHT)
            ws.cell(r, c).border = BORDER
        r += 1

        for item in items_here:
            key = (sched, item)
            sn += 1
            ws.cell(r, 1, sn).border = BORDER
            ws.cell(r, 2, item).border = BORDER
            row_total = 0.0
            for ci, label in enumerate(bill_labels, start=3):
                v = lookup[key].get(label)
                cell = ws.cell(r, ci)
                if v is not None:
                    cell.value = round(v, 2)
                    row_total += v
                    col_totals[label] += v
                cell.border = BORDER
                cell.alignment = Alignment(horizontal="right")
            tcell = ws.cell(r, last_col, round(row_total, 2))
            tcell.border = BORDER
            tcell.font = Font(bold=True)
            tcell.alignment = Alignment(horizontal="right")
            grand_total += row_total
            r += 1

    # ---- grand total row ----
    ws.cell(r, 2, "TOTAL").font = Font(bold=True, color=WHITE)
    for c in range(1, last_col + 1):
        ws.cell(r, c).fill = PatternFill("solid", fgColor=TEAL_DARK)
        ws.cell(r, c).border = BORDER
    for ci, label in enumerate(bill_labels, start=3):
        cell = ws.cell(r, ci, round(col_totals[label], 2))
        cell.font = Font(bold=True, color=WHITE)
        cell.alignment = Alignment(horizontal="right")
    gcell = ws.cell(r, last_col, round(grand_total, 2))
    gcell.font = Font(bold=True, color=WHITE)
    gcell.alignment = Alignment(horizontal="right")

    # ---- widths ----
    ws.column_dimensions["A"].width = 5
    ws.column_dimensions["B"].width = 16
    from openpyxl.utils import get_column_letter
    for c in range(3, last_col + 1):
        ws.column_dimensions[get_column_letter(c)].width = 14
    ws.freeze_panes = "C5"

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
