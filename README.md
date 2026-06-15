# BillExtractor — PDF Bill → Excel

A small web app that reads CR/BSL civil bill PDFs and produces a **bill-wise
statement** in Excel (schedule-wise, item-wise). Amounts are read straight
from the PDF tables with `pdfplumber` — **no LLM touches the numbers**, so
figures cannot be invented. The filter shown in the UI is built from whatever
PDF you upload.

## How it works

1. Upload one PDF per bill (B1…B10).
2. The app reads the bills and shows the schedules + item numbers it found.
3. You pick the value column (default: *Amount Since last Bill including
   special condition*) and the items (and optionally schedules).
4. Download the statement `.xlsx`.

## Project layout

```
bill-extractor/
├── app.py              # Flask routes: / , /analyze , /generate
├── extractor.py        # pdfplumber table extraction (no AI)
├── excel_builder.py    # openpyxl statement builder
├── templates/index.html
├── static/style.css    # SocietyNotice mint/teal theme
├── requirements.txt
├── Procfile            # gunicorn start command
├── render.yaml         # one-click Render config
└── runtime.txt
```

## Run locally (VS Code)

```bash
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux:  source .venv/bin/activate
pip install -r requirements.txt
python app.py
```
Open http://localhost:5000

## Push to GitHub

```bash
git init
git add .
git commit -m "BillExtractor: PDF bill to Excel"
git branch -M main
git remote add origin https://github.com/<your-username>/bill-extractor.git
git push -u origin main
```

## Deploy on Render

**Option A — Blueprint (uses render.yaml):**
1. Render dashboard → **New** → **Blueprint** → connect this GitHub repo.
2. Render reads `render.yaml` and creates the service. Click **Apply**.

**Option B — Manual:**
1. **New** → **Web Service** → connect the repo.
2. Runtime: **Python 3**
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app`
5. Plan: Free → **Create Web Service**.

Render sets `$PORT` automatically; `gunicorn app:app` binds to it.

## Notes & limits

- Built and verified against CR/BSL item-wise bills (15-column table layout).
  Item numbers like `0330 62` are normalised to `033062` automatically.
- The session store is in-memory (single process). For many concurrent users,
  move it to Redis or a token-keyed disk store.
- On Render free tier the service sleeps when idle and the first request after
  sleep is slow — normal for free plans.
- Always spot-check a couple of figures against the bill before filing, as a
  matter of habit.
