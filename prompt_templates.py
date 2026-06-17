"""
Pre-built prompt templates for bill data extraction.
Users can select and customize these, or write custom prompts.
"""

TEMPLATES = {
    "bill_summary": {
        "name": "Bill Summary (Bills 1-10)",
        "description": "Extract bill number, measurement dates, and bill amount",
        "prompt": """Extract from all bills the following data and return as JSON:
For each bill (B1 through B10):
  - Bill No
  - Measurement Start Date
  - Measurement Complete Date
  - Bill Amount (including GST)

Return as: {"bills": [{"bill_no": "B1", "meas_start": "date", "meas_end": "date", "amount": number}, ...]}""",
        "output_format": "Bill Summary",
        "columns": ["Bill No", "Measurement Start", "Measurement Complete", "Amount (Rs)"],
    },
    
    "single_item_multi_bill": {
        "name": "Single Item Across Bills",
        "description": "Amount for one item number across all bills (each schedule)",
        "prompt": """Extract from all bills the 'Amount Since last Bill including special condition' for item no. {item_no}.
For each schedule where this item appears and each bill (B1-B10), return:
  - Schedule
  - Item No
  - Bill No
  - Amount

Return as JSON: {"items": [{"schedule": "101", "item_no": "033062", "bill_no": "B1", "amount": number}, ...]}
If item doesn't appear in a bill, set amount to 0.""",
        "output_format": "Single Item Statement",
        "columns": ["Schedule", "Item No", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "B10"],
        "variables": {"item_no": "033062"},
    },
    
    "multi_item_multi_schedule": {
        "name": "Multiple Items, Multiple Schedules",
        "description": "Amount for specified items across schedules and bills",
        "prompt": """Extract from all bills the 'Amount Since last Bill including special condition' for:
{schedule_items}

For each (schedule, item) pair and each bill (B1-B10), return the amount.

Return as JSON: {{"items": [{{"schedule": "101", "item_no": "011051", "bill_no": "B1", "amount": number}}, ...]}}
If an item doesn't appear in a bill, set amount to 0.""",
        "output_format": "Multi-Item Statement",
        "columns": ["Schedule", "Item No", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "B10"],
        "variables": {
            "schedule_items": """Schedule 101: items 011051, 011052, 042025, 042042, 042029, 042030, 098083, 099181, 099182, 099183, 099184, 099185
Schedule 102: item 275190
Schedule 201: items 095027, 099045, 099200, 131156, 171621, 171631
Schedule 202: item 278070
Schedule 301: items 011051, 011052, 014110, 021070, 092050, 137010, 181040
Schedule 302: item 272030"""
        },
    },
    
    "schedule_items_with_total": {
        "name": "Schedule Items with Total",
        "description": "Multiple items per schedule with totals",
        "prompt": """Extract from all bills (B1-B10) the 'Amount Since last Bill including special condition' for:
Schedule 101: items {sch101_items}
Schedule 102: item {sch102_item}
Schedule 201: items {sch201_items}
Schedule 202: item {sch202_item}
Schedule 301: items {sch301_items}
Schedule 302: item {sch302_item}

Return as JSON with structure: {{"items": [{{"schedule": "101", "item_no": "043015", "bills": {{"B1": number, "B2": number, ...}}, "total": number}}, ...]}}
Calculate totals across all bills for each (schedule, item) pair.""",
        "output_format": "Items with Total",
        "columns": ["Schedule", "Item No", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "B10", "Total"],
        "variables": {
            "sch101_items": "043015, 078150, 134011, 134041, 151181, 182013, 155200, 182033, 183030, 185010",
            "sch102_item": "275190",
            "sch201_items": "095027, 099045, 099200, 131156, 171621, 171631",
            "sch202_item": "278070",
            "sch301_items": "011051, 011052, 014110, 021070, 092050, 137010, 181040",
            "sch302_item": "272030",
        },
    },
}


def get_template(template_id):
    return TEMPLATES.get(template_id)


def list_templates():
    return [
        {"id": tid, "name": t["name"], "description": t["description"]}
        for tid, t in TEMPLATES.items()
    ]


def render_prompt(template_id, **overrides):
    """Render a prompt by substituting variables."""
    t = TEMPLATES.get(template_id)
    if not t:
        return None
    prompt = t["prompt"]
    vars_dict = t.get("variables", {}).copy()
    vars_dict.update(overrides)
    for var, val in vars_dict.items():
        prompt = prompt.replace(f"{{{var}}}", str(val))
    return prompt
