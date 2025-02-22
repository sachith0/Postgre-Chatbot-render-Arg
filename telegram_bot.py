from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import requests
import sqlite3
import pytesseract
from PIL import Image
import io

TOKEN = "7922001101:AAGUqcKnpPV6_0bgFJ2XB7PEBQD5NKsLPGI"
GEMINI_API_KEY = "AIzaSyA8btcq5oLVtm0Pdg0kuuIgCAAkoTebmIs"

# ✅ Extract Text from Image (OCR)
def extract_text_from_image(image_bytes):
    image = Image.open(io.BytesIO(image_bytes))
    image = image.convert("L")  # Grayscale
    return pytesseract.image_to_string(image, lang="hin+eng+kan+tam+ben").strip()

# ✅ Fetch Transactions
def fetch_transaction_details():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM transactions;")
    transaction_count = cursor.fetchone()[0]
    conn.close()
    return f"Total Transactions: {transaction_count}"

# ✅ Handle Images
def handle_image(update: Update, context: CallbackContext):
    user = update.message.from_user
    file = context.bot.get_file(update.message.photo[-1].file_id)
    image_bytes = file.download_as_bytearray()
    
    extracted_text = extract_text_from_image(image_bytes)
    
    query_needs_db = any(word in extracted_text.lower() for word in ["transaction", "amount", "balance", "statement"])
    db_response = fetch_transaction_details() if query_needs_db else "Not a transaction-related query."

    update.message.reply_text(f"Extracted Text: {extracted_text}\n\nDatabase Response: {db_response}")

# ✅ Handle Text Queries
def handle_text(update: Update, context: CallbackContext):
    user_message = update.message.text

    payload = {
        "contents": [{"parts": [{"text": user_message}]}]
    }

    headers = {"Content-Type": "application/json"}
    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}",
        headers=headers,
        json=payload
    )

    if response.status_code == 200:
        llm_response = response.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
        update.message.reply_text(llm_response.strip())
    else:
        update.message.reply_text("❌ Gemini API error. Please try again.")

# ✅ Start Bot
def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(MessageHandler(Filters.photo, handle_image))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
