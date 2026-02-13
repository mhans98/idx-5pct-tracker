"""
IDX 5% Shareholder PDF Parser
Parses KSEI 5% shareholder PDFs that are manually uploaded.
No web scraping needed.
"""

import re
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

import pdfplumber

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
PDF_DIR = DATA_DIR / "pdfs"
JSON_DIR = DATA_DIR / "json"


def ensure_dirs():
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    JSON_DIR.mkdir(parents=True, exist_ok=True)


def parse_pdf(filepath):
    """Parse KSEI 5% shareholder PDF into records."""
    filepath = Path(filepath)
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

    shareholder = ""
    for j in range(ti + 2, min(ti + 5, len(cells))):
        if cells[j] and not is_num(cells[j]):
            shareholder = cells[j]
            break

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


def process_uploaded_pdfs(filepaths):
    """
    Parse one or more uploaded PDFs. Merge with existing data.
    Returns result dict.
    """
    ensure_dirs()
    existing = load_data()
    old_records = existing.get("records", []) if existing else []

    result = {
        "success": False,
        "scraped_at": datetime.now().isoformat(),
        "pdfs_parsed": 0,
        "total_records": 0,
        "new_records": 0,
        "records": [],
        "errors": [],
    }

    new_records = []
    for fp in filepaths:
        try:
            records = parse_pdf(fp)
            if records:
                result["pdfs_parsed"] += 1
                new_records.extend(records)
            else:
                result["errors"].append(f"No records found in: {Path(fp).name}")
        except Exception as e:
            result["errors"].append(f"Error parsing {Path(fp).name}: {str(e)}")

    # Merge with existing
    all_records = old_records + new_records

    # De-duplicate
    seen = set()
    unique = []
    for r in all_records:
        key = (r["run_date"], r["ticker"], r["shareholder"])
        if key not in seen:
            seen.add(key)
            unique.append(r)

    # Sort by run_date desc, then net_change desc
    unique.sort(key=lambda x: (x.get("run_date", ""), abs(x["net_change"])), reverse=True)

    # Count new
    old_keys = set()
    for r in old_records:
        old_keys.add((r["run_date"], r["ticker"], r["shareholder"]))
    new_count = sum(1 for r in unique
                    if (r["run_date"], r["ticker"], r["shareholder"]) not in old_keys)

    result["records"] = unique
    result["total_records"] = len(unique)
    result["new_records"] = new_count
    result["success"] = True

    save_data(unique, result["scraped_at"])
    return result


def save_data(records, scraped_at):
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
    path = JSON_DIR / "latest.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None
