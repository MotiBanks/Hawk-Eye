import os
import requests
import time
import sqlite3
import json
from dotenv import load_dotenv  
from datetime import datetime, timezone  
from fpdf import FPDF  # For PDF report generation

# Load environment variables
load_dotenv()

# Configurations
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY")
TELEGRAM_BOT_API_KEY = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TRANSACTION_THRESHOLD = 1.0  # Minimum ETH amount to trigger an alert

# Function to fetch hacker addresses from JSON file
def get_hacker_addresses():
    try:
        with open("hacker_addresses.json", "r") as file:
            data = json.load(file)
        hacker_addresses = [addr for entry in data.values() if isinstance(entry, dict) for addr in entry.get("eth", [])]
        return hacker_addresses
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error reading hacker addresses: {e}")
        return []

# Function to fetch all transactions of an address
def get_transactions(address):
    url = f"https://api.etherscan.io/api?module=account&action=txlist&address={address}&sort=desc&apikey={ETHERSCAN_API_KEY}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        return data.get("result", []) if data.get("status") == "1" else []
    return []

# Function to classify transactions
def classify_transaction(to_address, known_list):
    if to_address.lower() in known_list:
        return "Exchange/Mixer"
    return "Normal"

# Load known exchanges and mixers from one file
with open("exchange_list.txt", "r") as file:
    known_list = set(line.strip().lower() for line in file.readlines())

# Connect to SQLite database
conn = sqlite3.connect("transactions.db")
cursor = conn.cursor()
cursor.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        address TEXT,
        tx_hash TEXT UNIQUE,  
        to_address TEXT,
        value REAL,
        timestamp TEXT,
        detected_as TEXT
    )
""")
conn.commit()

# Function to send Telegram alert
def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_API_KEY}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    requests.post(url, data=payload)

# Function to generate PDF report
def generate_pdf_report(transactions):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Arial", style='B', size=16)
    pdf.cell(200, 10, "Lazarus Hack Fund Movement Report", ln=True, align='C')
    pdf.ln(10)
    
    pdf.set_font("Arial", size=12)
    for tx in transactions:
        pdf.cell(0, 10, f"TX Hash: {tx['tx_hash']}", ln=True)
        pdf.cell(0, 10, f"From: {tx['address']}", ln=True)
        pdf.cell(0, 10, f"To: {tx['to_address']} ({tx['detected_as']})", ln=True)
        pdf.cell(0, 10, f"Amount: {tx['value']} ETH", ln=True)
        pdf.cell(0, 10, f"Timestamp: {tx['timestamp']}", ln=True)
        pdf.ln(5)
    
    pdf.output("transaction_report.pdf")

# Monitoring loop
print("Monitoring hacker addresses...")
while True:
    hacker_addresses = get_hacker_addresses()
    detected_transactions = []

    for address in hacker_addresses:
        transactions = get_transactions(address)
        for tx in transactions:
            tx_hash = tx.get("hash")
            to_address = tx.get("to", "Unknown")
            value_eth = int(tx.get("value", "0")) / 1e18  
            timestamp = int(tx.get("timeStamp", "0"))
            time_diff = int(datetime.now(timezone.utc).timestamp()) - timestamp

            if time_diff <= 600 and value_eth >= TRANSACTION_THRESHOLD:  # Updated to 10 minutes (600 seconds)
                detected_as = classify_transaction(to_address, known_list)
                cursor.execute("""
                    INSERT OR IGNORE INTO transactions (address, tx_hash, to_address, value, timestamp, detected_as)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (address, tx_hash, to_address, value_eth, timestamp, detected_as))
                conn.commit()
                
                detected_transactions.append({
                    "address": address,
                    "tx_hash": tx_hash,
                    "to_address": to_address,
                    "value": value_eth,
                    "timestamp": datetime.utcfromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S'),
                    "detected_as": detected_as
                })
                
                alert_message = f"🚨 Alert! Hacker funds moved!\nFrom: {address}\nTo: {to_address} ({detected_as})\nAmount: {value_eth} ETH\nTX Hash: {tx_hash}"
                send_telegram_alert(alert_message)
                print(alert_message)
    
    if detected_transactions:
        generate_pdf_report(detected_transactions)
        send_telegram_alert("📄 A detailed PDF report has been generated.")

    time.sleep(10)
