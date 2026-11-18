"""Fetch NSE provisional FII/DII cash-market figures and append them to fii_dii.csv.
Runs on GitHub Actions (or any computer). Exits with an error if NSE does not return data."""
import csv
import datetime
import os
import sys
import time

import requests

OUT = "fii_dii.csv"
HEAD = ["date", "category", "buy", "sell", "net", "fetched_utc", "source"]
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}


def num(x):
    try:
        return float(str(x).replace(",", "").strip())
    except ValueError:
        return 0.0


def fetch():
    s = requests.Session()
    s.headers.update(HEADERS)
    s.get("https://www.nseindia.com/", timeout=30)  # obtain session cookies
    last = None
    for i in range(4):
        try:
            r = s.get("https://www.nseindia.com/api/fiidiiTradeReact", timeout=30)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list) and data:
                    return data
                last = "empty or unexpected payload"
            else:
                last = f"HTTP {r.status_code}"
        except Exception as e:  # network error, JSON error
            last = str(e)
        time.sleep(5 * (i + 1))
    sys.exit(f"NSE fetch failed: {last}")


def main():
    data = fetch()
    existing = set()
    if os.path.exists(OUT):
        with open(OUT, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                existing.add((row["date"], row["category"]))
    new_rows = []
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    for d in data:
        c = str(d.get("category", ""))
        cat = "DII" if "DII" in c.upper() else ("FII/FPI" if ("FII" in c.upper() or "FPI" in c.upper()) else None)
        if not cat:
            continue
        key = (str(d.get("date", "")).strip(), cat)
        if key in existing or not key[0]:
            continue
        existing.add(key)
        new_rows.append([key[0], cat, num(d.get("buyValue")), num(d.get("sellValue")), num(d.get("netValue")), now, "NSE fiidiiTradeReact"])
    write_header = not os.path.exists(OUT)
    with open(OUT, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(HEAD)
        w.writerows(new_rows)
    print(f"Added {len(new_rows)} new rows")


if __name__ == "__main__":
    main()
