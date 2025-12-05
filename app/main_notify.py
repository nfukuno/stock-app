from datetime import datetime
import pandas as pd
from utils import generate_stock_image   # utils.py の関数をインポート
from line_notify.notify import send_line_notification

# ダミーデータ（実際は株価チェック結果をここに入れる）
df = pd.DataFrame({
    "Symbol": ["AAPL", "MSFT", "AMZN"],
    "Latest": [190.2, 370.5, 145.8],
    "Change": ["+1.2%", "-0.5%", "+0.8%"]
})

# 実行時刻をファイル名に利用
timestamp = datetime.now().strftime("%Y-%m-%d-%H-%M")

# 画像生成
filename = generate_stock_image(df, timestamp)

# LINE通知用メッセージ
message = f"{timestamp.replace('-', ':')}時点の記録"

# 画像URL（テスト時は仮のURL。GitHub Pagesやサーバーにアップロードして利用）
#IMAGE_URL = "https://yourdomain.com/output/" + filename.split("/")[-1]
IMAGE_URL = f"https://nfukuno.github.io/stock-app/{filename}"
print(IMAGE_URL)


# LINE通知送信
send_line_notification(message, IMAGE_URL)