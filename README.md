# 📈 Stock App with LINE Notify

株価チェック結果を画像化し、LINEに通知するアプリケーションです。  
GitHub Actions を使って定時実行も可能です。

---

## 📦 主なファイルと役割

| ファイル/フォルダ       | 役割                                 |
|------------------------|--------------------------------------|
| `main.py`              | 株価チェック本体                     |
| `main_notify.py`       | 通知付きバージョン（テスト用）       |
| `utils.py`             | 共通関数（画像生成など）             |
| `data/`                | 入力データ                           |
| `output/`              | 生成画像の保存先                     |
| `line_notify/notify.py`| LINE通知処理                         |
| `.github/workflows/`   | GitHub Actions ワークフロー定義       |

---

## ⚙️ セットアップ手順

### 1. 依存関係のインストール

```bash
pip install -r requirements.txt