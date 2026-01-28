import requests
from bs4 import BeautifulSoup
import re
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import json

# ------------------ GOOGLE SHEETS SETUP ------------------
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

service_account_info = json.loads(
    os.getenv("GOOGLE_CREDENTIALS_JSON")
)

creds = Credentials.from_service_account_info(
    service_account_info,
    scopes=SCOPES
)

client = gspread.authorize(creds)
sheet = client.open("IPO Tracker").sheet1

existing_rows = sheet.get_all_values()

existing_ipo_map = {
    row[0]: idx + 2
    for idx, row in enumerate(existing_rows[1:])
    if row and row[0]
}

# ------------------ EMAIL CONFIG ------------------
SENDER_EMAIL = os.getenv("prateek1559@gmail.com")
APP_PASSWORD = os.getenv("uyroseasfmeygyma")
RECEIVER_EMAIL = os.getenv("prateek1559@gmail.com")

gmp_alerts = []   # collect daily alerts for OPEN IPOs

# ------------------ SCRAPE IPO CALENDAR ------------------
calendar_url = "https://www.chittorgarh.com/ipo/ipo_calendar.asp"
headers = {"User-Agent": "Mozilla/5.0"}

calendar_resp = requests.get(calendar_url, headers=headers, timeout=15)
calendar_soup = BeautifulSoup(calendar_resp.text, "html.parser")

table = calendar_soup.find("table")
cells = table.find_all("td")

events = []

for cell in cells:
    for li in cell.find_all("li"):
        text = li.get_text(strip=True)
        if "IPO Opens on" in text or "IPO Closes on" in text:
            events.append(text)

ipo_data = {}

for event in events:
    match = re.match(r"(.*) IPO (Opens|Closes) on (.*)", event)
    if not match:
        continue

    name, action, date = match.groups()
    name = name.strip()

    if name not in ipo_data:
        ipo_data[name] = {}

    if action == "Opens":
        ipo_data[name]["open_date"] = date
    else:
        ipo_data[name]["close_date"] = date

# ------------------ SCRAPE GMP DATA ------------------
gmp_map = {}

# Chittorgarh
gmp_url = "https://www.chittorgarh.com/ipo/ipo_gmp.asp"
gmp_resp = requests.get(gmp_url, headers=headers, timeout=15)
gmp_soup = BeautifulSoup(gmp_resp.text, "html.parser")

gmp_table = gmp_soup.find("table")
if gmp_table:
    for row in gmp_table.find_all("tr")[1:]:
        cols = row.find_all("td")
        if len(cols) >= 2:
            gmp_map[cols[0].get_text(strip=True)] = cols[1].get_text(strip=True)

# InvestorGain (fallback)
ig_url = "https://www.investorgain.com/ipo-gmp/"
ig_resp = requests.get(ig_url, headers=headers, timeout=15)
ig_soup = BeautifulSoup(ig_resp.text, "html.parser")

ig_table = ig_soup.find("table")
if ig_table:
    for row in ig_table.find_all("tr")[1:]:
        cols = row.find_all("td")
        if len(cols) >= 3:
            name = cols[0].get_text(strip=True)
            if name not in gmp_map:
                gmp_map[name] = cols[2].get_text(strip=True)

# ------------------ UPDATE SHEET + DAILY GMP ALERT LOGIC ------------------
today = datetime.today().date()

for ipo, data in ipo_data.items():
    open_date_str = data.get("open_date", "")
    close_date_str = data.get("close_date", "")

    status = "UPCOMING"

    if open_date_str and close_date_str:
        open_date = datetime.strptime(open_date_str, "%b %d, %Y").date()
        close_date = datetime.strptime(close_date_str, "%b %d, %Y").date()

        if today < open_date:
            status = "UPCOMING"
        elif open_date <= today <= close_date:
            status = "OPEN"
        else:
            status = "CLOSED"

    gmp = gmp_map.get(ipo, "").strip()

    # ✅ DAILY ALERT ONLY WHILE IPO IS OPEN
    if status == "OPEN" and gmp:
        gmp_alerts.append(
            f"{ipo} – GMP ₹{gmp} (Closes on {close_date_str})"
        )

    row = [
        ipo,
        open_date_str,
        close_date_str,
        gmp,
        status,
        datetime.now().strftime("%Y-%m-%d %H:%M")
    ]

    if ipo in existing_ipo_map:
        sheet.update(
            f"A{existing_ipo_map[ipo]}:F{existing_ipo_map[ipo]}",
            [row]
        )
    else:
        sheet.append_row(row)

# ------------------ SEND EMAIL ONCE PER RUN ------------------
if gmp_alerts:
    msg = MIMEMultipart()
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECEIVER_EMAIL
    msg["Subject"] = "📈 IPO GMP Alert (Open IPOs)"

    body = "GMP available for the following OPEN IPOs:\n\n" + "\n".join(gmp_alerts)
    msg.attach(MIMEText(body, "plain"))

    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.starttls()
    server.login(SENDER_EMAIL, APP_PASSWORD)
    server.send_message(msg)
    server.quit()

    print("Daily GMP alert email sent")
else:
    print("No OPEN IPO with GMP today")
