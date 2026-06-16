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


@app.route("/healthz")
def healthz():
    return "ok", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
