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
- 対象日の **9:00 JST より前に保存した予想が、引け後に採点されます**。9:00 以降も編集はできますが、採点は 9:00 前の内容のままです（`frozen` として固定され、場中の編集は通常欄と `intraday` に別保持）。9:00 以降に初めて保存した予想は `late`（場中予想）で、採点・LINE 通知・成績集計の対象外です（場中に日足を考えてからエントリーする用途）。採点済みの予想は編集できません（API は 409）。
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

---

## 💹 仮想信用口座（デイトレ・スイングの練習用）

お金を減らさずに売買の経験を積むためのデモ口座です。日本株・信用取引が前提です。板は取らず、**銘柄・株数・価格・買/売を自分で入力**して約定として記録します。

| 画面 | 内容 |
|---|---|
| `/trade` | 口座サマリー（実質保証金・新規建余力・維持率・評価損益・本日の確定損益）、新規注文、建玉一覧と返済（同じ銘柄・売買・区分が 2 本以上なら合計行に平均建値・まとめて返済）、本日の約定、口座リセット、ロードマップ（各フェーズと次に進む条件の達成状況） |
| `/trade/history` | 成績（勝率・期待値・平均R・PF・最大DD・最大連敗・損切りライン超え）、損益曲線、理由タグ別/時間帯別/曜日別/感情別/売買別/区分別/銘柄別、約定履歴 |

### 取引条件（`app/trade/config.py`）
- 初期保証金 **500万円**、委託保証金率 30%（約3.3倍）、最低保証金 30万円、**維持率 20% 未満で追証**（新規建不可）
- 実質保証金 = 現金保証金 + 評価損（評価益は算入しない）− 未払いの金利・貸株料
- **いちにち信用**: 手数料・金利・貸株料なし。建てた日の大引け（15:30）までに返済しないと、その日の終値で強制返済
- **制度信用（6ヶ月）**: 楽天証券に合わせて 買方金利 2.85% / 売方金利 0% / 貸株料 1.10%（年率、受渡日〜受渡日の両端入れ・365日・円未満切り捨て）、手数料 0。期日（6ヶ月目の応当日。休業日なら前営業日）の大引けで強制返済
- 約定時刻は立会時間内（9:00〜11:30 / 12:30〜15:30）のみ。省略すると現在時刻。100株単位
- 新規注文では損切りライン・利確目標・エントリー理由タグ・感情・メモを記録（損切りラインがあると R 倍数を計算）
- 既存の建玉に追加したとき、平均建値より不利な価格（買いなら安く・売りなら高く）ならナンピン、有利なら増し玉として記録し、分析画面で成績を分けて集計
- まとめて返済は古い建玉から順に返済（建玉ごとに約定が記録されます）
- ロードマップと進む条件は `ROADMAP`（`app/trade/config.py`）で変更できます

### 保存先
日足予想と同じ `FORECAST_STORAGE` に従い、`github` なら `trades/` 以下に Contents API で保存します（`local` なら `TRADE_DATA_DIR`、既定は `<repo>/trades`）。
- `trades/current.json` … 使用中の口座 ID
- `trades/accounts/{口座ID}.json` … 建玉・約定履歴。リセットしても過去の口座は残ります

> ⚠️ **このリポジトリが public の場合、売買履歴もすべて公開されます。**
