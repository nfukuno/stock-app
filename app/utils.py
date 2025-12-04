import os
import matplotlib.pyplot as plt
import pandas as pd

def generate_stock_image(df: pd.DataFrame, timestamp: str, save_dir: str = "output") -> str:
    """
    株価データを画像化して保存し、保存先ファイル名を返す関数

    Parameters
    ----------
    df : pd.DataFrame
        株価データ（Symbol, Latest, Change などの列を持つ）
    timestamp : str
        保存ファイル名に使う時刻文字列 (例: "2025-12-04-16-28")
    save_dir : str
        保存先ディレクトリ（デフォルトは "output"）

    Returns
    -------
    str
        保存したファイルのパス
    """
    os.makedirs(save_dir, exist_ok=True)
    filename = f"{save_dir}/{timestamp}.png"

    fig, ax = plt.subplots(figsize=(6, 2))
    ax.axis("off")
    table = ax.table(cellText=df.values, colLabels=df.columns, loc="center")
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1.2, 1.2)

    plt.savefig(filename, bbox_inches="tight")
    plt.close(fig)

    return filename