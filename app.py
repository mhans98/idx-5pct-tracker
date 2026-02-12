"""
IDX 5% Shareholder Tracker - Flask App
Serves the dashboard UI and provides scraper API endpoints.
Deploy on Render free tier.
"""

import os
import logging
from flask import Flask, render_template, jsonify
from scraper import run_scrape, load_data

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# In-memory cache of latest scrape result
_cached_data = None
_scraping = False


@app.route("/")
def index():
    """Serve the dashboard."""
    return render_template("index.html")


@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    """Trigger a new scrape (called by 'Get Data' button)."""
    global _cached_data, _scraping

    if _scraping:
        return jsonify({"success": False, "error": "Scrape already in progress"}), 429

    _scraping = True
    try:
        logger.info("Scrape triggered via API")
        result = run_scrape(days_back=7)
        _cached_data = result
        return jsonify(result)
    except Exception as e:
        logger.exception("Scrape failed")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        _scraping = False


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


@app.route("/api/status")
def api_status():
    return jsonify({
        "status": "running",
        "has_data": _cached_data is not None and bool(_cached_data.get("records")),
        "scraping": _scraping,
        "last_scrape": _cached_data.get("scraped_at") if _cached_data else None,
        "total_records": _cached_data.get("total_records", 0) if _cached_data else 0,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
