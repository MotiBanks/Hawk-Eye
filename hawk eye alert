import os
import requests
import time
import sqlite3


from dotenv import load_dotenv  

# Load environment variables
load_dotenv()

# Configurations
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY")
TELEGRAM_BOT_API_KEY = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Load Ethereum hacker addresses from file
with open("eth_hacker_addresses.txt", "r") as file:
    hacker_addresses = [line.strip() for line in file.readlines()]

# Connect to SQLite database (or create if not exists)
conn = sqlite3.connect("transactions.db")
cursor = conn.cursor()
cursor.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        address TEXT,
        tx_hash TEXT,
        to_address TEXT,
        value REAL,  -- ✅ Changed to REAL (float) for ETH amounts
        timestamp TEXT,
        detected_as TEXT
    )
""")
conn.commit()

# Load list of exchanges and mixers
with open("exchange_list.txt", "r") as file:
    known_exchanges = set(line.strip().lower() for line in file.readlines())

# Function to fetch transactions for a given address
def get_transactions(address):
    url = f"https://api.etherscan.io/api?module=account&action=txlist&address={address}&apikey={ETHERSCAN_API_KEY}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if data["status"] == "1":
            return data["result"]  # List of transactions
    return []

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

print("Monitoring hacker addresses...")
while True:
    for address in hacker_addresses:
        transactions = get_transactions(address)
        if transactions:
            latest_tx = transactions[-1]  # Get the most recent transaction
            tx_hash = latest_tx.get("hash")
            to_address = latest_tx.get("to", "Unknown")
            value_wei = latest_tx.get("value", "0")
            value_eth = int(value_wei) / 1e18  # ✅ Convert Wei to ETH
            timestamp = latest_tx.get("timeStamp", "Unknown")

            if address not in last_transactions or last_transactions[address] != tx_hash:
                last_transactions[address] = tx_hash  # Update last seen transaction
                category = classify_transaction(to_address)
                
                # Save transaction to database
                cursor.execute("""
                    INSERT INTO transactions (address, tx_hash, to_address, value, timestamp, detected_as)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (address, tx_hash, to_address, value_eth, timestamp, category))
                conn.commit()
                
                # Send alert if detected as suspicious
                alert_message = f"🚨 Funds moved!\nAddress: {address}\nTo: {to_address}\nCategory: {category}\nAmount: {value_eth:.6f} ETH\nTx Hash: {tx_hash}\nCheck: https://etherscan.io/tx/{tx_hash}"
                send_telegram_alert(alert_message)
                print(alert_message)
    
    print("Waiting 5 minutes before next check...")
    time.sleep(300)  # Wait 5 minutes before checking again