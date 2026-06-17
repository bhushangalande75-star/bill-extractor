"""
LLM-based bill extractor supporting multiple providers:
  - Claude (Anthropic)  -> needs ANTHROPIC_API_KEY
  - Groq (Llama)        -> needs GROQ_API_KEY

The provider is chosen per request; the app falls back to whichever key is set.
"""
import os
import json
import re
import pdfplumber

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY")
GROQ_KEY = os.environ.get("GROQ_API_KEY")

# Model strings can be overridden via env if you want a different tier.
CLAUDE_MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")


SYSTEM_MSG = (
    "You are a railway civil-bill data extraction specialist. Read the bills "
    "provided and extract data exactly as the user's prompt requests. Respond "
    "with ONLY valid JSON — no preamble, no markdown fences, no explanation. "
    "Use 0 for missing numeric values and null for missing text. Numbers must "
    "be plain numbers (no commas, no currency symbols)."
)


def available_providers():
    """Which providers have a usable key right now."""
    out = []
    if ANTHROPIC_KEY:
        out.append("claude")
    if GROQ_KEY:
        out.append("groq")
    return out


def pdf_to_text(pdf_path, max_pages=60):
    parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages[:max_pages]):
            t = page.extract_text() or ""
            if t.strip():
                parts.append(f"=== PAGE {i+1} ===\n{t}")
    return "\n\n".join(parts)


def _parse_json(text):
    """Best-effort JSON parse: strip fences, then fall back to a brace scan."""
    if not text:
        return None
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                return None
    return None


def _call_claude(system_msg, user_msg):
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    resp = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=8000,
        temperature=0,
        system=system_msg,
        messages=[{"role": "user", "content": user_msg}],
    )
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


def _call_groq(system_msg, user_msg):
    from groq import Groq
    client = Groq(api_key=GROQ_KEY)
    resp = client.chat.completions.create(
        model=GROQ_MODEL,
        max_tokens=8000,
        temperature=0,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_msg},
        ],
    )
    return resp.choices[0].message.content


def extract_bills_with_prompt(pdf_paths, prompt, provider="claude", bill_labels=None):
    """
    Extract data from bill PDFs using the chosen LLM provider.

    provider: "claude" or "groq". If the chosen provider's key is missing,
              falls back to the other available provider.

    Returns: (success: bool, data_or_error)
    """
    if not pdf_paths:
        return False, "No PDFs provided."

    provider = (provider or "claude").lower()
    avail = available_providers()
    if not avail:
        return False, ("No LLM key configured. Set ANTHROPIC_API_KEY (Claude) "
                       "or GROQ_API_KEY (Groq) in the environment.")
    if provider not in avail:
        provider = avail[0]  # graceful fallback to whatever is configured

    # Read bills into text
    bill_texts = {}
    for i, path in enumerate(pdf_paths):
        label = (bill_labels or {}).get(path) if bill_labels else None
        label = label or f"B{i+1}"
        try:
            bill_texts[label] = pdf_to_text(path)
        except Exception as e:
            return False, f"Failed to read {os.path.basename(path)}: {e}"

    bills_context = "\n\n".join(
        f"--- {label} ---\n{text}" for label, text in sorted(bill_texts.items())
    )
    user_msg = f"{prompt}\n\nBILLS DATA:\n{bills_context}"

    try:
        if provider == "claude":
            raw = _call_claude(SYSTEM_MSG, user_msg)
        else:
            raw = _call_groq(SYSTEM_MSG, user_msg)
    except Exception as e:
        return False, f"{provider.title()} API error: {e}"

    data = _parse_json(raw)
    if data is None:
        return False, f"{provider.title()} returned text that wasn't valid JSON. Try a simpler prompt or fewer bills."
    return True, data
