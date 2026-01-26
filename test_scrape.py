import requests
from bs4 import BeautifulSoup
import re
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ------------------ GOOGLE SHEETS SETUP ------------------
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

import os
import json
from google.oauth2.service_account import Credentials

service_account_info = json.loads(
    os.environ["GOOGLE_CREDENTIALS_JSON"]
)

creds = Credentials.from_service_account_info(
    service_account_info,
    scopes=SCOPES
)

client = gspread.authorize(creds)
sheet = client.open("IPO Tracker").sheet1

# Read existing rows
existing_rows = sheet.get_all_values()

# Map IPO Name -> Row Number (skip header)
existing_ipo_map = {
    row[0]: idx + 2
    for idx, row in enumerate(existing_rows[1:])
    if row and row[0]
}

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
gmp_url = "https://www.chittorgarh.com/ipo/ipo_gmp.asp"
gmp_resp = requests.get(gmp_url, headers=headers, timeout=15)
gmp_soup = BeautifulSoup(gmp_resp.text, "html.parser")

gmp_map = {}

gmp_table = gmp_soup.find("table")
if gmp_table:
    rows = gmp_table.find_all("tr")[1:]
    for row in rows:
        cols = row.find_all("td")
        if len(cols) >= 2:
            ipo_name = cols[0].get_text(strip=True)
            gmp_value = cols[1].get_text(strip=True)
            gmp_map[ipo_name] = gmp_value
# ------------------ SCRAPE GMP DATA (InvestorGain) ------------------
ig_url = "https://www.investorgain.com/ipo-gmp/"
ig_resp = requests.get(ig_url, headers=headers, timeout=15)
ig_soup = BeautifulSoup(ig_resp.text, "html.parser")

ig_table = ig_soup.find("table")

if ig_table:
    rows = ig_table.find_all("tr")[1:]
    for row in rows:
        cols = row.find_all("td")
        if len(cols) >= 3:
            ipo_name = cols[0].get_text(strip=True)
            gmp_value = cols[2].get_text(strip=True)

            # Only add if not already present from Chittorgarh
            if ipo_name and ipo_name not in gmp_map:
                gmp_map[ipo_name] = gmp_value

print("GMP Map:", gmp_map)

# ------------------ STATUS + SHEET UPDATE ------------------
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

    gmp = gmp_map.get(ipo, "")

    row = [
        ipo,
        open_date_str,
        close_date_str,
        gmp,
        status,
        datetime.now().strftime("%Y-%m-%d %H:%M")
    ]

    if ipo in existing_ipo_map:
        row_num = existing_ipo_map[ipo]
        sheet.update(f"A{row_num}:F{row_num}", [row])
    else:
        sheet.append_row(row)

print(f"{len(ipo_data)} IPOs processed with GMP")
# ------------------ EMAIL TEST ------------------
SENDER_EMAIL = "prateek1559@gmail.com"
APP_PASSWORD = "uyroseasfmeygyma"
RECEIVER_EMAIL = "prateek1559@gmail.com"

msg = MIMEMultipart()
msg["From"] = SENDER_EMAIL
msg["To"] = RECEIVER_EMAIL
msg["Subject"] = "IPO GMP Alert Test"

body = "This is a test email from your IPO GMP tracking script."
msg.attach(MIMEText(body, "plain"))

server = smtplib.SMTP("smtp.gmail.com", 587)
server.starttls()
server.login(SENDER_EMAIL, APP_PASSWORD)
server.send_message(msg)
server.quit()

print("Test email sent successfully")

