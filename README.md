# IDX 5% Shareholder Tracker

Dashboard that scrapes and displays daily **5% shareholder ownership changes** from the Indonesia Stock Exchange (IDX/BEI).

**Data Source:** [IDX Keterbukaan Informasi](https://www.idx.co.id/id/perusahaan-tercatat/keterbukaan-informasi) → KSEI daily PDF reports

---

## How It Works

1. You press **"Get Data"** on the dashboard
2. The server scrapes the last 7 days of 5% shareholder PDFs from IDX
3. PDFs are parsed into structured data and displayed in the dashboard
4. Timestamp shows when data was last fetched

## Features

- **Manual scrape trigger** — "Get Data" button fetches last 7 days
- **Scrape timestamp** — shows exact date/time of latest data
- **Search** — filter by ticker, company, or shareholder name
- **Date filter** — view specific dates
- **Change filter** — accumulation / distribution / no change
- **Sort** — click any column header
- **Ownership bars** — visual percentage display
- **CSV export** — download filtered data
- **Net change badges** — color-coded with % change

---

## Deploy to Render (Free)

### Step 1: Push to GitHub

```bash
# Create a new repo on GitHub, then:
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/idx-5pct-tracker.git
git push -u origin main
```

### Step 2: Deploy on Render

1. Go to [render.com](https://render.com) and sign in
2. Click **"New +"** → **"Web Service"**
3. Connect your GitHub repo: `idx-5pct-tracker`
4. Settings:
   - **Name:** `idx-5pct-tracker`
   - **Runtime:** Python
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app --bind 0.0.0.0:$PORT --timeout 120 --workers 1`
   - **Plan:** Free
5. Click **"Create Web Service"**
6. Wait for deploy (~2-3 minutes)
7. Your dashboard is live at `https://idx-5pct-tracker.onrender.com`

### Step 3: Use It

1. Open your Render URL
2. Press **"Get Data"** — it will scrape IDX (takes 30-60 seconds)
3. Data loads into the dashboard
4. Press "Get Data" again anytime you want fresh data

---

## Run Locally

```bash
pip install -r requirements.txt
python app.py
# Open http://localhost:5000
```

---

## Project Structure

```
idx-5pct-tracker/
├── app.py              # Flask server (dashboard + API)
├── scraper.py          # PDF scraper logic
├── templates/
│   └── index.html      # Dashboard UI
├── data/
│   ├── pdfs/           # Downloaded PDFs (gitignored)
│   └── json/           # Parsed JSON (gitignored)
├── requirements.txt    # Python dependencies
├── render.yaml         # Render deploy config
└── README.md
```

## Notes

- **Render free tier** spins down after 15 min of inactivity. First visit after sleep takes ~30 seconds to wake up.
- **IDX may block requests** — if scrape fails, try again in a few minutes.
- **Data resets on redeploy** since Render free tier has ephemeral storage. Just press "Get Data" again.
- The scraper downloads PDFs from IDX's public disclosure page, which is within their terms for informational use.

## License

MIT — Data copyright belongs to IDX/KSEI.
