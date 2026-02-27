# scroll_copy

Webページ内の特定スクロール領域に表示されるテキストを、スクロール操作に合わせて自動収集し、重複除去したうえでテキスト出力するローカルスクリプトプロジェクトです。

## クイックスタート（実装版）

### 1. 仮想環境の作成と有効化

```powershell
# 仮想環境を作成
python -m venv venv

# 仮想環境を有効化
.\venv\Scripts\Activate.ps1
```

実行ポリシーエラーが出た場合：
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### 2. 依存関係インストール

```powershell
pip install -r requirements.txt
playwright install chromium
```

### 3. 既存ブラウザに接続する方法（推奨）

OAuth/SSOログインが必要なサイトや、手動で画面遷移が必要な場合に使用します。

#### 3-1. Chromeをデバッグモードで起動

デスクトップにショートカットを作成：
1. デスクトップで右クリック → 新規作成 → ショートカット
2. 項目の場所に以下を入力：
```
"C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222
```
3. ショートカット名を入力（例：Chrome Debug Mode）

このショートカットからChromeを起動してください。

#### 3-2. 手動でログインと画面遷移

1. デバッグモードで起動したChromeで対象サイトにアクセス
2. 手動でログイン
3. 目的のページまで移動（タブ切り替えなど）

#### 3-3. スクリプトを実行

**デフォルト（話者名付き）：**

```powershell
python scroll_copy.py run `
  --connect-existing `
  --container "#scrollToTargetTargetedFocusZone" `
  --output-raw "./out/raw_output.txt" `
  --output-final "./out/final_output.txt"
```

出力形式：`話者名\t本文テキスト`（タブ区切り）

**本文のみ取得（従来互換）：**

```powershell
python scroll_copy.py run `
  --connect-existing `
  --container "#scrollToTargetTargetedFocusZone" `
  --text-only `
  --line-selector '[class^="entryText-"]' `
  --output-raw "./out/raw_output.txt" `
  --output-final "./out/final_output.txt"
```

**注意：**
- `--connect-existing`を使用する場合、`--url`は省略可能です（現在開いているページで実行されます）
- デフォルトでは話者名付きで取得します。本文のみ必要な場合は`--text-only`を指定してください

### 4. 新しいブラウザで実行する方法

ログインが不要なサイトの場合：

**デフォルト（話者名付き）：**

```powershell
python scroll_copy.py run `
  --url "対象URL" `
  --container "#scrollToTargetTargetedFocusZone" `
  --output-raw "./out/raw_output.txt" `
  --output-final "./out/final_output.txt"
```

**本文のみ取得：**

```powershell
python scroll_copy.py run `
  --url "対象URL" `
  --container "#scrollToTargetTargetedFocusZone" `
  --text-only `
  --line-selector '[class^="entryText-"]' `
  --output-raw "./out/raw_output.txt" `
  --output-final "./out/final_output.txt"
```

ヘッドレスモードを無効にする場合（ブラウザを表示）：
```powershell
python scroll_copy.py run `
  --url "対象URL" `
  --container "#scrollToTargetTargetedFocusZone" `
  --no-headless `
  --output-raw "./out/raw_output.txt" `
  --output-final "./out/final_output.txt"
```

### 5. doctor（事前検証）

セレクタが正しいか確認：

**デフォルト（話者名付きモード）：**

```powershell
python scroll_copy.py doctor `
  --url "対象URL" `
  --container "#scrollToTargetTargetedFocusZone"
```

出力例：
```json
{
  "containerFound": true,
  "containerSelector": "#scrollToTargetTargetedFocusZone",
  "mode": "with_speaker",
  "entryCount": 87,
  "speakerCount": 87,
  "textCount": 87,
  "entrySelector": "[class^=\"baseEntry-\"]",
  "speakerSelector": "[id^=\"timestampSpeakerAriaLabel-\"]",
  "lineSelector": "[class^=\"entryText-\"]",
  "sampleEntry": {
    "speaker": "Yasunari Saitou",
    "text": "あの、例えばほら、なんか項数がこうで。"
  }
}
```

**本文のみモード：**

```powershell
python scroll_copy.py doctor `
  --url "対象URL" `
  --container "#scrollToTargetTargetedFocusZone" `
  --text-only `
  --line-selector '[class^="entryText-"]'
```

### 6. finalize（整形のみ再実行）

収集済みのrawファイルから重複除去のみ実行：

```powershell
python scroll_copy.py finalize `
  --output-raw "./out/raw_output.txt" `
  --output-final "./out/final_output.txt"
```

### 7. 中断後の再開

```powershell
python scroll_copy.py run `
  --resume `
  --state-file "./state.json"
```

## 目的

- スクロール中に表示されるテキストを取りこぼしなく収集する
- 最終的に扱いやすいテキストファイルとして出力する
- 同一行の重複を削除してデータ品質を上げる

## 想定ユースケース

- ページ全体とは別に、テキスト専用のスクロール領域があるサイト
- スクロールを進めると過去の行が消えていく（仮想リスト型）表示
- 手作業コピーでは取りこぼしや重複が起きやすいケース

## 必要機能

1. **スクロール連動取得機能**  
   特定スクロール領域を一定間隔で下方向へスクロールし、表示中のテキスト行を取得する。

2. **一時保持／保存機能**  
   取得行はメモリ上の一時バッファ（仮想クリップボード）または逐次ファイル追記で保持する。

3. **終了判定機能**  
   一定回数スクロールしても新規行が増えない場合、末尾到達とみなして処理を終了する。

4. **重複除去機能**  
   まずは完全一致の行を重複と判定して1行に統合する（将来拡張可能）。

5. **テキスト出力機能**  
   最終結果をUTF-8テキストファイルとして出力する。

## データ保持方式

- 第一候補：**最初からテキストファイルへ追記**
  - 長時間収集時のメモリ使用量を抑えやすい
  - 中断時にも途中データが残る
- 代替案：メモリに蓄積して最後に一括出力
  - 実装は直感的だが、データ量が増えるとメモリ負荷が高くなる

本プロジェクトでは、安定運用のため **逐次ファイル追記＋終了時重複除去** を推奨します。

## 技術選定（推奨）

実装スタックは **Python + Playwright** を第一候補とします。

- DOM取得とスクロール操作の安定性が高い
- 待機・再試行などの制御を実装しやすい
- テキスト処理（重複除去・整形・出力）が書きやすい
- ローカルスクリプト運用に適している

## 実装方針（概要）

1. 対象ページを開く
2. 対象スクロールコンテナを特定
3. ループで「取得→保存→スクロール→新規行判定」を繰り返す
4. 新規行が一定回数増えなければ終了
5. 収集結果を重複除去して最終txtを出力

## 失敗時リカバリ方針

スクロール収集中に通信遅延やDOM更新のタイミングずれ、ブラウザ例外が発生しても、収集結果を可能な限り失わず再開できる設計を採用します。

### 1) 途中保存（チェックポイント）

- 取得した行を都度 `raw_output.txt` に追記保存（即時永続化）
- `state.json` に以下を定期保存
  - 最終スクロール位置
  - 直近の取得件数
  - 新規行が増えなかった連続回数
  - 最終更新時刻

### 2) 自動リトライ

- 要素取得失敗や一時タイムアウト時は、短い待機を挟んで再試行
- 再試行回数上限を超えた場合は異常終了せず中断保存へ移行

### 3) 中断時の安全終了

- 例外発生時でも `state.json` とログを必ず出力
- その時点までの `raw_output.txt` は保持
- 後続の重複除去フェーズのみ再実行できる設計にする

### 4) 再開実行

- `--resume` オプションで `state.json` を読み込み、前回位置から収集再開
- 既存 `raw_output.txt` への追記モードで再開可能にする

### 5) 最終整形の分離

- 収集フェーズと整形フェーズ（重複除去・最終出力）を分離
- 収集失敗後でも整形のみ実行できるようにして復旧容易性を高める

## CLI仕様（実装向け詳細）

コマンド名は `scroll_copy.py` です。

```powershell
python scroll_copy.py run `
  --url "https://example.com" `
  --container ".scroll-pane" `
  --line-selector ".line"
```

### サブコマンド

- `run`: 収集（必要に応じて整形まで実行）
- `finalize`: 既存の `raw_output.txt` から重複除去して最終出力のみ実行
- `doctor`: 設定・セレクタ・権限・出力先の事前チェック

### 主なオプション一覧

| オプション | 型 | デフォルト | 説明 |
|---|---:|---:|---|
| `--url` | string | なし | 対象ページURL（`--connect-existing`時は省略可） |
| `--container` | string | なし | テキスト表示スクロール領域のCSSセレクタ |
| `--line-selector` | string | `[class^="entryText-"]` | 1行テキスト要素のCSSセレクタ |
| `--text-only` | flag | `false` | 本文のみ取得（話者名なし） |
| `--entry-selector` | string | `[class^="baseEntry-"]` | エントリ親要素のセレクタ（話者名付きモード用） |
| `--speaker-selector` | string | `[id^="timestampSpeakerAriaLabel-"]` | 話者名要素のセレクタ（話者名付きモード用） |
| `--output-raw` | path | `./raw_output.txt` | 逐次追記する生データ出力先 |
| `--output-final` | path | `./final_output.txt` | 重複除去後の最終出力先 |
| `--state-file` | path | `./state.json` | 再開用状態ファイル |
| `--resume` | flag | `false` | `state.json` を読み込んで再開 |
| `--connect-existing` | flag | `false` | 既存のデバッグモードブラウザに接続 |
| `--debug-port` | int | `9222` | デバッグポート番号 |
| `--max-idle-scrolls` | int | `15` | 新規行が増えない状態を何回で終了判定するか（長い動画の場合は20-30を推奨） |
| `--scroll-step` | int(px) | `400` | 1回のスクロール量 |
| `--scroll-interval-ms` | int | `600` | スクロール間隔（ms） |
| `--checkpoint-interval` | int(loops) | `5` | 何ループごとに `state.json` を更新するか |
| `--max-retries` | int | `3` | 一時エラー時の再試行回数 |
| `--retry-wait-ms` | int | `1000` | 再試行前待機（ms） |
| `--dedupe-mode` | enum | `exact` | 重複判定方式（初期値は完全一致） |
| `--headless` | flag | `true` | ヘッドレス実行（`--no-headless`で無効化） |
| `--timeout-ms` | int | `30000` | 要素待機・操作タイムアウト |
| `--log-level` | enum | `info` | `debug / info / warn / error` |

> 初期要件では `--dedupe-mode exact` のみサポート。将来 `trim` や `lowercase` などを追加可能な設計とする。

### 新機能：話者名付き取得（v2.0）

**デフォルト動作の変更：**
- v2.0以降、デフォルトで話者名付きで取得します
- 出力形式：`話者名\t本文テキスト`（タブ区切り）
- 話者名から時刻情報（"5 分間 37 秒間"など）は自動除去されます

**本文のみ取得（従来互換）：**
- `--text-only`オプションを指定すると、v1.x互換の本文のみモードで動作します
- この場合、`--line-selector`の指定が必須です

### 新機能：既存ブラウザ接続

`--connect-existing`オプションを使用すると、手動でログイン済みのブラウザに接続できます。

**メリット：**
- OAuth/SSOログインが必要なサイトに対応
- 手動で画面遷移（タブ切り替えなど）してからスクリプト実行可能
- ログイン処理の自動化が不要

**使用手順：**
1. Chromeをデバッグモードで起動（`--remote-debugging-port=9222`）
2. 手動でログインと画面遷移
3. `--connect-existing`オプションでスクリプト実行

### 実行例

```powershell
# 既存ブラウザに接続して実行（推奨・話者名付き）
python scroll_copy.py run `
  --connect-existing `
  --container "#scrollToTargetTargetedFocusZone" `
  --output-raw "./out/raw_output.txt" `
  --output-final "./out/final_output.txt"

# 新規ブラウザで実行（話者名付き）
python scroll_copy.py run `
  --url "https://example.com/page" `
  --container "#scrollToTargetTargetedFocusZone" `
  --output-raw "./out/raw_output.txt" `
  --output-final "./out/final_output.txt"

# 本文のみ取得（従来互換）
python scroll_copy.py run `
  --connect-existing `
  --container "#scrollToTargetTargetedFocusZone" `
  --text-only `
  --line-selector '[class^="entryText-"]' `
  --output-raw "./out/raw_output.txt" `
  --output-final "./out/final_output.txt"

# 中断後の再開
python scroll_copy.py run `
  --resume `
  --state-file "./state.json"

# 収集済みrawから整形のみ再実行
python scroll_copy.py finalize `
  --output-raw "./out/raw_output.txt" `
  --output-final "./out/final_output.txt" `
  --dedupe-mode exact

# 複数行にまたがるコマンド（PowerShell）
python scroll_copy.py run `
  --connect-existing `
  --container "#scrollToTargetTargetedFocusZone" `
  --line-selector '[class^="entryText-"]' `
  --max-idle-scrolls 10 `
  --scroll-step 500 `
  --scroll-interval-ms 800 `
  --output-raw "./out/raw_output.txt" `
  --output-final "./out/final_output.txt"
```

### 実サイトで確定したセレクタ例

以下は実際の確認結果に基づく、今回サイト向けの設定例です。

- `--container '#scrollToTargetTargetedFocusZone'`
- `--line-selector '[class^="entryText-"]'`

実行前のConsole確認結果:

```js
{ containerFound: true, lineCount: 87 }
```

実行コマンド例:

```powershell
# 既存ブラウザに接続（推奨）
python scroll_copy.py run `
  --connect-existing `
  --container "#scrollToTargetTargetedFocusZone" `
  --line-selector '[class^="entryText-"]' `
  --max-idle-scrolls 8 `
  --output-raw "./out/raw_output.txt" `
  --output-final "./out/final_output.txt"

# 新規ブラウザで実行
python scroll_copy.py run `
  --url "対象URL" `
  --container "#scrollToTargetTargetedFocusZone" `
  --line-selector '[class^="entryText-"]' `
  --max-idle-scrolls 8 `
  --output-raw "./out/raw_output.txt" `
  --output-final "./out/final_output.txt"
```

## `state.json` スキーマ（初版）

```json
{
  "version": 1,
  "run_id": "20260215T124500Z_abc123",
  "status": "running",
  "target": {
    "url": "https://example.com/page",
    "container_selector": ".transcript-scroll",
    "line_selector": ".transcript-line"
  },
  "progress": {
    "loop_count": 42,
    "scroll_top": 16800,
    "total_lines_seen": 1260,
    "unique_lines_seen": 1184,
    "idle_scroll_count": 2,
    "last_new_line_at": "2026-02-15T12:47:12+09:00"
  },
  "files": {
    "raw_output": "./out/raw_output.txt",
    "final_output": "./out/final_output.txt",
    "log_file": "./out/run.log"
  },
  "runtime": {
    "max_idle_scrolls": 8,
    "scroll_step": 400,
    "scroll_interval_ms": 600,
    "max_retries": 3,
    "retry_wait_ms": 1000,
    "dedupe_mode": "exact"
  },
  "timestamps": {
    "started_at": "2026-02-15T12:45:01+09:00",
    "updated_at": "2026-02-15T12:48:20+09:00"
  },
  "last_error": null
}
```

### スキーマ項目の意味

- `status`: `running / interrupted / completed / failed`
- `progress.idle_scroll_count`: 新規行未検出の連続回数（終了判定に利用）
- `last_error`: 直近の失敗情報（再開可否判断に利用）

例（失敗時）:

```json
{
  "code": "E_CONTAINER_NOT_FOUND",
  "message": "container selector not found",
  "at": "2026-02-15T12:49:03+09:00",
  "retry_count": 3
}
```

## 終了コード設計（推奨）

- `0`: 正常終了
- `10`: 設定不正（必須引数不足・型不正）
- `20`: 対象要素未検出（container/line selector不一致）
- `30`: リトライ上限超過で中断保存
- `40`: 出力書き込み失敗
- `50`: 予期しない例外

## トラブルシューティング

### エラー: `[selector error] container not found`

**原因：** Chrome内部タブ（`chrome://` や `devtools://`）が選択されている可能性があります。

**解決方法：**

1. **タブ選択機能を使用**（v2.1以降）
   - `--connect-existing` で接続すると、有効なタブが自動的に列挙されます
   - 対象ページのタブ番号を入力してください

2. **手動でタブを整理**
   - デバッグモードのChromeで、対象ページのタブをアクティブにする
   - 不要なタブ（DevToolsなど）を閉じる
   - スクリプトを再実行

3. **診断スクリプトで調査**
   ```powershell
   python inspect_page.py --connect-existing
   ```
   このスクリプトが正しいセレクタを提案します。

### 問題: 最後までスクロールせずに終了する

**原因：** 終了判定の閾値（`--max-idle-scrolls`）が小さすぎる可能性があります。

**解決方法：**

閾値を増やして実行：
```powershell
python scroll_copy.py run `
  --connect-existing `
  --container "#scrollToTargetTargetedFocusZone" `
  --max-idle-scrolls 20 `
  --output-raw "./out/raw_output.txt" `
  --output-final "./out/final_output.txt"
```

**パラメータ調整のガイドライン：**
- `--max-idle-scrolls`: 新規行が増えない状態を何回連続で許容するか
  - デフォルト: `15`
  - 短い動画: `10-15`
  - 長い動画: `20-30`
  - 非常に長い動画: `30-50`

- `--scroll-step`: 1回のスクロール量（ピクセル）
  - デフォルト: `400`
  - 小さくすると取りこぼしが減るが、処理時間が増える

- `--scroll-interval-ms`: スクロール間隔（ミリ秒）
  - デフォルト: `600`
  - 大きくすると安定するが、処理時間が増える

### 問題: セレクタが見つからない（Webサイトの構造変更）

**解決方法：**

1. **診断スクリプトを実行**
   ```powershell
   python inspect_page.py --connect-existing
   ```

2. **推奨セレクタを確認**
   スクリプトが自動的に正しいセレクタを提案します。

3. **doctorコマンドで検証**
   ```powershell
   python scroll_copy.py doctor `
     --url "対象URL" `
     --container "推奨されたセレクタ"
   ```

4. **新しいセレクタで実行**
   ```powershell
   python scroll_copy.py run `
     --connect-existing `
     --container "新しいセレクタ" `
     --output-raw "./out/raw_output.txt" `
     --output-final "./out/final_output.txt"
   ```
これにより、CIやバッチ実行時に終了理由を機械的に判定しやすくする。