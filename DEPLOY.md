# 部署到外網（讓別人用網址查看介面）

GitHub 只存程式碼、不會幫你「跑」這個 app。要在外網看介面，得把 repo 接到會執行它的平台：
**前端 → Vercel、後端 → Render**。兩邊都從你的 GitHub repo 自動部署。

> app 沒有任何 API 金鑰也會回 **mock 資料**，所以部署後介面是完整可用的 demo。

---

## Step 1 — 後端上 Render

1. 到 <https://render.com> 用 GitHub 帳號登入。
2. **New ➜ Blueprint**，選這個 repo（`0906866006ben-debug/ai-stock`）。
3. Render 會自動讀取根目錄的 `render.yaml`，服務名稱 `ai-stock-backend`。
4. 按 **Apply / Create**。第一次 build 約 3–8 分鐘（在裝 pandas/numpy）。
5. 完成後會拿到一個網址，例如：`https://ai-stock-backend.onrender.com`
   - 打開 `https://<那個網址>/health` 應該回 `{"status":"ok"}`（或類似）就代表活著。

> 免費方案會在閒置後休眠，第一次打開會慢 30–50 秒喚醒，正常現象。

## Step 2 — 前端上 Vercel

1. 到 <https://vercel.com> 用 GitHub 帳號登入 ➜ **Add New ➜ Project** ➜ 選同一個 repo。
2. **關鍵設定：Root Directory 選 `ai-stock-frontend`**（不是 repo 根目錄）。
   Framework 會自動偵測成 Next.js。
3. 展開 **Environment Variables**，新增一個：
   | Name | Value |
   |---|---|
   | `NEXT_PUBLIC_API_URL` | Step 1 拿到的後端網址（例：`https://ai-stock-backend.onrender.com`） |
4. 按 **Deploy**。完成後拿到前端網址，例如 `https://ai-stock.vercel.app` —— 這就是你要的「外網介面」。

## Step 3 —（可選）之後要真資料 / AI

在 Render 的 **Environment** 分頁補上金鑰即可，app 會自動從 mock 切成 live：
`GEMINI_API_KEY`、`FINMIND_API_KEY`、`FMP_API_KEY`、`FINNHUB_API_KEY` …

---

## 已知限制（看介面沒問題，但要知道）

- **資料庫沒上雲**：`historical_data.db` / `pit_fundamentals.db` 被 `.gitignore` 排除（曾超過 GitHub 100MB 限制）。
  因此**依賴這些 DB 的頁面**（篩選器 screener、品質觀察 quality-watch）會是空的/無資料。
  核心的個股分析、K 線、技術指標走 FinMind/yfinance（live+mock），不受影響。
- 若之後要讓那些頁面也有料，得在 Render 上跑一次 `refresh_data.py` 建 DB，或改用外接資料庫——那是另一個工程。
