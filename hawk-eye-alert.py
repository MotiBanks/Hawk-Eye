import os
import json
import requests
import time
import telebot
import logging
import sqlite3
from dotenv import load_dotenv
from fpdf import FPDF  # PDF generation

# Load environment variables
load_dotenv()
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not all([ETHERSCAN_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID]):
    raise ValueError("Missing required environment variables. Ensure .env is properly configured.")

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Load hacker addresses from JSON
def get_hacker_addresses():
    try:
        with open("hacker_addresses.json", "r") as file:
            data = json.load(file)
        return [addr for value in data.values() if isinstance(value, dict) for addr in value.get("eth", [])]
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logging.error(f"Error loading hacker addresses: {e}")
        return []

# Load exchange addresses from file
def get_exchange_list():
    try:
        with open("exchange_list.txt", "r") as file:
            return set(line.strip().lower() for line in file.readlines())
    except FileNotFoundError:
        logging.error("Exchange list file not found.")
        return set()

# Load wallets dynamically
WALLET_FILE = "tracked_wallets.txt"
WALLETS = set(open(WALLET_FILE).read().splitlines()) if os.path.exists(WALLET_FILE) else set()

def save_wallets():
    with open(WALLET_FILE, "w") as f:
        for wallet in WALLETS:
            f.write(wallet + "\n")

# Connect to SQLite for transaction tracking
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

def fetch_transactions(wallet):
    url = f"https://api.etherscan.io/api?module=account&action=txlist&address={wallet}&sort=desc&apikey={ETHERSCAN_API_KEY}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json().get("result", [])
    except requests.RequestException as e:
        logging.error(f"Error fetching transactions: {e}")
        return []

def generate_pdf_report():
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Arial", size=12)
    pdf.cell(200, 10, "Transaction Report", ln=True, align='C')
    pdf.ln(10)
    
    cursor.execute("SELECT address, tx_hash, to_address, value, timestamp, detected_as FROM transactions")
    for row in cursor.fetchall():
        pdf.multi_cell(0, 10, f"{row}")
        pdf.ln()
    
    pdf.output("transaction_report.pdf")
    logging.info("PDF Report generated.")

def monitor_wallets():
    hacker_addresses = get_hacker_addresses()
    exchange_list = get_exchange_list()
    while True:
        current_time = int(time.time())
        for wallet in list(WALLETS):
            transactions = fetch_transactions(wallet)
            for tx in transactions[:5]:
                tx_hash, sender, receiver = tx.get("hash"), tx.get("from"), tx.get("to")
                value = int(tx.get("value", 0)) / 10**18
                tx_time = int(tx.get("timeStamp", 0))
                
                if tx_hash and value >= 1.0 and (current_time - tx_time) <= 300:
                    detected_as = []
                    if sender in hacker_addresses:
                        detected_as.append("Hacker Address")
                    if receiver in exchange_list:
                        detected_as.append("Exchange Address")
                    
                    alert_msg = (
                        f"🚨 ALERT: Funds Moved! 🚨\nFrom: {sender}\nTo: {receiver}\nAmount: {value:.6f} ETH\n"
                        f"Detected: {', '.join(detected_as)}\nTx: https://etherscan.io/tx/{tx_hash}"
                    )
                    bot.send_message(TELEGRAM_CHAT_ID, alert_msg)
                    cursor.execute("INSERT OR IGNORE INTO transactions VALUES (NULL, ?, ?, ?, ?, ?, ?)",
                                   (wallet, tx_hash, receiver, value, tx_time, ', '.join(detected_as)))
                    conn.commit()
                    logging.info(f"Alert sent for {tx_hash}")
        time.sleep(60)

if __name__ == "__main__":
    monitor_wallets()
