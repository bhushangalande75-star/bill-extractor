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
import json
import shutil
import tempfile

from flask import Flask, request, jsonify, send_file, render_template
from werkzeug.utils import secure_filename
from werkzeug.exceptions import HTTPException

from extractor import summarize, extract_rows
from excel_builder import build_workbook

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024   # 40 MB per request


@app.errorhandler(Exception)
def json_errors(e):
    """Never let an API call receive an HTML error page (which breaks the
    frontend's res.json()). Client errors keep their normal page; anything
    else comes back as JSON."""
    if isinstance(e, HTTPException) and (e.code or 500) < 500:
        return e
    return jsonify({"error": f"Server error: {e}"}), 500

# In-memory session store: token -> {"dir": path, "files": [(path, name), ...]}.
# Fine for a single-process deployment; swap for Redis/disk-token store if you
# need to support many concurrent users.
SESSIONS = {}


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


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    files = request.files.getlist("pdfs")
    if not files:
        return jsonify({"error": "No PDF files received."}), 400

    token, d, saved = _save_uploads(files)
    if not saved:
        return jsonify({"error": "No valid .pdf files in the upload."}), 400

    try:
        parsed = []
        for path, name in saved:
            pb = extract_rows(path)      # parse ONCE here
            pb["file"] = name
            parsed.append(pb)
        result = summarize(parsed)
    except Exception as e:
        shutil.rmtree(d, ignore_errors=True)
        return jsonify({"error": f"Could not read the PDF(s): {e}"}), 500

    # cache the parsed rows so /generate does not re-parse
    SESSIONS[token] = {"dir": d, "parsed": parsed}
    result["token"] = token
    return jsonify(result)


@app.route("/generate", methods=["POST"])
def generate():
    payload = request.get_json(silent=True) or {}
    token = payload.get("token")
    session = SESSIONS.get(token)
    if not session:
        return jsonify({"error": "Session expired. Please re-upload the PDFs."}), 400

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
        buf = build_workbook(session["parsed"], config)   # reuse cached parse
    except Exception as e:
        return jsonify({"error": f"Failed to build the workbook: {e}"}), 500

    return send_file(
        buf,
        as_attachment=True,
        download_name="bill_wise_statement.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/healthz")
def healthz():
    return "ok", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
