import pandas as pd
import matplotlib.pyplot as plt

# ダミーデータ（株価チェック結果）
data = {
    "Symbol": ["AAPL", "MSFT", "AMZN"],
    "Latest": [190.2, 370.5, 145.8],
    "Change": ["+1.2%", "-0.5%", "+0.8%"],
    "Drawdown_3m": ["-5%", "-8%", "-3%"],
    "Drawdown_6m": ["-12%", "-15%", "-10%"]
}

df = pd.DataFrame(data)

# 表を画像化
fig, ax = plt.subplots(figsize=(6, 2))
ax.axis("off")
table = ax.table(cellText=df.values, colLabels=df.columns, loc="center")
table.auto_set_font_size(False)
table.set_fontsize(10)
table.scale(1.2, 1.2)

plt.savefig("result.png", bbox_inches="tight")