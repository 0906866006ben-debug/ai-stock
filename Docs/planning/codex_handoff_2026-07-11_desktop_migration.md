# 交接企劃書：alpha 研究平台從筆電搬遷到主機（5TB）

給主機上的 Claude Code / codex session 執行。筆電端的收尾（第 8 節）由筆電上的 Claude Code session 負責，**不要**在主機端執行第 8 節。

## 使用者原始需求與意圖

筆電容量與斷電/睡眠問題，使用者要把「自主 alpha 研究平台」（research_platform + 加密回測引擎 + 衍生品回填 + Tailscale funnel + Vercel dashboard 後端）搬到常開的主機（Windows、5TB）。**實盤 bot（crypto_auto_trader / discord_replay_bot / telegram / trade log）不在本次範圍**——它們有持倉 state，需另擇無持倉時點搬。

## 目前架構（筆電側，搬遷來源）

- repo：`ai-stock`（私有），分支 `feature/autonomous-alpha-research`（已推 GitHub）
- 市場快取：`%USERPROFILE%\.crypto_backtest\klines.db`（~2.2GB、持續回填中，SQLite WAL）
- 研究 metadata：`backend/data/research_platform/research.db`（小，可重建，不必搬）
- 機密：`backend/.env`（含 `AI_STOCK_BACKEND_TOKEN`、`RESEARCH_API_REQUIRE_AUTH=1` 等）——**永不 commit**，用 Taildrop 傳
- 常駐：排程任務「AI-Stock Research Platform」（logon 觸發 `tools/start_research_platform.ps1`，起 uvicorn:8000 + research_orchestrator worker + 快取預熱）
- 對外：Tailscale Funnel `--set-path /api` 只開放 `/api` 子樹；dashboard（Vercel，repo `ai-stock-research-dashboard`）BFF 以 `AI_STOCK_BACKEND_URL` 連此 funnel 網址
- 回填：`backend/data/research_platform/_backfill_runner.py`（508 幣全宇宙、頻率排序、斷點續傳；shard 參數 `<i> <n>`）+ `_relay_backfill.ps1`

## 主機端執行 checklist

### 1. 前置安裝
- [ ] Git、Python 3.12、Tailscale（登入 `0906866006ben@gmail.com` 的 Google 帳號——tailnet 是 `tailbed1ea.ts.net`，**不要**用 GitHub 帳號登，會開出另一個空 tailnet）
- [ ] `gh auth login`（repo 私有）

### 2. Clone + venv
```powershell
git clone https://github.com/0906866006ben-debug/ai-stock.git
cd ai-stock
git checkout feature/autonomous-alpha-research
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
```
（主機也是 Windows，`requirements.txt` 的 pywin32 可裝；若失敗改用 `requirements-deploy.txt` 再補漏套件。）

### 3. 接收筆電傳來的檔案（Taildrop）
筆電端會用 `tailscale file cp` 送出 `klines.db` 與 `.env`。主機端：
```powershell
tailscale file get $env:USERPROFILE\Downloads
New-Item -ItemType Directory -Force "$env:USERPROFILE\.crypto_backtest"
Move-Item "$env:USERPROFILE\Downloads\klines.db" "$env:USERPROFILE\.crypto_backtest\klines.db"
Move-Item "$env:USERPROFILE\Downloads\.env" "backend\.env"
```
- [ ] 確認 `klines.db` 大小 ≥ 2GB、`backend/.env` 內含 `AI_STOCK_BACKEND_TOKEN`

### 4. 啟動平台
```powershell
.\tools\start_research_platform.ps1
.\tools\install_research_startup_task.ps1
```
- [ ] `http://127.0.0.1:8000/api/v1/health` 回 200
- [ ] 帶 token 打 `/api/v1/market/meme?scope=meme` 回 200；不帶 token 回 401

### 5. Funnel（對外網址會變！）
```powershell
tailscale funnel --bg --set-path /api http://127.0.0.1:8000/api
tailscale funnel status
```
- [ ] 記下新網址 `https://<主機名>.tailbed1ea.ts.net`
- [ ] 公網驗證：`/api/v1/health` 200、研究端點無 token 401、`/analyze/tw` 404（主 app 不得暴露）

### 6. 更新 Vercel（使用者瀏覽器操作）
- [ ] Vercel 專案 `ai-stock-research-dashboard` → Settings → Environment Variables → `AI_STOCK_BACKEND_URL` 改成第 5 步的新網址 → Redeploy
- [ ] 手機/瀏覽器開 https://ai-stock-research-dashboard-ebon.vercel.app 登入，「市場數據」兩個分頁都有數字

### 7. 恢復回填（斷點續傳，已完成的自動跳過）
```powershell
foreach($i in 0,1,2){ Start-Process .venv\Scripts\python.exe -ArgumentList "backend\data\research_platform\_backfill_runner.py","$i","3" -WindowStyle Hidden -RedirectStandardOutput "backend\data\research_platform\logs\backfill-shard$i.out.log" -RedirectStandardError "backend\data\research_platform\logs\backfill-shard$i.err.log" }
```
- [ ] log 出現 `[ok] ... rows now ...`；主機網路穩，可視情況加到 4-6 分片
- [ ] dashboard「全市場山寨」進度 % 持續上升

### 8. 筆電端收尾（由筆電 session 執行，主機驗收全過後才做）
- 停排程任務、殺回填/uvicorn/worker 行程、`tailscale funnel reset`
- 筆電的 klines.db 保留當備份，標註截止時點

## 非目標
- 不搬實盤 bot 與其 state/lock 檔
- 不動台股正典資料庫（historical_data.db / pit_fundamentals.db 留筆電，另議）
- 不改回測引擎邏輯、不跑 OOS

## 已知風險
- 兩台同時開 funnel：Vercel 只會連 env var 指的那台，但務必完成第 8 節避免混淆
- 兩台同時回填寫各自的 klines.db 會分裂資料——傳檔後筆電端即停回填（筆電 session 負責）
- `.env` 含高危金鑰，只准 Taildrop/區網傳，不准經雲端

## 驗收條件（全過才算完成）
1. 主機 health 200、token 閘門正常
2. funnel 公網可達且只暴露 /api
3. Vercel dashboard 顯示真實數據（兩個 scope）
4. 回填 log 前進中、dashboard 進度上升
5. 開機重啟主機後平台自動恢復（排程任務生效）
