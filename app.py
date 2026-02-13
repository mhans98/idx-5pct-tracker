"""
IDX 5% Shareholder Tracker - Flask App
Upload KSEI PDFs manually, dashboard parses and displays data.
"""

import os
import logging
import threading
from pathlib import Path
from flask import Flask, render_template, jsonify, request
from scraper import process_uploaded_pdfs, load_data, ensure_dirs, PDF_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder=".")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB max upload

_cached_data = None
_processing = False
_progress = ""


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/upload", methods=["POST"])
def api_upload():
    """Handle PDF file uploads."""
    global _cached_data, _processing, _progress

    if _processing:
        return jsonify({"success": False, "error": "Already processing"}), 429

    files = request.files.getlist("pdfs")
    if not files or all(f.filename == "" for f in files):
        return jsonify({"success": False, "error": "No files uploaded"}), 400

    ensure_dirs()
    saved_paths = []
    for f in files:
        if f.filename and f.filename.lower().endswith(".pdf"):
            filepath = PDF_DIR / f.filename
            f.save(str(filepath))
            saved_paths.append(str(filepath))
            logger.info(f"Saved upload: {f.filename}")

    if not saved_paths:
        return jsonify({"success": False, "error": "No valid PDF files found"}), 400

    _processing = True
    _progress = f"Parsing {len(saved_paths)} PDF(s)..."

    def process():
        global _cached_data, _processing, _progress
        try:
            result = process_uploaded_pdfs(saved_paths)
            _cached_data = result
            if result["success"]:
                _progress = f"Done! +{result['new_records']} new records ({result['total_records']} total)"
            else:
                _progress = f"Issues: {result['errors'][0] if result['errors'] else 'Unknown'}"
        except Exception as e:
            logger.exception("Processing failed")
            _progress = f"Error: {str(e)}"
        finally:
            _processing = False

    thread = threading.Thread(target=process, daemon=True)
    thread.start()

    return jsonify({
        "started": True,
        "files": len(saved_paths),
        "message": f"Processing {len(saved_paths)} PDF(s)...",
    })


@app.route("/api/data")
def api_data():
    global _cached_data
    if _cached_data and _cached_data.get("records"):
        return jsonify(_cached_data)

    disk_data = load_data()
    if disk_data:
        _cached_data = disk_data
        return jsonify(disk_data)

    return jsonify({
        "success": True,
        "scraped_at": None,
        "total_records": 0,
        "records": [],
    })


@app.route("/api/status")
def api_status():
    return jsonify({
        "status": "running",
        "processing": _processing,
        "progress": _progress,
        "has_data": _cached_data is not None and bool(_cached_data.get("records")),
        "last_scrape": _cached_data.get("scraped_at") if _cached_data else None,
        "total_records": _cached_data.get("total_records", 0) if _cached_data else 0,
    })


@app.route("/api/clear", methods=["POST"])
def api_clear():
    """Clear all data and start fresh."""
    global _cached_data
    _cached_data = None
    json_path = Path("data/json/latest.json")
    if json_path.exists():
        json_path.unlink()
    return jsonify({"success": True, "message": "Data cleared"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
