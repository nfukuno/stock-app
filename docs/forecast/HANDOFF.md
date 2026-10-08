# 日足予想 & 類似度採点機能 — 開発引き継ぎ書

最終更新: 2026-10-08
対象リポジトリ: `nfukuno/stock-app`

---

## 0. このドキュメントの位置づけ

ユーザー（日本株のデイトレーダー）が **毎日「今日の日足」を寄り前に予想 → 引け後に自動採点 → LINE で結果通知 → ダッシュボードで癖を振り返る** ための機能を、既存の stock-app に追加する。
本書は要件・設計・採点式・作業手順・完了条件をまとめたもの。設計判断はここで確定済みなので、**不明点がない限り本書に従って実装すること**。本書と既存コードが矛盾する場合は既存コードの実態を優先し、判断をコミットメッセージか README に残す。

### ユーザーと確定済みの決定事項

| 項目 | 決定 |
|---|---|
| 対象市場 | **日本株**（東証。yfinance のシンボルは `7203.T` 形式） |
| 予想入力 | **案A：チャート上でローソク足をドラッグして描く**（数値入力欄も同期表示） |
| 付帯入力 | **シナリオ選択・自信度(1〜5)・一言メモ** |
| 保存先 | **GitHub リポジトリ**（ローカルの FastAPI から GitHub Contents API で書き込み） |
| 採点 | **GitHub Actions** が引け後に自動採点 |
| 通知 | **LINE**（既存の Messaging API push の仕組みを再利用、画像付き） |
| 開発範囲 | 予想入力 / 類似度スコア / LINE通知 / **ベースライン比較 / 成績ダッシュボード / シナリオ選択** すべて |
| 後回し（今回やらない） | 5分足による日中パス評価（DTW）、米国株対応 |

---

## 1. 既存コードの現状（調査済み）

```
app/
  main.py                 FastAPI。GET / で銘柄ドローダウン一覧（yfinance）。uvicorn app.main:app でリポジトリ直下から起動する前提
  main_notify.py          GitHub Actions から `python app/main_notify.py` で実行。画像生成→LINE通知（現在はダミーデータ）
  utils.py                generate_stock_image(): matplotlib で表を PNG 化し output/ に保存
  line_notify/notify.py   send_line_notification(message, image_url) — LINE Messaging API の push。
                          env: LINE_ACCESS_TOKEN, LINE_USER_ID（line_notify/.env も読む）
  services/yahoo_finance.py  get_drawdown_bulk() 等
  templates/index.html, loading.html   Jinja2
  data/stocks.csv         米国株中心の監視リスト（ドローダウン用。今回の機能では使わない）
.github/workflows/notify.yml  毎日 UTC 8:05 に main_notify.py 実行 → output/ を main に commit & push
output/*.png              GitHub Pages で公開され、LINE 画像は https://nfukuno.github.io/stock-app/output/<file>.png で参照
Dockerfile / docker-compose.yml   python:3.10-slim、uvicorn app.main:app
requirements.txt          fastapi, uvicorn, jinja2, yfinance, matplotlib, requests, pandas, numpy
```

注意点:
- `app/main.py` はテンプレートを `app/templates`（cwd=リポジトリ直下前提）、CSV を `data/stocks.csv`（Docker の cwd 前提）と相対パスが不統一。**既存部分は触らない**。新規コードは `Path(__file__)` 基準で絶対パス化すること。
- `app/__init__.py` は無い（namespace package として `app.services` を import している）。新規モジュールも `app.forecast.xxx` で import できる。
- `python-dotenv` は requirements.txt に無いが notify.py が使っている（間接依存で入っている）。今回 requirements.txt に明記してよい。
- 既存の `notify.yml` も main に push する。新ワークフローと push が競合しうるので、push 前に `git pull --rebase` + リトライを入れる。
- **スケジュール実行のワークフローはデフォルトブランチ（main）にマージされるまで動かない。**

---

## 2. 全体アーキテクチャ

```
[ユーザーPC: FastAPI (uvicorn / docker)]
  /forecast            銘柄選択・今日の予想一覧
  /forecast/{symbol}   日足チャート + ドラッグで予想足を描く → 保存
        │  GitHub Contents API (PUT)  ※ fine-grained PAT
        ▼
[GitHub: main ブランチ]
  forecasts/2026/10/2026-10-09_7203.T.json   ← 予想1件=1ファイル
  forecasts/results.csv                      ← 採点済み全件（Actions が再生成）
  output/forecast/2026-10-09_7203.T.png      ← 予想 vs 実際 の画像
        ▲
        │ checkout / commit / push
[GitHub Actions: forecast_score.yml]  平日 JST 16:30（再試行 20:00）
  pending の予想を採点 → JSON 更新 → results.csv 再生成 → 画像生成 → push → LINE 通知

[ユーザーPC: FastAPI]
  /forecast/dashboard  results.csv を GitHub から取得して成績を可視化
```

### ストレージ抽象化
`ForecastStore` インターフェースを作り、実装を2つ用意する。
- `GitHubStore`: Contents API で読み書き（本番。ローカルアプリから使用）
- `LocalStore`: リポジトリ作業ツリーのファイルを直接読み書き（Actions のジョブ、テスト、開発時）

環境変数 `FORECAST_STORAGE=github|local`（デフォルト `local`）で切替。

| 環境変数 | 用途 |
|---|---|
| `FORECAST_STORAGE` | `github` or `local` |
| `FORECAST_GITHUB_TOKEN` | fine-grained PAT（対象: nfukuno/stock-app のみ、権限: Contents Read and write） |
| `FORECAST_GITHUB_REPO` | 既定 `nfukuno/stock-app` |
| `FORECAST_GITHUB_BRANCH` | 既定 `main` |
| `FORECAST_DATA_DIR` | LocalStore のルート。既定 `<repo>/forecasts` |
| `LINE_ACCESS_TOKEN`, `LINE_USER_ID` | 既存（Actions の secrets に設定済み） |

`.env.example` を追加し、`docker-compose.yml` に上記 env を渡す設定を追記する。トークンは絶対にコミットしない（`.gitignore` 済みの `.env` を使う）。

⚠️ **リポジトリが public の場合、予想とメモも公開される。** README に明記すること（ユーザーは承知の上でこの方式を選択済み）。

---

## 3. データ仕様

### 3.1 予想ファイル `forecasts/YYYY/MM/{target_date}_{symbol}.json`

```json
{
  "id": "2026-10-09_7203.T",
  "schema_version": 1,
  "symbol": "7203.T",
  "name": "トヨタ自動車",
  "target_date": "2026-10-09",
  "created_at": "2026-10-09T08:12:03+09:00",
  "updated_at": "2026-10-09T08:40:11+09:00",
  "late": false,
  "snapshot": { "prev_date": "2026-10-08", "prev_close": 2650.0, "atr14": 45.2 },
  "pred": { "open": 2665.0, "high": 2700.0, "low": 2655.0, "close": 2690.0 },
  "scenario": "gap_up_trend",
  "confidence": 4,
  "memo": "米株高と円安。寄り後の押し目を拾われる想定",
  "status": "pending",

  "actual": null,
  "actual_scenario": null,
  "score": null,
  "baselines": null,
  "scored_at": null,
  "scoring_version": null
}
```

採点後に埋まるフィールド:
```json
  "status": "scored",
  "actual": { "open": 2660.0, "high": 2712.0, "low": 2648.0, "close": 2701.0,
              "prev_close": 2650.0, "atr14": 45.2 },
  "actual_scenario": "gap_up_trend",
  "score": { "total": 78.4, "direction": 100, "close": 75.7, "open": 89.0,
             "range_iou": 68.8, "body_iou": 60.1, "shadow": 81.3, "scenario_hit": true },
  "baselines": { "flat": { "total": 55.2 }, "prev_copy": { "total": 48.9 } },
  "skill": 23.2,
  "scored_at": "2026-10-09T16:31:22+09:00",
  "scoring_version": 1
```
`status` は `pending` / `scored` / `void`（休場・データ欠損で採点不能。`void_reason` を付与）。

### 3.2 ルール
- **1銘柄1日1予想**（同じ id は上書き）。
- **ロック**: 対象日の **09:00 JST 以降は既存の予想を編集不可**（API は 409）。09:00 以降に**新規**保存は可能だが `late: true` を付け、ダッシュボードの集計からは既定で除外（トグルで含められる）。
- **入力検証**: `high >= max(open, close)`、`low <= min(open, close)`、全て正の数。`confidence` は 1〜5 の整数。`memo` は 500 文字以内。`scenario` は 3.3 の enum のいずれか（必須）。
- 価格は呼値に丸めなくてよい（小数1桁まで保持）。
- `target_date` = 予想時点での「次の取引日」。15:30 JST より前で当日が取引日なら当日、それ以外は翌取引日。取引日判定は「土日・日本の祝日（`jpholiday` パッケージ）・12/31〜1/3 を除く」。

### 3.3 シナリオ enum（`app/forecast/config.py` に定義）

| key | 表示名 | 実際の足からの自動判定ルール（上から順に評価、ATR=A, pc=前日終値） |
|---|---|---|
| `round_trip` | 往って来い（長いヒゲ） | `(H−L) ≥ 1.0A` かつ `|C−O| ≤ 0.25(H−L)` |
| `gap_up_trend` | GU→上昇継続 | `(O−pc) ≥ 0.3A` かつ `C ≥ O` |
| `gap_up_fade` | GU→寄り天 | `(O−pc) ≥ 0.3A` かつ `C < O` |
| `gap_down_rebound` | GD→切り返し | `(O−pc) ≤ −0.3A` かつ `C > O` |
| `gap_down_trend` | GD→下落継続 | `(O−pc) ≤ −0.3A` かつ `C ≤ O` |
| `range` | もみ合い（小動き） | `(H−L) < 0.6A` かつ `|C−pc| < 0.3A` |
| `up_trend` | じり上げ | `C − pc ≥ 0.3A` |
| `down_trend` | じり下げ | `C − pc ≤ −0.3A` |
| `other` | その他 | 上記以外 |

日足だけでは日中の値動きの順番が分からないため、自動判定は近似であることを UI のツールチップに記載する。`scenario_hit` は「予想したシナリオ == 実際の足から判定したシナリオ」。ユーザーが `other` を選んだ場合、`scenario_hit` は `null`（集計対象外）。

### 3.4 `forecasts/results.csv`
Actions のジョブが **全 JSON から毎回再生成**する（冪等）。列:
```
id,symbol,name,target_date,weekday,late,status,scenario,actual_scenario,scenario_hit,confidence,
pred_open,pred_high,pred_low,pred_close,act_open,act_high,act_low,act_close,prev_close,atr14,
total,direction,close_s,open_s,range_iou,body_iou,shadow,flat_total,prev_copy_total,skill,
pred_change_atr,act_change_atr,pred_range_atr,act_range_atr,memo,scored_at,scoring_version
```
（`*_change_atr = (close − prev_close)/atr14`、`*_range_atr = (high − low)/atr14`。ダッシュボードの偏り分析に使う）

---

## 4. 採点ロジック（`app/forecast/scoring.py`）

純粋関数として実装し、pytest で網羅すること。記号: 予想足 P=(Op,Hp,Lp,Cp)、実際 R=(Or,Hr,Lr,Cr)、`pc` = 対象日の前取引日終値、`A` = ATR14。

### 4.1 ATR14
`TR_t = max(H_t − L_t, |H_t − C_{t−1}|, |L_t − C_{t−1}|)`、**ATR14 = 対象日の前日までの直近14本の TR の単純平均**。
採点時は**採点時点で取得したデータから再計算した値**を正とする（予想時の snapshot は参考値）。`A <= 0` の場合は `A = pc * 0.01` で代替。

### 4.2 要素スコア（各 0〜100）

| 要素 | 計算 |
|---|---|
| `direction` | `d(x) = +1 if x−pc > 0.1A; −1 if x−pc < −0.1A; else 0`。`d(Cp)==d(Cr)` → 100、片方だけ 0 → 50、逆方向 → 0 |
| `close` | `100 * max(0, 1 − |Cp − Cr| / A)` |
| `open` | `100 * max(0, 1 − |Op − Or| / A)` |
| `range_iou` | 区間 `[Lp,Hp]` と `[Lr,Hr]` の IoU × 100（重なり ÷ 和集合。和集合長 0 なら 100） |
| `body_iou` | 区間 `[min(O,C), max(O,C)]` の IoU × 100。十字線対策に各実体を中心から**最低幅 0.05A** に広げてから計算 |
| `shadow` | 上ヒゲ比 `u = (H − max(O,C)) / (H − L)`、下ヒゲ比 `l = (min(O,C) − L) / (H − L)`（`H==L` なら u=l=0）。`100 * (1 − (|u_p − u_r| + |l_p − l_r|) / 2)` |

### 4.3 総合スコア
```
WEIGHTS = { direction: 0.25, close: 0.20, open: 0.10, range_iou: 0.25, body_iou: 0.15, shadow: 0.05 }
total = Σ weight × 要素スコア   （小数1桁に丸め）
SCORING_VERSION = 1
```
重みと閾値は `config.py` の定数にまとめる。式を変える場合は `SCORING_VERSION` を上げる（ジョブに `--rescore` オプションを用意し、全件再採点できるようにする）。

### 4.4 ベースライン（「何もしない予想」）
同じ関数で採点し、`baselines` に保存する。
- `flat`（横ばい予想）: `O = C = pc`、`H = pc + A/2`、`L = pc − A/2`
- `prev_copy`（前日の足のコピー）: 前日の足の形を `pc` を基準に平行移動したもの。前日足 (O1,H1,L1,C1)、前々日終値 pc1 として `O = pc + (O1 − pc1)`、H/L/C も同様
- `skill = total − baselines.flat.total`（ダッシュボードの主要指標）

### 4.5 テストケース（最低限）
- 予想 = 実際 → total 100
- 方向が逆で値幅もずれている → total が低い（例: < 30）
- 十字線（O==C）でも ZeroDivision にならない
- H==L の足でも落ちない
- flat ベースラインの各値が式どおり
- シナリオ自動判定: 各 enum に該当する足を1つずつ用意

---

## 5. 画面と API（FastAPI）

`app/forecast/routes.py` に `APIRouter(prefix="")` を作り、`app/main.py` に `app.include_router(...)` を **1行追加**するだけにする（既存ルートは変更しない）。静的 JS は `app/static/` を作って `StaticFiles` でマウントする（パスは `Path(__file__)` 基準）。

### 5.1 エンドポイント

| Method | Path | 内容 |
|---|---|---|
| GET | `/forecast` | 銘柄選択 + 次の取引日の予想一覧（保存済み/未入力）+ 直近の採点結果5件 |
| GET | `/forecast/{symbol}` | 予想入力画面（案A） |
| GET | `/forecast/dashboard` | 成績ダッシュボード（※ `/forecast/{symbol}` より**先に**登録してルート衝突を避ける） |
| GET | `/api/forecast/candles/{symbol}?days=120` | `{symbol, name, bars:[{time,open,high,low,close,volume}], prev_close, prev_date, atr14, target_date, locked, existing}` |
| GET | `/api/forecast/{target_date}/{symbol}` | 保存済み予想 |
| POST | `/api/forecast` | 保存（3.2 の検証・ロック）。成功で保存した JSON を返す |
| GET | `/api/forecast/results` | results.csv を JSON 化（クエリで `include_late`, `symbol`, `from`, `to`） |

- yfinance 取得は `auto_adjust=False`（実際の4本値で採点・表示するため）。index の tz は Asia/Tokyo の日付に変換。
- yfinance の取得結果はプロセス内で短時間（例: 5分）キャッシュしてよい。
- 銘柄リストは新規 `app/data/forecast_symbols.csv`（`symbol,name`）。日本株の例を数件入れておく。画面ではリスト選択に加えて**コードの直接入力**も可能にする（`7203` や `285A` のように `.T` が無ければ自動で付与）。

### 5.2 予想入力画面（案A）— 最重要 UI

- チャート: **TradingView Lightweight Charts v4.2 系をバージョン固定で CDN 読み込み**（例 `https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js`）。v5 は API が異なるので使わない。
- 直近60営業日の日足 + 出来高 + MA5/MA25。
- 右端（`target_date`）に**半透明の予想ローソク足**を別の candlestick series として描画。
- **ドラッグ操作**: 予想足の位置に O / H / L / C の4つの水平ハンドル（ラベル付き）をチャート上のオーバーレイとして配置。`series.priceToCoordinate` / `coordinateToPrice` と `timeScale().timeToCoordinate` で座標変換。Pointer Events でマウスとタッチの両方に対応。ドラッグ中は制約（H ≥ max(O,C)、L ≤ min(O,C)）を自動で保つ（O/C を H より上に動かしたら H も一緒に上げる等）。チャートのスクロールやズームの後もハンドルの位置を再計算する（`subscribeVisibleTimeRangeChange` / resize）。
- **数値パネル**（ハンドルと双方向に同期）: O/H/L/C の価格、前日比%、ATR倍率、値幅。
- 初期値は **flat ベースライン**（O=C=pc, H/L=pc±A/2）。保存済みならその値。
- 下部フォーム: **シナリオ**（必須。ラジオボタン or セレクト。小さなローソク足アイコンがあると良い）、**自信度**（1〜5 の星 or セグメント）、**メモ**（textarea、500文字カウンタ）。
- 「保存」→ POST。ロック済みなら読み取り専用表示 + 「9:00 を過ぎたため編集できません」。late の場合は保存前に確認ダイアログを出す。
- スマホ幅（〜400px）でも操作可能なレイアウト。

### 5.3 成績ダッシュボード

グラフは Chart.js（CDN・バージョン固定）を使う。期間フィルタ（直近20日 / 60日 / 全期間）、銘柄フィルタ、late を含めるトグル。

1. **KPI カード**: 採点件数、平均スコア、**平均スキル（自分 − 横ばい予想）とプラスだった日の割合**、方向的中率、シナリオ的中率
2. **スコア推移**: 日別 total（点）＋ 10件移動平均（線）＋ flat ベースラインの移動平均（線）
3. **偏り分析**
   - 楽観/悲観バイアス: `mean(pred_change_atr − act_change_atr)`（+なら上に予想しがち）
   - 値幅の見積もり: `mean(pred_range_atr / act_range_atr)`（<1 なら値幅を小さく見がち）
   - 散布図: x=実際の前日比(ATR)、y=予想の前日比(ATR)
4. **自信度別**: 自信度1〜5ごとの件数・平均スコア・平均スキル（棒グラフ）
5. **シナリオ別**: 予想したシナリオごとの件数・的中率・平均スコア ＋ 予想シナリオ×実際シナリオの混同行列（表）
6. **銘柄別 / 曜日別**: 平均スコア・平均スキル
7. **振り返り一覧**: 直近の予想カード（予想と実際の比較画像 `output/forecast/*.png` のサムネイル、スコア内訳、シナリオ、自信度、**メモ**）

集計ロジックは `app/forecast/stats.py` に pandas で実装し、テンプレート側は描画だけにする。

---

## 6. 採点ジョブ（`python -m app.forecast.job`）

```
python -m app.forecast.job [--date YYYY-MM-DD] [--dry-run] [--no-notify] [--rescore]
```
処理:
1. LocalStore で `status == pending` かつ `target_date <= 今日(JST)` の予想を列挙
2. 銘柄ごとに yfinance で日足を取得（`auto_adjust=False`、十分な期間）
3. 対象日の足が**確定しているか**判定: 対象日が今日なら現在時刻 ≥ 15:45 JST であること。対象日の足が存在しない場合 → 対象日が非取引日、または**対象日より後の足が既に存在する**なら `void`（`void_reason`）、それ以外は次回に持ち越し（pending のまま）
4. 採点（4章）→ JSON 更新 → 予想 vs 実際の画像生成
5. `results.csv` を全件から再生成
6. 新たに採点した分を LINE 通知（`--no-notify` / `--dry-run` 時は送らない。dry-run はファイルも書かず標準出力のみ）

### 6.1 画像（`app/forecast/image.py`、matplotlib のみ使用。mplfinance は追加しない）
- `output/forecast/{id}.png`。直近20本の実際の日足 + 対象日の位置に **実際の足（実色）と予想足（半透明・破線枠）を左右に並べて**表示
- タイトル: `7203.T トヨタ 2026-10-09  78.4点（横ばい比 +23.2）`
- 日本語フォント: Actions では `fonts-noto-cjk` を apt で入れる。フォントが無い環境では英字にフォールバックして落ちないこと
- LINE の画像 URL は既存の方式に合わせる: `https://nfukuno.github.io/stock-app/output/forecast/{id}.png`（URL エンコードに注意。`.T` は問題なし）

### 6.2 LINE 通知
既存の `app/line_notify/notify.py` の `send_line_notification` を再利用（必要なら「テキスト1件 + 画像複数件」を送れる関数を同ファイルに追加。LINE push は1リクエストあたり最大5メッセージ）。テキスト例:
```
📊 10/9 日足予想の採点結果
7203.T トヨタ  78.4点（横ばい比 +23.2）
  方向○  シナリオ○(GU→上昇継続)  自信4
  メモ: 米株高と円安。寄り後の押し目を拾われる想定
6758.T ソニーG  41.0点（横ばい比 −9.8）
  方向✕  シナリオ✕(予想:じり上げ / 実際:GD→下落継続)  自信2
直近10件 平均スキル +6.3
```
**画像 URL を送るのは push の後**（GitHub Pages の反映待ちとして push 後に 60 秒程度 sleep してから通知でよい）。

### 6.3 ワークフロー `.github/workflows/forecast_score.yml`
- `on: schedule` 平日 `30 7 * * 1-5`（JST 16:30）と `0 11 * * 1-5`（JST 20:00、データ遅延時の再試行）、`workflow_dispatch`（inputs: date, rescore）
- `permissions: contents: write`、`concurrency: forecast-score`
- 手順: checkout → Python 3.11 → `sudo apt-get install -y fonts-noto-cjk` → `pip install -r requirements.txt` → `python -m app.forecast.job --no-notify`（ファイル更新のみ）→ commit（`forecasts/`, `output/forecast/`）→ `git pull --rebase` + push（最大3回リトライ）→ 60 秒待つ → 通知ステップ（ジョブが書き出した `forecasts/.pending_notify.json` を読んで送信し、送信後に削除して commit。または採点と通知を `--notify-only` で分ける等、**push 前に通知しない**構成であれば実装方法は任意）
- 変更が無ければ何もせず正常終了

---

## 7. 追加・変更ファイル一覧（目安）

```
app/forecast/__init__.py
app/forecast/config.py      重み・閾値・シナリオ enum・SCORING_VERSION・パス
app/forecast/market.py      JST、取引日カレンダー(jpholiday)、yfinance 取得、ATR
app/forecast/scoring.py     4章の純粋関数
app/forecast/scenarios.py   シナリオ自動判定
app/forecast/models.py      pydantic モデル（Prediction, Score 等）
app/forecast/store.py       ForecastStore / GitHubStore / LocalStore
app/forecast/stats.py       ダッシュボード集計
app/forecast/image.py       比較画像
app/forecast/notify.py      LINE 文面生成（送信は line_notify を利用）
app/forecast/job.py         採点ジョブ CLI
app/forecast/routes.py      画面 + API
app/static/js/forecast_input.js
app/static/js/forecast_dashboard.js
app/templates/forecast_index.html / forecast_input.html / forecast_dashboard.html
app/data/forecast_symbols.csv
forecasts/.gitkeep
output/forecast/.gitkeep
tests/forecast/test_scoring.py / test_scenarios.py / test_market.py / test_store.py / test_stats.py / test_routes.py
.github/workflows/forecast_score.yml
.env.example
requirements.txt          + jpholiday, python-dotenv, pytest, httpx（TestClient 用）
docker-compose.yml        env 追加
README.md                 「日足予想機能」節を追加（セットアップ・PAT 作成手順・public リポジトリの注意）
app/main.py               include_router と StaticFiles マウントのみ追記
```

---

## 8. 実装の進め方（フェーズごとにコミット＆プッシュ）

1. **Core**: config / market / scoring / scenarios / models / store(Local) + テスト。`pytest` が通ること
2. **入力 UI + API**: routes / テンプレート / forecast_input.js / GitHubStore。ローカルで `FORECAST_STORAGE=local uvicorn app.main:app` を起動し、Playwright（Chromium はプリインストール済み。`playwright install` は実行しない）で `/forecast/7203.T` を開き、ハンドルのドラッグ → 保存 → JSON 生成までを確認、スクリーンショットを撮る
3. **採点ジョブ + 画像 + LINE + ワークフロー**: 過去日付（例: 直近の営業日）のダミー予想 JSON を一時的に作り、`python -m app.forecast.job --dry-run` と `--no-notify` で採点・画像・results.csv を確認（確認用のダミーデータはコミットしない）
4. **ダッシュボード**: 過去20営業日分のダミー予想を一時生成→採点→画面を Playwright で確認
5. **ドキュメント**: README、.env.example

各フェーズの終わりに `pytest` を実行し、通ってからコミットすること。

---

## 9. 完了条件（Definition of Done）

- [ ] `pytest` がすべて通る（採点・シナリオ・取引日・ストア・集計・API）
- [ ] 予想入力画面でマウスとタッチ（Playwright のモバイルエミュレーション）によるドラッグが動き、制約が保たれる
- [ ] 9:00 JST 以降は既存予想の編集が 409、新規は late 扱い
- [ ] ジョブが pending → scored / void を正しく判定し、JSON・results.csv・画像を出力する
- [ ] ベースライン（flat / prev_copy）とスキルが保存・表示される
- [ ] ダッシュボードの全セクション（5.3 の 1〜7）が表示される。データ0件でもエラーにならない
- [ ] 既存の `/` と `notify.yml` の動作に影響がない
- [ ] README にユーザーの手作業（下記10章）が書かれている

---

## 10. ユーザー側で必要な作業（README に記載する）

1. GitHub で **fine-grained PAT** を作成（Repository access: `nfukuno/stock-app` のみ / Permissions: Contents = Read and write）→ ローカルの `.env` に `FORECAST_GITHUB_TOKEN` として設定し、`FORECAST_STORAGE=github` にする
2. Actions の secrets `LINE_ACCESS_TOKEN` / `LINE_USER_ID` は既存のものを流用（追加作業なし）
3. **PR を main にマージ**（マージされるまでスケジュール実行は動かない）
4. 動作確認: Actions の `forecast_score` を `workflow_dispatch` で手動実行

---

## 11. 将来の拡張（今回はやらない）
- 5分足を使った日中パス評価（DTW）。yfinance の5分足は直近60日分しか取れないため、着手する場合は5分足を日次で保存する仕組みを先に入れる
- 米国株対応（採点時刻・取引日カレンダーを市場別にする）
- 採点の重みをユーザーが画面から調整する
