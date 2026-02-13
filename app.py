"""
IDX 5% Shareholder Tracker - Flask App
Serves the dashboard UI and provides scraper API endpoints.
Deploy on Render free tier.

Scraping runs in a BACKGROUND THREAD so it won't hit
Render's 120s request timeout (30 days of PDFs can take 2-3 min).
"""

import os
import logging
import threading
from datetime import datetime
from flask import Flask, render_template, jsonify
from scraper import run_scrape, load_data

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# In-memory state
_cached_data = None
_scraping = False
_scrape_progress = ""


def background_scrape():
    """Run scrape in background thread."""
    global _cached_data, _scraping, _scrape_progress
    try:
        # Check if this is first run or incremental
        existing = load_data()
        if existing and existing.get("records"):
            _scrape_progress = "Incremental update — fetching new data since last scrape..."
        else:
            _scrape_progress = "First run — fetching last 90 days from IDX..."

        result = run_scrape()  # Smart mode: auto-decides days_back
        _cached_data = result

        if result.get("success") and result.get("total_records", 0) > 0:
            mode = result.get("mode", "backfill")
            new_ct = result.get("new_records", 0)
            total = result["total_records"]
            if mode == "incremental":
                _scrape_progress = f"Done! +{new_ct} new records ({total} total)"
            else:
                _scrape_progress = f"Done! {total} records from {result.get('pdfs_parsed', 0)} PDFs (90-day backfill)"
        else:
            errors = result.get("errors", [])
            _scrape_progress = f"Completed with issues: {errors[0] if errors else 'No records found'}"

        logger.info(f"Background scrape finished: {result.get('total_records', 0)} records, mode={result.get('mode')}")
    except Exception as e:
        logger.exception("Background scrape failed")
        _scrape_progress = f"Error: {str(e)}"
    finally:
        _scraping = False


@app.route("/")
def index():
    """Serve the dashboard."""
    return render_template("index.html")


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    """Start a background scrape (called by 'Get Data' button)."""
    global _scraping, _scrape_progress

    if _scraping:
        return jsonify({
            "started": False,
            "message": "Scrape already in progress",
            "progress": _scrape_progress,
        }), 429

    _scraping = True
    _scrape_progress = "Starting..."

    thread = threading.Thread(target=background_scrape, daemon=True)
    thread.start()

    logger.info("Background scrape started (smart mode)")
    return jsonify({
        "started": True,
        "message": "Scrape started in background. Polling for status...",
    })


@app.route("/api/status")
def api_status():
    """Poll this to check if scrape is done."""
    return jsonify({
        "status": "running",
        "scraping": _scraping,
        "progress": _scrape_progress,
        "has_data": _cached_data is not None and bool(_cached_data.get("records")),
        "last_scrape": _cached_data.get("scraped_at") if _cached_data else None,
        "total_records": _cached_data.get("total_records", 0) if _cached_data else 0,
    })


@app.route("/api/data")
def api_data():
    """Return cached data or load from disk."""
    global _cached_data

    if _cached_data and _cached_data.get("records"):
        return jsonify(_cached_data)

    # Try loading from disk
    disk_data = load_data()
    if disk_data:
        _cached_data = disk_data
        return jsonify(disk_data)

    return jsonify({
        "success": True,
        "scraped_at": None,
        "total_records": 0,
        "records": [],
        "message": "No data yet. Press 'Get Data' to scrape."
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
