import os
import requests
import time
import sqlite3
import json
from dotenv import load_dotenv  
from datetime import datetime, timezone  

# Load environment variables
load_dotenv()

# Configurations
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY")
TELEGRAM_BOT_API_KEY = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TRANSACTION_THRESHOLD = 1.0  # ✅ Minimum ETH amount to trigger an alert

# Function to fetch hacker addresses from the JSON file
def get_hacker_addresses():
    try:
        with open("hacker_addresses.json", "r") as file:
            data = json.load(file)

        # Extract addresses correctly (assuming structure like { "0221": { "eth": [..addresses..] } })
        hacker_addresses = []
        for key, value in data.items():
            if isinstance(value, dict) and "eth" in value:
                hacker_addresses.extend(value["eth"])  # Add Ethereum addresses to the list

        return hacker_addresses

    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"⚠️ Error reading hacker addresses: {e}")
        return []  # Return empty list to prevent script failure

# Connect to SQLite database (or create if not exists)
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

# Load list of exchanges and mixers
with open("exchange_list.txt", "r") as file:
    known_exchanges = set(line.strip().lower() for line in file.readlines())

# Function to fetch only the latest transaction (for alerts)
def get_latest_transaction(address):
    url = f"https://api.etherscan.io/api?module=account&action=txlist&address={address}&sort=desc&page=1&offset=1&apikey={ETHERSCAN_API_KEY}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if data["status"] == "1" and data["result"]:
            return data["result"][0]  
    return None

# Function to check if an address is an exchange/mixer
def classify_transaction(to_address):
    if to_address and to_address.lower() in known_exchanges:
        return "Exchange/Mixer"
    return "Normal"

# Function to send Telegram alerts
def send_telegram_alert(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_API_KEY}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    requests.post(url, data=payload)

# Dictionary to store last checked transactions for each address
last_transactions = {}

# Send test alert to verify Telegram is working
send_telegram_alert("🚨 Test Alert: Your monitoring system is working!")
print("✅ Test alert sent to Telegram!")

print("📡 Monitoring hacker addresses...")
while True:
    # Load updated hacker addresses before each monitoring cycle
    hacker_addresses = get_hacker_addresses()

    for address in hacker_addresses:
        latest_tx = get_latest_transaction(address)

        if latest_tx:
            tx_hash = latest_tx.get("hash")
            to_address = latest_tx.get("to", "Unknown")
            value_wei = latest_tx.get("value", "0")
            value_eth = int(value_wei) / 1e18  
            timestamp = int(latest_tx.get("timeStamp", "0"))  # Convert to integer

            # ✅ Check if the transaction happened in the last 60 seconds and meets threshold
            current_time = int(datetime.now(timezone.utc).timestamp())
            time_diff = current_time - timestamp  # Difference in seconds

            if time_diff <= 60 and value_eth >= TRANSACTION_THRESHOLD:  # ✅ Ensure it's recent & meets threshold
                if address not in last_transactions or last_transactions[address] != tx_hash:
                    last_transactions[address] = tx_hash  
                    category = classify_transaction(to_address)

                    # Save transaction in database
                    cursor.execute("""
                        INSERT OR IGNORE INTO transactions (address, tx_hash, to_address, value, timestamp, detected_as)
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, (address, tx_hash, to_address, value_eth, timestamp, category))
                    conn.commit()

                    # Send alert
                    alert_message = f"🚨 Live Transaction Alert!\nAddress: {address}\nTo: {to_address}\nCategory: {category}\nAmount: {value_eth:.6f} ETH\nTx Hash: {tx_hash}\n🔍 Check: https://etherscan.io/tx/{tx_hash}"
                    send_telegram_alert(alert_message)
                    print(alert_message)
            else:
                print(f"⏳ Ignoring transaction for {address}: {tx_hash} (Occurred {time_diff} seconds ago, Amount: {value_eth:.6f} ETH)")

    print("⏳ Waiting 10 seconds before next check...")
    time.sleep(10)  # ✅ Reduced wait time to 10 seconds
