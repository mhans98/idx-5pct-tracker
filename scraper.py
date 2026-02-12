"""
IDX 5% Shareholder PDF Scraper
Fetches and parses KSEI 5% shareholder reports from IDX.co.id
"""

import re
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup
import pdfplumber

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
PDF_DIR = DATA_DIR / "pdfs"
JSON_DIR = DATA_DIR / "json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
    "Referer": "https://www.idx.co.id/id/perusahaan-tercatat/keterbukaan-informasi",
    "X-Requested-With": "XMLHttpRequest",
}

IDX_API_URLS = [
    "https://www.idx.co.id/primary/ListedCompany/GetAnnouncementStock",
    "https://www.idx.co.id/umbraco/Surface/ListedCompany/GetAnnouncementStock",
]


def ensure_dirs():
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    JSON_DIR.mkdir(parents=True, exist_ok=True)


def fetch_announcements(days_back=7):
    """Fetch 5% shareholder announcement list from IDX."""
    today = datetime.now()
    date_from = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
    date_to = today.strftime("%Y-%m-%d")

    params = {
        "indexFrom": 0,
        "pageSize": 30,
        "keyword": "5%",
        "dateFrom": date_from,
        "dateTo": date_to,
    }

    session = requests.Session()
    session.headers.update(HEADERS)

    for api_url in IDX_API_URLS:
        try:
            logger.info(f"Trying: {api_url}")
            resp = session.get(api_url, params=params, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("Results", data.get("results", []))
                if results:
                    logger.info(f"Found {len(results)} announcements")
                    return results, session
        except Exception as e:
            logger.warning(f"Error with {api_url}: {e}")

    logger.warning("API failed, trying HTML fallback")
    return fetch_via_html(session, days_back), session


def fetch_via_html(session, days_back=7):
    """Fallback: try to find PDF links from the HTML page."""
    try:
        resp = session.get(
            "https://www.idx.co.id/id/perusahaan-tercatat/keterbukaan-informasi",
            timeout=30
        )
        if resp.status_code != 200:
            return []

        soup = BeautifulSoup(resp.text, "html.parser")
        results = []
        for link in soup.find_all("a", href=True):
            href = link["href"]
            if "lamp1" in href.lower() and href.endswith(".pdf"):
                full_url = href if href.startswith("http") else "https://www.idx.co.id" + href
                results.append({"Attachments": [{"FileUrl": full_url}]})
        return results
    except Exception as e:
        logger.error(f"HTML fallback failed: {e}")
        return []


def get_pdf_url(announcement):
    """Extract PDF attachment URL from announcement."""
    for key in ["Attachments", "attachments"]:
        attachments = announcement.get(key, [])
        for att in attachments:
            for url_key in ["FileUrl", "fileUrl", "file_url"]:
                url = att.get(url_key, "")
                if url and ("lamp1" in url.lower() or url.endswith(".pdf")):
                    if not url.startswith("http"):
                        url = "https://www.idx.co.id" + url
                    return url
    return None


def download_pdf(url, session):
    """Download a PDF, return local path."""
    filename = url.split("/")[-1]
    if not filename.endswith(".pdf"):
        filename += ".pdf"
    filepath = PDF_DIR / filename

    if filepath.exists():
        logger.info(f"Already have: {filename}")
        return filepath

    try:
        resp = session.get(url, timeout=60)
        if resp.status_code == 200 and len(resp.content) > 1000:
            filepath.write_bytes(resp.content)
            logger.info(f"Downloaded: {filename} ({len(resp.content):,} bytes)")
            return filepath
        else:
            logger.error(f"Download failed: status={resp.status_code}")
    except Exception as e:
        logger.error(f"Download error: {e}")
    return None


def parse_pdf(filepath):
    """Parse KSEI 5% shareholder PDF into records."""
    logger.info(f"Parsing: {filepath.name}")
    records = []

    try:
        with pdfplumber.open(filepath) as pdf:
            first_text = pdf.pages[0].extract_text() or ""
            dates = extract_dates(first_text)
            d2_date = dates.get("d2", "")
            d1_date = dates.get("d1", "")

            all_rows = []
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    if table:
                        all_rows.extend(table)

            # Extract run_date from filename
            run_date = ""
            m = re.match(r"(\d{8})", filepath.name)
            if m:
                d = m.group(1)
                run_date = f"{d[:4]}-{d[4:6]}-{d[6:8]}"

            for row in all_rows:
                if not row or all(c is None or str(c).strip() == "" for c in row):
                    continue
                cells = [str(c).strip() if c else "" for c in row]
                if any(h in " ".join(cells).upper() for h in ["KODE EFEK", "NAMA EMITEN", "KEPEMILIKAN PER"]):
                    continue

                rec = try_extract_record(cells, d2_date, d1_date, run_date)
                if rec:
                    records.append(rec)

    except Exception as e:
        logger.error(f"Parse error on {filepath.name}: {e}")

    logger.info(f"Extracted {len(records)} records from {filepath.name}")
    return records


def extract_dates(text):
    """Extract D-1 and D-2 dates from PDF header."""
    dates = {}
    patterns = [
        r"(\d{1,2}-[A-Z]{3}-\d{4})",
        r"[Pp]er\s*(?:tanggal\s*)?(\d{1,2}[-/]\w{3,9}[-/]\d{4})",
    ]
    found = []
    for pat in patterns:
        for m in re.findall(pat, text):
            parsed = try_parse_date(m)
            if parsed and parsed not in found:
                found.append(parsed)

    found.sort()
    if len(found) >= 2:
        dates["d2"] = found[-2]
        dates["d1"] = found[-1]
    elif len(found) == 1:
        dates["d1"] = found[0]
        d1 = datetime.strptime(found[0], "%Y-%m-%d")
        d2 = d1 - timedelta(days=1)
        while d2.weekday() >= 5:
            d2 -= timedelta(days=1)
        dates["d2"] = d2.strftime("%Y-%m-%d")
    return dates


MONTH_MAP = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04", "MAY": "05", "MEI": "05",
    "JUN": "06", "JUL": "07", "AUG": "08", "AGU": "08", "SEP": "09",
    "OCT": "10", "OKT": "10", "NOV": "11", "DEC": "12", "DES": "12",
}


def try_parse_date(s):
    s = s.strip()
    m = re.match(r"(\d{1,2})[-/\s](\w{3,9})[-/\s](\d{4})", s)
    if m:
        day, mon, year = m.groups()
        mm = MONTH_MAP.get(mon.upper()[:3])
        if mm:
            return f"{year}-{mm}-{int(day):02d}"
    return None


def try_extract_record(cells, d2_date, d1_date, run_date):
    """Try to extract a shareholder record from a table row."""
    if len(cells) < 5:
        return None

    # Find ticker (4 uppercase letters)
    ticker = ""
    ti = -1
    for i, c in enumerate(cells):
        if re.match(r"^[A-Z]{4}$", c):
            ticker = c
            ti = i
            break
    if not ticker:
        return None

    nama = cells[ti + 1] if ti + 1 < len(cells) else ""

    # Find shareholder name (non-numeric cell after company name)
    shareholder = ""
    for j in range(ti + 2, min(ti + 5, len(cells))):
        if cells[j] and not is_num(cells[j]):
            shareholder = cells[j]
            break

    # Find numeric values
    large_nums = []
    small_nums = []
    for c in cells:
        if is_num(c):
            n = parse_num(c)
            if n > 100:
                large_nums.append(n)
            elif 0 < n <= 100:
                small_nums.append(n)

    shares_d2 = int(large_nums[0]) if len(large_nums) >= 1 else 0
    shares_d1 = int(large_nums[1]) if len(large_nums) >= 2 else shares_d2
    pct_d2 = round(small_nums[0], 2) if len(small_nums) >= 1 else 0
    pct_d1 = round(small_nums[1], 2) if len(small_nums) >= 2 else pct_d2

    if shares_d2 == 0 and shares_d1 == 0:
        return None

    net = shares_d1 - shares_d2
    return {
        "run_date": run_date or d1_date,
        "d2_date": d2_date,
        "d1_date": d1_date,
        "ticker": ticker,
        "nama_emiten": clean(nama),
        "shareholder": clean(shareholder),
        "shares_d2": shares_d2,
        "pct_d2": pct_d2,
        "shares_d1": shares_d1,
        "pct_d1": pct_d1,
        "net_change": net,
    }


def is_num(s):
    if not s:
        return False
    return s.replace(",", "").replace(".", "").replace(" ", "").replace("-", "").isdigit()


def parse_num(s):
    s = s.strip().replace(" ", "")
    if s.count(".") > 1:
        s = s.replace(".", "")
    elif s.count(",") > 1:
        s = s.replace(",", "")
    elif "," in s and len(s.split(",")[-1]) <= 4:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0


def clean(s):
    return re.sub(r"\s+", " ", (s or "")).strip()


def run_scrape(days_back=7):
    """
    Main scrape function. Returns dict with results.
    Called by Flask when user presses "Get Data".
    """
    ensure_dirs()
    logger.info(f"Starting scrape (last {days_back} days)")

    result = {
        "success": False,
        "scraped_at": datetime.now().isoformat(),
        "pdfs_found": 0,
        "pdfs_downloaded": 0,
        "pdfs_parsed": 0,
        "total_records": 0,
        "records": [],
        "errors": [],
    }

    try:
        announcements, session = fetch_announcements(days_back)
        result["pdfs_found"] = len(announcements)

        if not announcements:
            result["errors"].append("No announcements found from IDX API")
            return result

        all_records = []
        for ann in announcements:
            pdf_url = get_pdf_url(ann)
            if not pdf_url:
                continue

            pdf_path = download_pdf(pdf_url, session)
            if not pdf_path:
                result["errors"].append(f"Failed to download: {pdf_url.split('/')[-1]}")
                continue
            result["pdfs_downloaded"] += 1

            records = parse_pdf(pdf_path)
            if records:
                result["pdfs_parsed"] += 1
                all_records.extend(records)
            else:
                result["errors"].append(f"No records parsed from: {pdf_path.name}")

        # De-duplicate by (run_date, ticker, shareholder)
        seen = set()
        unique = []
        for r in all_records:
            key = (r["run_date"], r["ticker"], r["shareholder"])
            if key not in seen:
                seen.add(key)
                unique.append(r)

        # Sort by net_change descending
        unique.sort(key=lambda x: abs(x["net_change"]), reverse=True)

        result["records"] = unique
        result["total_records"] = len(unique)
        result["success"] = True

        # Save combined JSON
        save_data(unique, result["scraped_at"])

    except Exception as e:
        logger.exception("Scrape failed")
        result["errors"].append(str(e))

    return result


def save_data(records, scraped_at):
    """Save records to JSON file."""
    ensure_dirs()
    data = {
        "scraped_at": scraped_at,
        "total_records": len(records),
        "records": records,
    }
    path = JSON_DIR / "latest.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved {len(records)} records to {path}")


def load_data():
    """Load the most recent scraped data."""
    path = JSON_DIR / "latest.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None
