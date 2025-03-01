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
load_dotenv(override=True)
ETHERSCAN_API_KEY = ("GZM8MTWKSYRGVR3REDWP5J33FDQ9CA4JC7")
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

# Fetch transactions in batch to avoid rate limits
def fetch_transactions_batch(wallets):
    wallet_addresses = ",".join(wallets)
    url = f"https://api.etherscan.io/api?module=account&action=txlist&address={wallet_addresses}&sort=desc&apikey={ETHERSCAN_API_KEY}"
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        if data["status"] == "0":
            logging.warning(f"API returned error: {data['message']} - {data['result']}")
        return data.get("result", [])
    except requests.RequestException as e:
        logging.error(f"Error fetching transactions: {e}")
        return []

# Generate a well-formatted PDF report
def generate_pdf_report():
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Arial", "B", 16)
    pdf.cell(200, 10, "Ethereum Transaction Report", ln=True, align='C')
    pdf.ln(10)
    
    pdf.set_font("Arial", "B", 12)
    pdf.cell(30, 10, "Sender", border=1)
    pdf.cell(30, 10, "Receiver", border=1)
    pdf.cell(30, 10, "Amount (ETH)", border=1)
    pdf.cell(50, 10, "Status", border=1)
    pdf.cell(50, 10, "Transaction", border=1)
    pdf.ln()
    
    pdf.set_font("Arial", size=10)
    cursor.execute("SELECT address, tx_hash, to_address, value, timestamp, detected_as FROM transactions")
    
    for row in cursor.fetchall():
        sender, tx_hash, receiver, value, timestamp, detected_as = row
        pdf.cell(30, 10, sender[:6] + "...", border=1)  # Shorten long addresses
        pdf.cell(30, 10, receiver[:6] + "...", border=1)
        pdf.cell(30, 10, f"{value:.4f}", border=1)
        pdf.cell(50, 10, detected_as, border=1)
        pdf.cell(50, 10, tx_hash[:10] + "...", border=1)  # Shorten hash
        pdf.ln()
    
    pdf.output("transaction_report.pdf")
    logging.info("📄 PDF Report generated.")

# Monitor wallets and send batched Telegram alerts
def monitor_wallets():
    hacker_addresses = get_hacker_addresses()
    exchange_list = get_exchange_list()
    
    while True:
        current_time = int(time.time())
        transactions = fetch_transactions_batch(WALLETS)  # Batch request
        
        alerts = []
        
        for tx in transactions:
            tx_hash, sender, receiver = tx.get("hash"), tx.get("from"), tx.get("to")
            value = int(tx.get("value", 0)) / 10**18
            tx_time = int(tx.get("timeStamp", 0))

            if tx_hash and value >= 1.0 and (current_time - tx_time) <= 300:
                detected_as = []
                if sender in hacker_addresses:
                    detected_as.append("Hacker Address")
                if receiver in exchange_list:
                    detected_as.append("Exchange Address")
                
                alerts.append(f"🚨 **ALERT: Funds Moved!** 🚨\n"
                              f"🔹 **From:** {sender}\n"
                              f"🔹 **To:** {receiver}\n"
                              f"💰 **Amount:** {value:.6f} ETH\n"
                              f"⚠️ **Detected:** {', '.join(detected_as)}\n"
                              f"🔗 [View Transaction](https://etherscan.io/tx/{tx_hash})\n\n")

                cursor.execute("INSERT OR IGNORE INTO transactions VALUES (NULL, ?, ?, ?, ?, ?, ?)",
                               (sender, tx_hash, receiver, value, tx_time, ', '.join(detected_as)))
                conn.commit()
        
        if alerts:
            bot.send_message(TELEGRAM_CHAT_ID, "".join(alerts))
            logging.info(f"Sent {len(alerts)} alerts")
        
        time.sleep(60)

if __name__ == "__main__":
    monitor_wallets()
