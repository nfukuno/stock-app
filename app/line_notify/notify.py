import os
import requests
from dotenv import load_dotenv

# LINE通知関数
def send_line_notification(message: str, image_url: str = None):
    # LINE用の.envを読み込む
    load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
    ACCESS_TOKEN = os.getenv("LINE_ACCESS_TOKEN")
    USER_ID = os.getenv("LINE_USER_ID")
    
    headers = {
        "Authorization": f"Bearer {ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    messages = [{"type": "text", "text": message}]

    if image_url:
        messages.append({
            "type": "image",
            "originalContentUrl": image_url,
            "previewImageUrl": image_url
        })

    data = {"to": USER_ID, "messages": messages}

    response = requests.post(
        "https://api.line.me/v2/bot/message/push",
        headers=headers,
        json=data
    )

    print(response.status_code, response.text)