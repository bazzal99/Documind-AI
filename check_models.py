import requests
from dotenv import load_dotenv
import os

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"

for m in requests.get(url).json().get("models", []):
    print(m["name"], m.get("supportedGenerationMethods", []))