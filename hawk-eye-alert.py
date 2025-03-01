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
API_CALL_INTERVAL = 300  # ⏳ Increased delay between API calls (5 minutes)

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

# Function to fetch the latest transaction of an address
def get_latest_transaction(address):
    url = f"https://api.etherscan.io/api?module=account&action=txlist&address={address}&sort=desc&page=1&offset=1&apikey={ETHERSCAN_API_KEY}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if data.get("status") == "1" and data.get("result"):
            return data["result"][0]  # Only fetch the most recent transaction
    return None

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

# Cache to track last checked transaction per address
last_checked_tx = {}

# Function to send Telegram alert
def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_API_KEY}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    requests.post(url, data=payload)

# Monitoring loop
print("Monitoring hacker addresses...")
while True:
    hacker_addresses = get_hacker_addresses()
    detected_transactions = []

    for address in hacker_addresses:
        latest_tx = get_latest_transaction(address)
        if latest_tx:
            tx_hash = latest_tx.get("hash")
            to_address = latest_tx.get("to", "Unknown")
            value_eth = int(latest_tx.get("value", "0")) / 1e18  
            timestamp = int(latest_tx.get("timeStamp", "0"))
            time_diff = int(datetime.now(timezone.utc).timestamp()) - timestamp

            # Skip already checked transactions
            if last_checked_tx.get(address) == tx_hash:
                continue  # 🚀 Avoid duplicate API calls

            if time_diff <= 600 and value_eth >= TRANSACTION_THRESHOLD:  # Updated to 10 minutes (600 seconds)
                detected_as = classify_transaction(to_address, known_list)
                cursor.execute("""
                    INSERT OR IGNORE INTO transactions (address, tx_hash, to_address, value, timestamp, detected_as)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (address, tx_hash, to_address, value_eth, timestamp, detected_as))
                conn.commit()
                
                last_checked_tx[address] = tx_hash  # Store last checked transaction
                
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
        print("📄 Generating report...")
    
    print(f"⏳ Waiting {API_CALL_INTERVAL} seconds before the next check...")
    time.sleep(API_CALL_INTERVAL)  # ⏳ Increased wait time to 5 minutes (300 seconds)
