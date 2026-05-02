import requests
import os
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

url = f"https://api.telegram.org/bot{TOKEN}/sendMessage+"

payload = {"chat_id": CHAT_ID, "text": "Teste de conexão direta!"}
response = requests.post(url, data=payload)
print(response.json()) # Veja o erro que o Telegram retorna aqui
