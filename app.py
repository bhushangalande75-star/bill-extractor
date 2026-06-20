"""
SocietyNotice-themed PDF Bill -> Excel extractor.

Flow:
  1. User uploads one or more bill PDFs           -> POST /analyze
  2. Server returns the schedules + item numbers found in those PDFs,
     so the filter shown to the user matches the uploaded bills.
  3. User selects value column + items (+ schedules) -> POST /generate
  4. Server returns the bill-wise statement .xlsx.

No external API keys required. The amounts are read straight from the PDF
tables, so figures cannot be invented.
"""
import os
import io
import uuid
import time
import json
import shutil
import tempfile
import threading

from flask import Flask, request, jsonify, send_file, render_template
from werkzeug.utils import secure_filename
from werkzeug.exceptions import HTTPException

from extractor import summarize, extract_rows
from excel_builder import build_workbook, build_preset_workbook, build_raw_workbook
from presets import list_presets, get_preset
from prompt_templates import list_templates, get_template, render_prompt
from llm_extractor import extract_bills_with_prompt, available_providers
from nl_interpret import interpret_request

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024   # 200 MB (10+ bills at once)

JOB_TTL = 45 * 60   # forget a job 45 min after it was created


@app.errorhandler(Exception)
def json_errors(e):
    """Never let an API call receive an HTML error page (which breaks the
    frontend's res.json()). Client errors keep their normal page; anything
    else comes back as JSON."""
    if isinstance(e, HTTPException) and (e.code or 500) < 500:
        return e
    return jsonify({"error": f"Server error: {e}"}), 500


# token -> {status, total, done, parsed, summary, error, dir, ts}
# In-memory and per-process. Fine for a single instance; for multi-instance
# scale move this to Redis and the files to object storage (see README).
JOBS = {}
_LOCK = threading.Lock()


def _cleanup_jobs():
    now = time.time()
    for tok in [t for t, j in JOBS.items() if now - j["ts"] > JOB_TTL]:
        job = JOBS.pop(tok, None)
        if job:
            shutil.rmtree(job.get("dir", ""), ignore_errors=True)


def _save_uploads(files):
    token = uuid.uuid4().hex
    d = tempfile.mkdtemp(prefix=f"bill_{token}_")
    saved = []
    for f in files:
        if not f or not f.filename.lower().endswith(".pdf"):
            continue
        name = secure_filename(f.filename)
        path = os.path.join(d, name)
        f.save(path)
        saved.append((path, name))
    return token, d, saved


import re as _re
_VALUE_COL = "Amount Since last Bill including special condition"
_STRUCTURED = {"bill_summary", "single_item_multi_bill",
               "multi_item_multi_schedule", "schedule_items_with_total"}


def _prompt_item_targets(prompt):
    codes = set(_re.findall(r"\b\d{5,6}\b", prompt))
    codes |= set(_re.findall(r"\b\d{1,3}(?:\.\d{1,3}){1,3}\b", prompt))
    return codes


def _deterministic_prompt_data(prompt_id, prompt, pdf_paths):
    """Build the same JSON the LLM would, but straight from the parsed bills —
    exact, free, no token limit. Used for the built-in structured templates."""
    parsed = []
    for p in pdf_paths:
        pb = extract_rows(p)
        parsed.append(pb)
    parsed.sort(key=lambda b: _bill_key(b.get("bill_no")))

    if prompt_id == "bill_summary":
        bills = [{"bill_no": b.get("bill_no") or "?",
                  "meas_start": b.get("meas_from"),
                  "meas_end": b.get("meas_to"),
                  "amount": b.get("bill_amount") or 0} for b in parsed]
        return {"bills": bills}

    # item templates: amount per (schedule, item) per bill
    targets = _prompt_item_targets(prompt)
    items = []
    for b in parsed:
        bn = b.get("bill_no") or "?"
        for row in b["rows"]:
            if row["item"] in targets:
                amt = row["values"].get(_VALUE_COL)
                items.append({"schedule": row["schedule"], "item_no": row["item"],
                              "bill_no": bn, "amount": amt if amt is not None else 0})
    return {"items": items}


def _bill_key(bn):
    m = _re.search(r"(\d+)", bn or "")
    return int(m.group(1)) if m else 9999


def _groq_job(token, saved_pdfs, prompt, provider="claude", prompt_id=None):
    """Built-in structured templates are handled deterministically (exact, free,
    no token limit). Only genuinely custom prompts go to the LLM."""
    pdf_paths = [path for path, _ in saved_pdfs]
    try:
        if prompt_id in _STRUCTURED:
            data = _deterministic_prompt_data(prompt_id, prompt, pdf_paths)
            with _LOCK:
                JOBS[token]["groq_data"] = data
                JOBS[token]["status"] = "done"
            return
        success, data = extract_bills_with_prompt(pdf_paths, prompt, provider=provider)
        with _LOCK:
            if success:
                JOBS[token]["groq_data"] = data
                JOBS[token]["status"] = "done"
            else:
                JOBS[token]["status"] = "error"
                JOBS[token]["error"] = data  # data is error message if not success
    except Exception as e:
        with _LOCK:
            JOBS[token]["status"] = "error"
            JOBS[token]["error"] = str(e)


def _parse_job(token, saved):
    """Runs in a background thread so /analyze returns immediately and never
    hits the request timeout, however many bills are uploaded."""
    parsed = []
    try:
        for path, name in saved:
            pb = extract_rows(path)
            pb["file"] = name
            parsed.append(pb)
            with _LOCK:
                JOBS[token]["done"] = len(parsed)
                JOBS[token]["parsed"] = parsed
        summary = summarize(parsed)
        summary["token"] = token
        with _LOCK:
            JOBS[token]["summary"] = summary
            JOBS[token]["status"] = "done"
    except Exception as e:
        with _LOCK:
            JOBS[token]["status"] = "error"
            JOBS[token]["error"] = str(e)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    _cleanup_jobs()
    files = request.files.getlist("pdfs")
    if not files:
        return jsonify({"error": "No PDF files received."}), 400

    token, d, saved = _save_uploads(files)
    if not saved:
        return jsonify({"error": "No valid .pdf files in the upload."}), 400

    JOBS[token] = {"status": "processing", "total": len(saved), "done": 0,
                   "parsed": [], "summary": None, "error": None,
                   "dir": d, "ts": time.time()}
    threading.Thread(target=_parse_job, args=(token, saved), daemon=True).start()
    return jsonify({"token": token, "status": "processing", "total": len(saved)})


@app.route("/status/<token>")
def status(token):
    job = JOBS.get(token)
    if not job:
        return jsonify({"error": "Unknown or expired job. Please re-upload."}), 404
    if job["status"] == "done":
        return jsonify({"status": "done", "result": job["summary"]})
    if job["status"] == "error":
        return jsonify({"status": "error", "error": job["error"]}), 500
    return jsonify({"status": "processing", "done": job["done"], "total": job["total"]})


def _ready_job(token):
    job = JOBS.get(token)
    if not job or job["status"] != "done":
        return None
    return job


@app.route("/extracted_data/<token>")
def extracted_data(token):
    """Full extracted data in a plain-readable shape, one block per bill."""
    job = _ready_job(token)
    if not job:
        return jsonify({"error": "Session expired or still processing. Re-upload."}), 400
    bills = []
    for b in sorted(job["parsed"], key=lambda x: _bill_key(x.get("bill_no"))):
        rows = []
        for r in b["rows"]:
            f = r["full"]
            rows.append({
                "schedule": r["schedule"], "item": r["item"], "unit": r["unit"],
                "description": r["description"],
                "base_rate": f["base_rate"], "agmt_rate": f["agmt_rate"],
                "qty_upto_date": f["qty_upto_date"],
                "amt_upto_last": f["amt_upto_last"],
                "amt_since_incl_spec": f["amt_incl_spec"],
                "total_upto_date": f["total_upto_date"],
            })
        bills.append({
            "bill_no": b.get("bill_no"), "meas_from": b.get("meas_from"),
            "meas_to": b.get("meas_to"), "bill_date": b.get("bill_date"),
            "bill_amount": b.get("bill_amount"),
            "schedules": sorted({r["schedule"] for r in b["rows"] if r["schedule"]}),
            "row_count": len(rows), "rows": rows,
        })
    return jsonify({"ca_no": job["summary"].get("ca_no"), "bills": bills})


@app.route("/generate", methods=["POST"])
def generate():
    payload = request.get_json(silent=True) or {}
    job = _ready_job(payload.get("token"))
    if not job:
        return jsonify({"error": "Session expired or still processing. Re-upload the PDFs."}), 400

    config = {
        "value_column": payload.get("value_column")
        or "Amount Since last Bill including special condition",
        "items": payload.get("items") or [],
        "schedules": payload.get("schedules") or [],
        "title": payload.get("title") or "STATEMENT SHOWING BILL-WISE AMOUNT",
        "ca_no": payload.get("ca_no"),
    }
    if not config["items"]:
        return jsonify({"error": "Select at least one item number."}), 400

    try:
        buf = build_workbook(job["parsed"], config)
    except Exception as e:
        return jsonify({"error": f"Failed to build the workbook: {e}"}), 500

    return send_file(
        buf,
        as_attachment=True,
        download_name="bill_wise_statement.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/presets")
def presets():
    return jsonify({"presets": list_presets()})


@app.route("/generate_preset", methods=["POST"])
def generate_preset():
    payload = request.get_json(silent=True) or {}
    job = _ready_job(payload.get("token"))
    if not job:
        return jsonify({"error": "Session expired or still processing. Re-upload the PDFs."}), 400
    preset = get_preset(payload.get("preset_id"))
    if not preset:
        return jsonify({"error": "Unknown preset."}), 400
    try:
        buf = build_preset_workbook(job["parsed"], preset)
    except Exception as e:
        return jsonify({"error": f"Failed to build the workbook: {e}"}), 500
    return send_file(
        buf,
        as_attachment=True,
        download_name="bill_statement_full.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/nl_request", methods=["POST"])
def nl_request():
    """Plain-English request -> the LLM returns only a small spec (which items,
    schedules, column, totals); the numbers are then pulled deterministically
    from the already-extracted bills. The model never sees the figures."""
    payload = request.get_json(silent=True) or {}
    job = _ready_job(payload.get("token"))
    if not job:
        return jsonify({"error": "Session expired or still processing. Re-upload."}), 400
    req = (payload.get("request") or "").strip()
    if not req:
        return jsonify({"error": "Type what you want first."}), 400

    parsed = job["parsed"]
    # Build the catalogue (small) the model reasons over — never the amounts.
    all_items = sorted({(r["schedule"], r["item"]) for b in parsed for r in b["rows"]})
    catalogue = [{"schedule": s, "item": i,
                  "description": next((r["description"][:60] for b in parsed
                                       for r in b["rows"] if r["item"] == i and r["schedule"] == s), "")}
                 for s, i in all_items]

    spec, err = interpret_request(req, catalogue)
    if err:
        return jsonify({"error": err}), 200  # soft error, show to user
    # Deterministic build from the spec
    try:
        from nl_build import build_from_spec
        buf, info = build_from_spec(parsed, spec)
    except Exception as e:
        return jsonify({"error": f"Could not build from the request: {e}"}), 500
    JOBS[payload["token"]]["nl_buf"] = buf.getvalue()
    return jsonify({"status": "ok", "understood": info})


@app.route("/download_nl/<token>")
def download_nl(token):
    job = _ready_job(token)
    if not job or "nl_buf" not in job:
        return jsonify({"error": "Nothing to download yet."}), 400
    import io as _io
    return send_file(_io.BytesIO(job["nl_buf"]), as_attachment=True,
                     download_name="statement.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/generate_raw", methods=["POST"])
def generate_raw():
    payload = request.get_json(silent=True) or {}
    job = _ready_job(payload.get("token"))
    if not job:
        return jsonify({"error": "Session expired or still processing. Re-upload the PDFs."}), 400
    try:
        buf = build_raw_workbook(job["parsed"])
    except Exception as e:
        return jsonify({"error": f"Failed to build the workbook: {e}"}), 500
    return send_file(
        buf,
        as_attachment=True,
        download_name="bills_full_extract.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/prompts")
def prompts():
    return jsonify({"prompts": list_templates()})


@app.route("/prompt_details/<prompt_id>")
def prompt_details(prompt_id):
    t = get_template(prompt_id)
    if not t:
        return jsonify({"error": "Unknown prompt template."}), 404
    return jsonify(t)


@app.route("/extract_with_prompt", methods=["POST"])
def extract_with_prompt():
    """Start a Groq extraction job in background."""
    _cleanup_jobs()
    files = request.files.getlist("pdfs")
    payload = request.form.to_dict()
    
    if not files or not payload.get("prompt_id"):
        return jsonify({"error": "No PDFs or prompt template selected."}), 400

    token, d, saved = _save_uploads(files)
    if not saved:
        return jsonify({"error": "No valid .pdf files in the upload."}), 400

    # Render the prompt template with any variable overrides from the form
    t = get_template(payload.get("prompt_id"))
    if not t:
        return jsonify({"error": "Unknown prompt template."}), 400
    
    overrides = {k: v for k, v in payload.items()
                 if k not in ("prompt_id", "csrftoken", "provider", "extra_instructions")}
    prompt = render_prompt(payload.get("prompt_id"), **overrides)
    if not prompt:
        return jsonify({"error": "Could not render the prompt."}), 400

    extra = (payload.get("extra_instructions") or "").strip()
    if extra:
        prompt += ("\n\nADDITIONAL INSTRUCTIONS (apply these on top of the above, "
                   "but still return only the JSON described):\n" + extra)

    JOBS[token] = {"status": "processing", "total": len(saved), "done": 0,
                   "groq_data": None, "error": None,
                   "dir": d, "ts": time.time(), "prompt_id": payload.get("prompt_id")}
    provider = (payload.get("provider") or "claude").lower()
    threading.Thread(target=_groq_job, args=(token, saved, prompt, provider),
                     kwargs={"prompt_id": payload.get("prompt_id")}, daemon=True).start()
    return jsonify({"token": token, "status": "processing", "total": len(saved)})


@app.route("/providers")
def providers():
    """Which LLM providers have a key configured."""
    return jsonify({"providers": available_providers()})


@app.route("/groq_status/<token>")
def groq_status(token):
    job = JOBS.get(token)
    if not job:
        return jsonify({"error": "Unknown or expired job."}), 404
    if job["status"] == "done":
        return jsonify({"status": "done", "data": job.get("groq_data")})
    if job["status"] == "error":
        return jsonify({"status": "error", "error": job.get("error", "Unknown error")}), 500
    return jsonify({"status": "processing", "done": job["done"], "total": job["total"]})


@app.route("/generate_from_groq", methods=["POST"])
def generate_from_groq():
    payload = request.get_json(silent=True) or {}
    job = JOBS.get(payload.get("token"))
    if not job or job["status"] != "done":
        return jsonify({"error": "Job not ready or expired."}), 400
    
    prompt_id = job.get("prompt_id")
    template = get_template(prompt_id)
    if not template:
        return jsonify({"error": "Template not found."}), 400
    
    try:
        from groq_to_excel import groq_json_to_excel
        buf = groq_json_to_excel(job.get("groq_data", {}), template)
    except Exception as e:
        return jsonify({"error": f"Failed to build Excel: {e}"}), 500
    
    return send_file(
        buf,
        as_attachment=True,
        download_name=f"{template['output_format'].replace(' ', '_')}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/healthz")
def healthz():
    return "ok", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
