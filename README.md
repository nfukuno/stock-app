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

---

## 🎯 日足予想 & 類似度採点機能

毎日「今日の日足」を寄り前に予想 → 引け後に自動採点 → LINE で結果通知 → ダッシュボードで癖を振り返る機能です（日本株、`7203.T` 形式）。

| 画面 | 内容 |
|---|---|
| `/forecast` | 銘柄選択（コード直接入力可）・次の取引日の予想一覧・直近の採点結果 |
| `/forecast/{symbol}` | 日足チャート上の O/H/L/C ハンドルをドラッグして予想足を描く。シナリオ・自信度(1〜5)・一言メモ付き |
| `/forecast/dashboard` | 平均スコア・スキル（自分−横ばい予想）・偏り分析・自信度別/シナリオ別/銘柄別/曜日別・振り返り一覧 |

### 仕組み
- 予想は `forecasts/YYYY/MM/{対象日}_{銘柄}.json`（1銘柄1日1件）。ローカルの FastAPI から **GitHub Contents API** でリポジトリに保存します（`FORECAST_STORAGE=github`）。
- 対象日の **9:00 JST より前に保存した予想だけが、引け後に採点されます**。9:00 以降も保存・編集はできますが、`late`（場中予想）扱いとなり、採点・LINE 通知・成績集計の対象外です（場中に日足を考えてからエントリーする用途）。9:00 前に保存した予想を 9:00 以降に編集した場合も、以降は採点されません。採点済みの予想は編集できません（API は 409）。
- GitHub Actions `forecast_score`（平日 JST 16:30、再試行 20:00）が `python -m app.forecast.job` を実行して採点し、`forecasts/results.csv`・比較画像 `output/forecast/*.png` を生成して push、**push の後に** LINE へ通知します。
- 採点式（方向・終値・始値・値幅IoU・実体IoU・ヒゲ）と重みは `app/forecast/config.py`。式を変えるときは `SCORING_VERSION` を上げ、`--rescore` で全件再採点します。ベースラインは横ばい予想(flat)と前日足コピー(prev_copy)で、スキル = 総合 − flat です。
- ジョブ CLI: `python -m app.forecast.job [--date YYYY-MM-DD] [--dry-run] [--no-notify] [--rescore] [--notify-only]`

> ⚠️ **このリポジトリが public の場合、予想・メモ・成績はすべて公開されます。**

### ローカルでの起動
```bash
cp .env.example .env        # 下記 PAT を設定
export $(grep -v '^#' .env | xargs)   # もしくは docker compose up（compose が .env を読みます）
uvicorn app.main:app --reload         # http://localhost:8000/forecast
pytest                                # テスト
```
GitHub に書き込まず試すだけなら `FORECAST_STORAGE=local`（`forecasts/` に保存。コミットしないでください）。

### 初回セットアップ（ユーザーの手作業）
1. **fine-grained PAT を作成**: GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token。Repository access は `nfukuno/stock-app` のみ、Permissions は **Contents: Read and write**。発行された値をローカルの `.env` の `FORECAST_GITHUB_TOKEN` に設定し、`FORECAST_STORAGE=github` にします。
2. Actions の secrets `LINE_ACCESS_TOKEN` / `LINE_USER_ID` は既存のものをそのまま使います（追加作業なし）。
3. **この機能のブランチを `main` にマージ**します（スケジュール実行はデフォルトブランチにマージされるまで動きません）。
4. 動作確認: Actions タブ → `Forecast Score` → *Run workflow*（`workflow_dispatch`）で手動実行し、採点対象があれば結果の push と LINE 通知を確認します。
