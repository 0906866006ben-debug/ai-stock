# Codex 日誌：加密掃描修正與推播對齊

日期：2026-07-07  
分支：`001-mvp-stock-analysis`  
主題：修正加密掃描觀察名單邏輯、Vercel 部署、Discord signal 推播文字

## 背景

這次處理的是加密掃描這個額外功能。使用者明確指出：`15m EMA12` 是做單策略裡的目標參考，不是篩選條件。

我一開始誤把 `15m EMA12 偏離`、資費方向和品質分當成觀察名單 gate，導致超買/超賣幣即使出現，也可能因為離 EMA12 不夠遠或資費不合而沒有跳出。這和使用者真正要的流程不同。

使用者真正要的是：

- 先找到 `1h RSI` 超買或超賣。
- 進入觀察名單後，再盯 `1m EMA12` 是否跌破或突破。
- `15m EMA12` 只當作目標參考。
- 資費、OI、偏離 z 只能當輔助參考或排序加分，不應該擋名單。

## 目前行為

加密掃描現在採用 `rsi_setup_v2`：

- `1h RSI >= 75`：列入超買、空向觀察。
- `1h RSI <= 25`：列入超賣、多向觀察。
- `1m EMA12`：用來判斷跌破/突破觸發，並要求下一根守住。
- `15m EMA12`：只顯示為目標距離，不再作為入選條件。
- `funding / OI / ext_z / volume`：保留為排序、品質分、訊息參考。
- 預設掃描範圍放大到 `top=150`，品質分門檻預設 `minQ=0`。

## 修改內容

### Vercel API

檔案：`ai-stock-frontend/app/api/crypto-scan/route.ts`

- 移除 `15m EMA12 偏離` 與資費方向的硬 gate。
- 第一階段只用 `1h RSI` 超買/超賣產生觀察名單。
- 第二階段把觸發條件改成 `1m EMA12` 跌破/突破並守住。
- 保留放量作為 `★` 升級，不作為入選必要條件。
- 新增 `scan_mode: "rsi_setup_v2"`，方便確認 Vercel 是否部署到新版。

### 前端加密掃描頁

檔案：`ai-stock-frontend/app/components/CryptoScanView.tsx`

- 預設請求改成 `/api/crypto-scan?minVol=15&top=150&minQ=0`。
- 文案改成「1h RSI 先進觀察名單，1m EMA12 才是觸發」。
- 明確標示 `15m EMA12` 是目標參考，不是跳出訊號條件。
- 移除舊的 `EMA20` 說法。

### Python 掃描腳本

檔案：`backend/scripts/crypto_anomaly_scanner.py`

- 與 Next API 對齊成 `1h RSI -> 觀察名單`、`1m EMA12 -> 觸發`。
- 預設改成 `--top 150 --min-q 0`。
- JSON 輸出新增 `scan_mode: "rsi_setup_v2"`。
- 修正 NumPy bool / number 造成 `json.dumps` 失敗的問題。

### Discord signal 推播

檔案：`backend/scripts/discord_replay_bot.py`

- `SCAN_URL` 改成新版 API 參數。
- 推播文字改成觀察語氣，避免看起來像直接下單訊號。
- 未觸發時顯示：
  - `設定: 1h RSI 超買/超賣`
  - `等待: 1m EMA12 跌破/突破 + 守住`
  - `目標參考: 15m EMA12 距離`
- 已觸發時顯示：
  - `1m EMA12跌破觀察` 或 `1m EMA12突破觀察`
  - `扳機: 1m整根實體...EMA12+守住`
- 抽出 `build_signal_message()`，避免推播格式以後改漏。

## 驗證

已執行：

- `npm exec -- eslint app/api/crypto-scan/route.ts app/components/CryptoScanView.tsx --no-warn-ignored`
- `npm exec -- tsc --noEmit --pretty false`
- `.venv\Scripts\python.exe -m py_compile backend\scripts\crypto_anomaly_scanner.py backend\scripts\discord_replay_bot.py`
- `.venv\Scripts\python.exe backend\scripts\crypto_anomaly_scanner.py --json --top 150 --min-vol 15 --min-q 0`
- `npm run build`
- 本機 Next API smoke test
- Vercel API smoke test
- 正式站瀏覽器檢查
- Discord 推播訊息模板測試

驗證重點：

- Python 掃描曾回傳 `EVAAUSDT`，即使 `ext_z` 很低仍進名單，證明 `15m EMA12 偏離` 已不再擋名單。
- 正式站 API 回傳 `scan_mode: "rsi_setup_v2"`。
- 正式站加密掃描頁出現新版文案與觀察名單，且沒有舊 `EMA20` 文案。
- Discord 推播模板可用正式 API row 產生新版訊息。

## 部署與提交

已推到 GitHub，透過 Vercel Git 整合部署。

相關 commit：

- `f7135a1 Fix crypto scan setup gates`
- `76ca419 Align Discord crypto signal copy`

正式站：

- `https://ai-stock-rosy-eight.vercel.app`

## 非目標

這次沒有做：

- 沒有新增回測或宣稱此策略有 edge。
- 沒有改台股核心分析、推薦守則或後端主流程。
- 沒有碰工作區裡原本存在的其他文件與回測資料變更。
- 沒有把觀察名單改成自動下單或直接買賣建議。

## 剩餘注意事項

- Discord bot 如果是常駐程序，需要重啟才會載入新的推播文字。
- 加密掃描仍是觀察輔助，不是回測完成的策略模組。
- 如果未來要提高訊號品質，應該另外建立可回測規則，而不是再把目標 EMA 或資費塞回觀察名單 gate。

## Codex 自我備註

這次最重要的修正不是程式碼，而是把使用者的交易流程聽準：

`15m EMA12` 是目標，不是門票。  
`1h RSI` 才是找名單。  
`1m EMA12` 才是進場觀察。

我前面把「目標」誤作「篩選條件」，這會讓系統太聰明反而錯過使用者真正要看的東西。修正後，功能比較單純，也更貼近使用者的實際看盤節奏。
