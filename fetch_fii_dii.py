"""Download NSE data the Google Sheet cannot reach, and save it in this repository:
  fii_dii.csv                          FII/DII cash figures (history accumulates)
  data/fao_participant_oi_latest.csv   F&O participant-wise open interest (latest day)
  data/bhav_latest.csv                 Equity delivery data (latest day, EQ series, trimmed)
  data/bulk.csv, data/block.csv        Bulk / block deals (history accumulates)
  data/ind_nifty500list.csv            Sector classification
  data/dates.json                      Trading date of each latest file
Each source is independent: one failing does not stop the others."""
import csv
import datetime
import io
import json
import os
import sys
import time

import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}
ARCH = "https://nsearchives.nseindia.com"
os.makedirs("data", exist_ok=True)
DATES_FILE = "data/dates.json"
dates = json.load(open(DATES_FILE)) if os.path.exists(DATES_FILE) else {}
failures = []


def num(x):
    try:
        return float(str(x).replace(",", "").strip())
    except ValueError:
        return 0.0


def get_text(url, tries=3):
    for i in range(tries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=40)
            if r.status_code == 200 and len(r.text) > 20 and not r.text.lstrip().startswith("<"):
                return r.text
        except Exception:
            pass
        time.sleep(4 * (i + 1))
    return None


def recent_weekdays(n=6):
    d = datetime.date.today()
    out = []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= datetime.timedelta(days=1)
    return out


def step(name, fn):
    try:
        print(f"{name}: {fn()}")
    except Exception as e:
        failures.append(name)
        print(f"{name}: FAILED - {e}")


def fii_dii():
    s = requests.Session()
    s.headers.update(HEADERS)
    s.get("https://www.nseindia.com/", timeout=30)
    data = None
    for i in range(4):
        r = s.get("https://www.nseindia.com/api/fiidiiTradeReact", timeout=30)
        if r.status_code == 200:
            j = r.json()
            if isinstance(j, list) and j:
                data = j
                break
        time.sleep(5 * (i + 1))
    if not data:
        raise RuntimeError("no data from NSE")
    out = "fii_dii.csv"
    seen = set()
    if os.path.exists(out):
        with open(out, newline="", encoding="utf-8") as f:
            seen = {(r["date"], r["category"]) for r in csv.DictReader(f)}
    now = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    rows = []
    for d in data:
        c = str(d.get("category", "")).upper()
        cat = "DII" if "DII" in c else ("FII/FPI" if ("FII" in c or "FPI" in c) else None)
        key = (str(d.get("date", "")).strip(), cat)
        if not cat or not key[0] or key in seen:
            continue
        seen.add(key)
        rows.append([key[0], cat, num(d.get("buyValue")), num(d.get("sellValue")), num(d.get("netValue")), now, "NSE fiidiiTradeReact"])
    new = not os.path.exists(out)
    with open(out, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["date", "category", "buy", "sell", "net", "fetched_utc", "source"])
        w.writerows(rows)
    return f"{len(rows)} new rows"


def participant_oi():
    for d in recent_weekdays():
        t = get_text(f"{ARCH}/content/nsccl/fao_participant_oi_{d:%d%m%Y}.csv", tries=1)
        if t:
            open("data/fao_participant_oi_latest.csv", "w", encoding="utf-8").write(t)
            dates["oi"] = f"{d:%d-%m-%Y}"
            return f"saved {dates['oi']}"
    raise RuntimeError("no file in last 6 weekdays")


def bhav():
    keep = ["SYMBOL", "SERIES", "DATE1", "CLOSE_PRICE", "TTL_TRD_QNTY", "TURNOVER_LACS", "DELIV_QTY", "DELIV_PER"]
    for d in recent_weekdays():
        t = get_text(f"{ARCH}/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv", tries=1)
        if not t:
            continue
        rd = csv.reader(io.StringIO(t))
        head = [h.strip().upper() for h in next(rd)]
        idx = [head.index(k) for k in keep if k in head]
        iser = head.index("SERIES")
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow([head[i] for i in idx])
        n = 0
        for r in rd:
            if len(r) > max(idx) and r[iser].strip() == "EQ":
                w.writerow([r[i].strip() for i in idx])
                n += 1
        open("data/bhav_latest.csv", "w", encoding="utf-8").write(buf.getvalue())
        dates["bhav"] = f"{d:%d-%m-%Y}"
        return f"saved {n} rows for {dates['bhav']}"
    raise RuntimeError("no file in last 6 weekdays")


def deals(name):
    t = get_text(f"{ARCH}/content/equities/{name}.csv")
    if not t:
        raise RuntimeError("download failed")
    rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(t)) if r]
    if len(rows) < 2:
        return "no deals today"
    head = rows[0]
    body = [r for r in rows[1:] if len(r) == len(head)]
    path = f"data/{name}.csv"
    existing = []
    if os.path.exists(path):
        existing = list(csv.reader(open(path, newline="", encoding="utf-8")))[1:]
    seen = {tuple(r) for r in existing}
    added = [r for r in body if tuple(r) not in seen]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(head)
        w.writerows(existing + added)
    return f"{len(added)} new deals"


def sectors():
    t = get_text(f"{ARCH}/content/indices/ind_nifty500list.csv")
    if not t:
        raise RuntimeError("download failed")
    open("data/ind_nifty500list.csv", "w", encoding="utf-8").write(t)
    return "saved"


step("FII/DII cash", fii_dii)
step("Participant OI", participant_oi)
step("Bhavcopy", bhav)
step("Bulk deals", lambda: deals("bulk"))
step("Block deals", lambda: deals("block"))
step("Sector list", sectors)
json.dump(dates, open(DATES_FILE, "w"))
if len(failures) >= 6:
    sys.exit("All sources failed")
print("Failed sources:", failures or "none")
