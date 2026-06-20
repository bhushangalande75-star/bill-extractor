"""
Interpret a plain-English request into a small extraction spec.

The LLM only sees the user's request plus the catalogue of available
(schedule, item, short description) tuples — never any amounts. It returns:

  {
    "value_column": "<one of the four amount columns>",
    "include_total": true|false,
    "selections": [ {"schedule": "301", "item": "033062"}, ... ]
  }

If no LLM key is configured, a keyword fallback handles the common cases.
"""
import os
import re
import json

VALUE_COLUMNS = [
    "Amount Since last Bill including special condition",
    "Amount Since last Bill",
    "Amount up to last Bill",
    "Total Up to Date Amount",
]

_KEY_CLAUDE = os.environ.get("ANTHROPIC_API_KEY")
_KEY_GROQ = os.environ.get("GROQ_API_KEY")


def _pick_column(req):
    r = req.lower()
    if "total up to date" in r or "upto date" in r or "up to date" in r:
        return "Total Up to Date Amount"
    if "up to last" in r or "upto last" in r or "previous" in r:
        return "Amount up to last Bill"
    if "special" in r or "incl" in r:
        return "Amount Since last Bill including special condition"
    if "since last" in r:
        return "Amount Since last Bill"
    return "Amount Since last Bill including special condition"


def _keyword_fallback(req, catalogue):
    """No LLM available: match explicit item numbers, schedules, and keywords."""
    r = req.lower()
    want_total = "total" in r
    col = _pick_column(req)

    explicit = set(re.findall(r"\b\d{6}\b", req))
    sched_filter = set(re.findall(r"schedule\s*(\d{2,3})", r))

    sel = []
    for c in catalogue:
        if explicit:
            if c["item"] in explicit and (not sched_filter or c["schedule"] in sched_filter):
                sel.append({"schedule": c["schedule"], "item": c["item"]})
        else:
            desc = c["description"].lower()
            kw_hit = (("steel" in r and ("steel" in desc or "rsj" in desc or "angles" in desc))
                      or ("cement" in r and ("cement" in desc or "opc" in desc))
                      or ("granite" in r and "granite" in desc)
                      or ("water" in r and ("water" in desc or "pipe" in desc)))
            if kw_hit and (not sched_filter or c["schedule"] in sched_filter):
                sel.append({"schedule": c["schedule"], "item": c["item"]})
    if not sel and sched_filter and not explicit:
        sel = [{"schedule": c["schedule"], "item": c["item"]}
               for c in catalogue if c["schedule"] in sched_filter]
    return {"value_column": col, "include_total": want_total, "selections": sel}


def interpret_request(req, catalogue):
    """Return (spec, error). Tries the LLM for a tiny spec; falls back to keywords."""
    provider = "claude" if _KEY_CLAUDE else ("groq" if _KEY_GROQ else None)
    if not provider:
        spec = _keyword_fallback(req, catalogue)
        if not spec["selections"]:
            return None, "No matching items found. Try naming item numbers or a schedule."
        return spec, None

    cat_lines = "\n".join(f"{c['schedule']}|{c['item']}|{c['description']}" for c in catalogue)
    sys = ("You map a user's request to a JSON spec selecting rows from a railway bill "
           "item catalogue. Respond with ONLY JSON: "
           '{"value_column": one of '
           f'{VALUE_COLUMNS}, '
           '"include_total": bool, "selections": [{"schedule":"..","item":".."}]}. '
           "Pick selections strictly from the catalogue. No prose.")
    user = f"REQUEST: {req}\n\nCATALOGUE (schedule|item|description):\n{cat_lines}"

    try:
        if provider == "claude":
            import anthropic
            cl = anthropic.Anthropic(api_key=_KEY_CLAUDE)
            resp = cl.messages.create(model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6"),
                                      max_tokens=4000, temperature=0, system=sys,
                                      messages=[{"role": "user", "content": user}])
            raw = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        else:
            from groq import Groq
            cl = Groq(api_key=_KEY_GROQ)
            resp = cl.chat.completions.create(
                model=os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
                max_tokens=4000, temperature=0,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": sys}, {"role": "user", "content": user}])
            raw = resp.choices[0].message.content
        spec = json.loads(re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip())
        if not spec.get("selections"):
            return None, "I couldn't match that to any items. Try naming an item number or schedule."
        if spec.get("value_column") not in VALUE_COLUMNS:
            spec["value_column"] = _pick_column(req)
        return spec, None
    except Exception:
        # fall back to keyword matching rather than failing the request
        spec = _keyword_fallback(req, catalogue)
        if not spec["selections"]:
            return None, "Couldn't interpret that. Try naming item numbers or a schedule."
        return spec, None
