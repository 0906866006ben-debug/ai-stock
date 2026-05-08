# AI Stock 專案 — 開發者工具完整參考手冊

> 本文件記錄此專案實際使用的所有工具、套件與指令。
> 所有指令均以專案根目錄 `/home/ben_0527/project/ai-stock` 為執行位置，除非另有說明。

---

## 目錄

1. [Claude Code 指令](#1-claude-code-指令)
2. [Git 工作流程指令](#2-git-工作流程指令)
3. [RTK 指令](#3-rtk-指令)
4. [Superpowers 外掛指令](#4-superpowers-外掛指令)
5. [Spec-kit 指令](#5-spec-kit-指令)
6. [後端 Python 指令](#6-後端-python-指令)
7. [金融 Python 套件](#7-金融-python-套件)
8. [前端指令](#8-前端指令)
9. [前端套件](#9-前端套件)
10. [環境變數](#10-環境變數)
11. [常見開發工作流程](#11-常見開發工作流程)

---

## 1. Claude Code 指令

Claude Code 的指令分為兩類：**CLI 啟動參數**（在終端機輸入）和**對話內斜線指令**（在 `>` 提示字元輸入）。

### 1.1 CLI 啟動方式

| 指令 | 用途 |
|---|---|
| `claude` | 以互動模式啟動 Claude Code（最常用） |
| `claude --permission-mode acceptEdits` | 自動允許所有檔案編輯，無需逐一確認。適合信任 Claude 直接修改檔案的場景 |

```bash
# 一般啟動
claude

# 允許自動編輯（不需要手動確認每個檔案修改）
claude --permission-mode acceptEdits
```

> ⚠️ `acceptEdits` 模式下，Claude 可以直接修改任何檔案，不會詢問。請確認你信任目前的任務再使用。

---

### 1.2 對話內斜線指令

在 Claude Code 的 `>` 輸入框中輸入：

| 指令 | 說明 | 使用時機 |
|---|---|---|
| `/help` | 顯示所有可用指令與鍵盤快捷鍵 | 忘記指令時查詢 |
| `/status` | 顯示目前模型、Token 使用量、Session 資訊 | 確認目前使用哪個模型 |
| `/clear` | 清除整個對話歷史，重新開始 | 開始新任務；對話太長導致 Claude 混淆 |
| `/compact` | 壓縮對話歷史，保留重要上下文但節省 Token | 長時間工作後 Session 變慢時 |
| `/permissions` | 顯示哪些工具已自動允許、哪些需要確認 | 想了解或調整 Claude 的操作權限 |
| `/config` | 開啟互動式設定選單（模型、佈景主題、自動允許等） | 切換模型、調整自動確認規則 |
| `/review` | 對目前的 staged/unstaged diff 進行程式碼審查 | 提交前快速複查改動 |

---

### 1.3 訊息前綴（在一般訊息中使用）

| 前綴 | 說明 | 範例 |
|---|---|---|
| `!` | 直接在對話中執行 shell 指令，輸出會出現在對話裡 | `! git log --oneline -5` |
| `@` | 在訊息中引用特定檔案，讓 Claude 讀取該檔案內容 | `@backend/app/main.py 這個路由是做什麼的？` |

```
# 範例：讓 Claude 看 main.py 並解釋 /analyze/tw 路由
@backend/app/main.py 請說明 /analyze/tw 這個 endpoint 的運作流程

# 範例：執行 shell 指令並在對話中看到結果
! curl http://localhost:8000/health
```

> `!` 前綴非常實用 — 當你需要執行互動式指令（如 `gcloud auth login`），輸出會直接帶入對話中，Claude 能即時看到結果。

---

## 2. Git 工作流程指令

| 指令 | 說明 |
|---|---|
| `git status` | 查看工作目錄的狀態（已修改、已暫存、未追蹤的檔案） |
| `git add <檔案>` | 將指定檔案加入暫存區 |
| `git commit -m "訊息"` | 建立一個新的 commit |
| `git push` | 將本地 commits 推送到遠端 |
| `git pull` | 從遠端拉取並合併最新變更 |
| `git fetch` | 從遠端下載最新資訊但不合併 |
| `git branch` | 列出所有本地分支；目前分支前有 `*` |
| `git checkout <分支>` | 切換到指定分支 |
| `git log` | 查看 commit 歷史 |
| `git diff` | 查看尚未暫存的變更內容 |
| `git restore <檔案>` | 捨棄工作目錄中的變更（還原到最後一次 commit 狀態） |
| `git reset HEAD <檔案>` | 將檔案從暫存區移除（但保留工作目錄的變更） |

```bash
# 查看目前狀態
git status

# 暫存特定檔案
git add backend/app/main.py
git add backend/app/models/schemas.py

# 建立 commit（推薦使用 HEREDOC 確保格式正確）
git commit -m "feat: add new Taiwan endpoint"

# 推送目前分支
git push

# 查看最近 10 筆 commit（一行格式）
git log --oneline -10

# 查看某個檔案的變更
git diff backend/app/main.py

# 建立並切換到新分支
git checkout -b feature/new-feature

# 取消暫存某個檔案
git reset HEAD backend/app/main.py

# 捨棄工作目錄的修改（危險：無法復原）
git restore backend/app/main.py
```

> ⚠️ `git restore` 和 `git reset --hard` 是不可逆操作，執行前請確認你不需要這些變更。

---

## 3. RTK 指令

**RTK（Rust Token Killer）** 是一個 CLI 代理工具，版本 `0.38.0`。它透過過濾與壓縮 shell 指令的輸出，**減少送進 Claude 的 Token 量，節省 60–90% 的 Token 消耗**。

RTK 透過 Claude Code 的 `PreToolUse` hook 自動攔截 Bash 工具呼叫，對使用者完全透明。你不需要手動加上 `rtk` 前綴，系統已自動套用。

### 直接使用 RTK 的場景

以下指令需要直接輸入 `rtk`：

| 指令 | 說明 |
|---|---|
| `rtk gain` | 顯示本次 session 節省的 Token 數與百分比統計 |
| `rtk gain --history` | 顯示過去所有指令的使用歷史與節省紀錄 |
| `rtk grep <關鍵字> <路徑>` | Token 最佳化版的 grep，過濾冗餘輸出 |
| `rtk git status` | 等同 `git status`，但輸出會被過濾精簡 |
| `rtk ls <路徑>` | 等同 `ls`，輸出精簡化 |
| `rtk proxy <指令>` | 執行原始指令而不經過 RTK 過濾（用於除錯） |

```bash
# 查看目前 session 節省了多少 Token
rtk gain

# 查看歷史節省紀錄
rtk gain --history

# Token 最佳化的 grep（和一般 grep 語法相同）
rtk grep "def get_tw" backend/app/

# 如果需要看原始未過濾的輸出
rtk proxy git log --oneline -20
```

> **RTK 如何運作：** `settings.json` 中設定了 `PreToolUse` hook，每次 Claude 呼叫 Bash 工具時，hook 會自動將指令路由到 `rtk hook claude`，進行輸出過濾後再回傳。

---

## 4. Superpowers 外掛指令

> ⚠️ **Superpowers 是需要安裝的外掛。** 目前此專案的 `docs/superpowers/` 目錄中有過去產生的 spec 與 plan 檔案，代表此工具曾被使用過。若需重新啟用，請先安裝外掛。

Superpowers 提供從「想法 → 設計規格 → 執行計畫」的完整工作流程，特別適合需要仔細規劃的新功能開發。

### 指令說明

| 指令 | 說明 | 使用時機 |
|---|---|---|
| `/brainstorm` | 以對話方式探索功能想法、架構選項與取捨 | 功能還不明確，想先發散思考時 |
| `/write-plan` | 根據 brainstorm 結果或需求描述，產生結構化的設計規格（存入 `docs/superpowers/specs/`） | 確認方向後，需要詳細的技術設計文件 |
| `/execute-plan` | 讀取設計規格，產生分步驟的實作計畫（存入 `docs/superpowers/plans/`） | 有了設計文件後，轉換成 Claude 可執行的任務清單 |
| `/review` | 針對目前分支的變更進行深度程式碼審查 | 實作完成後的品質把關 |

```
# 典型的 Superpowers 工作流程：

# 步驟 1：探索想法
/brainstorm 我想要在台股分析頁面加入法人籌碼異動警示功能

# 步驟 2：產生設計規格
/write-plan

# 步驟 3：產生實作計畫
/execute-plan

# 步驟 4：Claude 依計畫逐步實作（搭配 /speckit-implement 或直接讓 Claude 執行）
```

> **此專案的 Superpowers 產出位置：** `docs/superpowers/specs/`（設計規格）和 `docs/superpowers/plans/`（實作計畫）

---

## 5. Spec-kit 指令

> ⚠️ **Spec-kit 需要安裝 `specify` CLI。** 執行 `specify --version` 可確認是否已安裝。目前此環境尚未安裝。

Spec-kit 是一套規格驅動開發（Spec-Driven Development）工具，讓你用自然語言描述功能，自動產生可被 Claude 理解並執行的結構化規格。

### 安裝

```bash
# 全域安裝（需要 Node.js）
npm install -g specify-cli

# 確認安裝成功
specify --version
```

### 指令說明

| 指令 | 說明 |
|---|---|
| `specify version` | 顯示目前安裝的 Spec-kit 版本 |
| `specify init --here --integration claude` | 在目前目錄初始化 Spec-kit，並與 Claude Code 整合（產生 `specs/` 目錄與設定檔） |

初始化後，Claude Code 會自動載入以下斜線指令：

| 指令 | 說明 | 使用時機 |
|---|---|---|
| `/speckit-constitution` | 建立或更新專案的核心設計原則文件 | 一開始設定專案規範，之後作為所有規格的基礎 |
| `/speckit-specify` | 用對話方式將功能需求轉換成結構化規格文件 | 要開始一個新功能，需要整理清楚「要做什麼」 |
| `/speckit-plan` | 根據規格文件產生詳細的技術實作計畫 | 需求確認後，產生 Claude 可執行的步驟清單 |
| `/speckit-tasks` | 將實作計畫拆解成可追蹤的任務項目 | 把大計畫拆成小任務，逐一勾選完成 |
| `/speckit-implement` | 依照任務清單逐步實作，每個任務完成後暫停確認 | 讓 Claude 有條不紊地執行，避免一次改太多 |

### 完整工作流程（從想法到實作）

```
# 第 1 步：初始化（只需做一次）
specify init --here --integration claude

# 第 2 步：建立專案設計原則
/speckit-constitution

# 第 3 步：描述新功能
/speckit-specify 我想要在 /analyze/tw 加入法人買賣超的趨勢圖

# 第 4 步：產生技術計畫
/speckit-plan

# 第 5 步：拆解任務
/speckit-tasks

# 第 6 步：讓 Claude 逐步實作
/speckit-implement
```

> **與 Superpowers 的差異：** Superpowers 偏向探索性設計（brainstorm → design）；Spec-kit 偏向精確的規格追蹤（specify → task → implement）。兩者可搭配使用。

---

## 6. 後端 Python 指令

所有後端指令從專案根目錄執行（`/home/ben_0527/project/ai-stock`），使用根目錄的 `.venv/`。

### 虛擬環境

```bash
# 啟動虛擬環境（啟動後提示字元會出現 (.venv)）
source .venv/bin/activate

# 啟動後可直接使用 python、pip 等指令
python --version
# Python 3.14.x

# 離開虛擬環境
deactivate
```

### 套件管理

```bash
# 安裝套件（啟動 venv 後）
pip install <套件名稱>

# 安裝所有依賴（從 requirements.txt）
pip install -r backend/requirements.txt

# 查看所有已安裝套件與版本
pip freeze

# 查看特定套件資訊
pip show pydantic-ai
```

### 測試

```bash
# 執行所有後端測試
.venv/bin/python -m pytest backend/tests/ -q

# 執行單一測試檔
.venv/bin/python -m pytest backend/tests/test_tw_indicators.py -q

# 執行單一測試函式
.venv/bin/python -m pytest backend/tests/test_tw_indicators.py::test_rsi_warmup_is_none -q

# 顯示詳細輸出
.venv/bin/python -m pytest backend/tests/ -v
```

### 啟動後端伺服器

```bash
# 開發模式（檔案變更時自動重啟）
.venv/bin/uvicorn backend.app.main:app --reload --port 8000

# 或啟動 venv 後直接用 uvicorn
source .venv/bin/activate
uvicorn backend.app.main:app --reload --port 8000
```

### 測試 API

```bash
# 健康檢查
curl http://localhost:8000/health

# 台股分析（台積電）
curl "http://localhost:8000/analyze/tw?symbol=2330"

# 美股分析（Apple）
curl "http://localhost:8000/analyze?symbol=AAPL"

# 台股 K 線資料（日線，含均線與成交量）
curl "http://localhost:8000/tw/price-history?stock_code=2330&range=D&include_indicators=ma,volume"

# 台股目錄搜尋
curl "http://localhost:8000/tw/stocks?q=台積電"
```

---

## 7. 金融 Python 套件

> 以下套件均在 `.venv/` 中管理。標示 ⚠️ 的套件**目前尚未安裝**，如需使用請先執行 `pip install`。

---

### FinMind（透過 httpx 直接呼叫）

| 項目 | 說明 |
|---|---|
| **安裝** | `pip install httpx`（已安裝，`httpx==0.28.1`）|
| **用途** | 台股行情資料主要來源：K 線、法人買賣、月營收、融資融券等 |

```python
import httpx

# 此專案的 FinMind 封裝在 backend/app/services/finmind_market.py
# 基本呼叫方式（mock fallback 設計：API key 缺失時自動回傳假資料）
params = {
    "dataset": "TaiwanStockPrice",
    "data_id": "2330",
    "start_date": "2024-01-01",
    "token": "你的_FINMIND_API_KEY",  # 可省略，會用 mock data
}
async with httpx.AsyncClient() as client:
    resp = await client.get("https://api.finmindtrade.com/api/v4/data", params=params)
    data = resp.json()
```

---

### polygon-api-client ⚠️

| 項目 | 說明 |
|---|---|
| **安裝** | `pip install polygon-api-client`（**尚未安裝**）|
| **用途** | 美股即時/歷史價格資料（此專案目前透過 httpx 直接呼叫 FMP API 取得美股資料）|

```python
# 安裝後使用方式
from polygon import RESTClient

client = RESTClient(api_key="你的_POLYGON_API_KEY")
aggs = client.get_aggs("AAPL", 1, "day", "2024-01-01", "2024-12-31")
```

---

### finnhub-python

| 項目 | 說明 |
|---|---|
| **安裝** | `pip install finnhub-python`（已安裝，`finnhub-python==2.4.28`）|
| **用途** | 美股新聞來源；此專案在 `backend/app/services/` 中使用 |

```python
import finnhub

client = finnhub.Client(api_key="你的_FINNHUB_API_KEY")

# 取得公司新聞
news = client.company_news("AAPL", _from="2024-01-01", to="2024-12-31")
```

---

### financialmodelingprep ⚠️

| 項目 | 說明 |
|---|---|
| **安裝** | 無專用 Python 套件（**此專案透過 httpx 直接呼叫 FMP REST API**）|
| **用途** | 美股基本面資料、同業比較、市場概況（`backend/app/services/fmp_*.py`）|

```python
import httpx

# 此專案的呼叫方式（見 backend/app/services/fmp_fundamentals.py）
async with httpx.AsyncClient() as client:
    resp = await client.get(
        "https://financialmodelingprep.com/api/v3/profile/AAPL",
        params={"apikey": "你的_FMP_API_KEY"}
    )
    profile = resp.json()
```

---

### yfinance

| 項目 | 說明 |
|---|---|
| **安裝** | `pip install yfinance`（已安裝，`yfinance==1.3.0`）|
| **用途** | 台股總經環境快照（USD/TWD、美債、黃金、石油、S&P 500、Nasdaq）；見 `backend/app/services/tw_macro.py` |

```python
import yfinance as yf

# 取得匯率（此專案用於台股總經摘要）
usd_twd = yf.Ticker("TWD=X").fast_info["lastPrice"]

# 取得指數
sp500 = yf.Ticker("^GSPC").fast_info["lastPrice"]

# 取得歷史 K 線
hist = yf.Ticker("2330.TW").history(period="1y")
```

---

### pandas

| 項目 | 說明 |
|---|---|
| **安裝** | `pip install pandas`（已安裝，`pandas==3.0.2`）|
| **用途** | 資料清洗、時間序列處理、API 回傳資料轉換 |

```python
import pandas as pd

# 將 FinMind 回傳的 list[dict] 轉為 DataFrame
df = pd.DataFrame(api_data)
df["date"] = pd.to_datetime(df["date"])
df = df.sort_values("date")

# 此專案常見用法：轉成 dict list 再回傳給前端
candles = df.to_dict("records")
```

---

### numpy

| 項目 | 說明 |
|---|---|
| **安裝** | `pip install numpy`（已安裝，`numpy==2.4.4`）|
| **用途** | 指標數學計算（SMA、EMA、RSI、MACD）；`backend/app/services/tw_indicators.py` 使用 |

```python
import numpy as np

# 此專案指標計算方式（見 tw_indicators.py）
closes = np.array([float(c["close"]) for c in candles])
sma20 = np.convolve(closes, np.ones(20) / 20, mode="valid")
```

---

### ta ⚠️

| 項目 | 說明 |
|---|---|
| **安裝** | `pip install ta`（**尚未安裝**）|
| **用途** | 技術指標函式庫（RSI、MACD、布林通道等）；**此專案自行實作指標數學** (`tw_indicators.py`)，不依賴此套件 |

```python
# 若安裝後可這樣使用
import ta
import pandas as pd

df = pd.DataFrame(candles)
df["rsi"] = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
df["macd"] = ta.trend.MACD(df["close"]).macd()
```

---

### plotly ⚠️

| 項目 | 說明 |
|---|---|
| **安裝** | `pip install plotly`（**Python 版尚未安裝**；前端 `plotly.js` 已安裝但目前未使用）|
| **用途** | 後端圖表產生（此專案圖表全部在前端使用 `lightweight-charts` 渲染，不需要後端 plotly）|

```python
# Python 版使用方式（參考）
import plotly.graph_objects as go

fig = go.Figure(data=[go.Candlestick(
    x=[c["time"] for c in candles],
    open=[c["open"] for c in candles],
    close=[c["close"] for c in candles],
)])
fig.show()
```

---

### pydantic

| 項目 | 說明 |
|---|---|
| **安裝** | `pip install pydantic`（已安裝，`pydantic==2.13.4`）|
| **用途** | 所有 API request/response 的資料驗證與序列化；`backend/app/models/schemas.py` 是唯一 schema 來源 |

```python
from pydantic import BaseModel
from typing import Optional

# 此專案的 schema 擴充模式（新欄位必須是 Optional + nullable）
class TaiwanStockAnalysisResponse(BaseModel):
    symbol: str
    company_name: str
    current_price: float
    next_dividend: Optional[DividendEvent] = None  # Phase 2 新增
```

---

### pydantic-ai

| 項目 | 說明 |
|---|---|
| **安裝** | `pip install pydantic-ai`（已安裝，`pydantic-ai==1.91.0`）|
| **用途** | 結構化 AI 輸出；AI agent 宣告 `output_type` 並直接回傳 Pydantic model，不是自由格式文字 |

```python
from pydantic_ai import Agent
from pydantic import BaseModel

class StockAnalysis(BaseModel):
    summary: str
    trend: str
    confidence: float
    recommendation: str

# 此專案的 AI agent 模式（見 backend/app/services/tw_ai_analysis.py）
agent = Agent(
    model="google-gla:gemini-2.5-pro",
    output_type=StockAnalysis,
    system_prompt="你是一位台股分析師...",
)
result = await agent.run(user_prompt)
analysis: StockAnalysis = result.output
```

---

### langchain / langgraph

| 項目 | 說明 |
|---|---|
| **安裝** | `pip install langgraph`（已安裝，`langgraph==1.1.10`；`langchain-core==1.3.3` 為依賴項）|
| **備註** | `langchain` 主套件**未直接安裝**，此專案只使用 `langgraph` 的狀態機功能 |
| **用途** | 美股與台股分析的多步驟 pipeline（`backend/app/graphs/`）；每個 graph node 呼叫不同 service，累積 state 後輸出 |

```python
from langgraph.graph import StateGraph, END
from typing import TypedDict

class AnalysisState(TypedDict):
    symbol: str
    price_data: dict
    ai_result: dict

# 此專案 graph 結構（見 backend/app/graphs/stock_analysis_graph.py）
graph = StateGraph(AnalysisState)
graph.add_node("fetch_price", fetch_price_node)
graph.add_node("run_ai", run_ai_node)
graph.add_edge("fetch_price", "run_ai")
graph.add_edge("run_ai", END)
app = graph.compile()
```

---

### fastapi

| 項目 | 說明 |
|---|---|
| **安裝** | `pip install fastapi`（已安裝，`fastapi==0.136.1`）|
| **用途** | 所有 API 路由；`backend/app/main.py` 是唯一路由檔案 |

```python
from fastapi import FastAPI, Query

app = FastAPI(title="AI Stock API", version="3.0.0")

@app.get("/analyze/tw")
async def analyze_tw(symbol: str = Query(..., description="台股代號")):
    # ...
    return response
```

---

### uvicorn

| 項目 | 說明 |
|---|---|
| **安裝** | `pip install uvicorn`（已安裝，`uvicorn==0.46.0`）|
| **用途** | ASGI 伺服器，用來執行 FastAPI 應用程式 |

```bash
# 開發模式（自動重載）
uvicorn backend.app.main:app --reload --port 8000

# 生產模式
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --workers 4
```

---

### httpx

| 項目 | 說明 |
|---|---|
| **安裝** | `pip install httpx`（已安裝，`httpx==0.28.1`）|
| **用途** | 所有外部 API 呼叫（FinMind、FMP、Polygon 等）；支援 async/await |

```python
import httpx

# 此專案所有外部 API 呼叫都用 async httpx（mock fallback 模式）
async def fetch_finmind(dataset: str, stock_code: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(FINMIND_URL, params={...})
            return resp.json()
    except Exception:
        return MOCK_DATA  # 失敗時永遠回傳 mock，不 raise
```

---

### python-dotenv

| 項目 | 說明 |
|---|---|
| **安裝** | `pip install python-dotenv`（已安裝，`python-dotenv==1.2.2`）|
| **用途** | 在 import 時從 `backend/.env` 載入環境變數 |

```python
from dotenv import load_dotenv
import os

load_dotenv("backend/.env")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")  # 預設空字串 = mock 模式
```

---

### pydantic-settings

| 項目 | 說明 |
|---|---|
| **安裝** | `pip install pydantic-settings`（已安裝，`pydantic-settings==2.14.0`）|
| **用途** | 型別安全的環境變數設定管理 |

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    gemini_api_key: str = ""
    fmp_api_key: str = ""
    finmind_api_key: str = ""

    class Config:
        env_file = "backend/.env"

settings = Settings()
```

---

## 8. 前端指令

所有前端指令在 `ai-stock-frontend/` 目錄下執行：

```bash
cd ai-stock-frontend
```

| 指令 | 說明 |
|---|---|
| `npm install` | 安裝 `package.json` 中所有依賴套件 |
| `npm run dev` | 啟動開發伺服器（預設 port 3000，若被占用則用 3001）|
| `npm run build` | 建立生產環境 build（輸出到 `.next/`）|
| `npm run lint` | 執行 ESLint 程式碼風格檢查 |
| `npm list` | 列出所有已安裝套件與版本 |

```bash
# 安裝依賴
cd ai-stock-frontend && npm install

# 啟動開發伺服器
npm run dev
# → 開啟 http://localhost:3000

# 型別檢查（此專案無獨立 test suite，用 tsc 驗證型別正確性）
npx tsc --noEmit

# 建立生產 build（確認無錯誤）
npm run build
```

---

## 9. 前端套件

### next

| 項目 | 說明 |
|---|---|
| **版本** | `next@16.2.4` |
| **安裝** | `npm install next@16.2.4` |
| **用途** | React 全端框架；此專案使用 App Router（`app/` 目錄）、單頁架構（`app/page.tsx`）|

```tsx
// app/layout.tsx — Next.js 16 App Router 根 layout
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html><body>{children}</body></html>;
}
```

> ⚠️ Next.js 16 有 breaking change。修改路由、layout 或 config 前，請先閱讀 `node_modules/next/dist/docs/`。

---

### react

| 項目 | 說明 |
|---|---|
| **版本** | `react@19.2.4` + `react-dom@19.2.4` |
| **安裝** | `npm install react@19 react-dom@19` |
| **用途** | UI 元件基礎；此專案使用 `'use client'` directive 搭配 hooks（useState、useEffect、useRef、useCallback、useMemo）|

---

### typescript

| 項目 | 說明 |
|---|---|
| **版本** | `typescript@^5`（dev dependency）|
| **安裝** | `npm install -D typescript` |
| **用途** | 靜態型別檢查；型別定義集中在 `lib/types.ts` |

```bash
# 執行型別檢查（不產生輸出檔）
npx tsc --noEmit
```

---

### tailwindcss

| 項目 | 說明 |
|---|---|
| **版本** | `tailwindcss@^4` + `@tailwindcss/postcss@^4`（dev dependency）|
| **安裝** | `npm install -D tailwindcss @tailwindcss/postcss` |
| **用途** | Utility-first CSS；此專案使用 `dark:` variant、`zinc`/`blue`/`green`/`red` 色系 |

```tsx
// 典型用法（dark mode 支援）
<div className="rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
```

---

### lightweight-charts

| 項目 | 說明 |
|---|---|
| **版本** | `lightweight-charts@^5.2.0` |
| **安裝** | `npm install lightweight-charts` |
| **用途** | 所有 K 線圖渲染（價格、成交量、RSI、MACD 四個同步 pane）；見 `app/components/PriceHistoryChart.tsx` |

```tsx
import { createChart, CandlestickSeries } from 'lightweight-charts';

// v5 API（注意：不是舊版的 addCandlestickSeries()）
const chart = createChart(containerRef.current, { width: 800, height: 460 });
const series = chart.addSeries(CandlestickSeries, { upColor: '#22c55e' });
series.setData(candles);

// ⚠️ 不要在子圖呼叫 fitContent() — 會覆蓋 barSpacing 設定
```

---

### plotly.js

| 項目 | 說明 |
|---|---|
| **版本** | `plotly.js@^3.5.1` |
| **安裝** | `npm install plotly.js` |
| **用途** | 已安裝但**目前未使用**（所有圖表已改用 `lightweight-charts`）|

---

### react-plotly.js

| 項目 | 說明 |
|---|---|
| **版本** | `react-plotly.js@^2.6.0` |
| **安裝** | `npm install react-plotly.js` |
| **用途** | Plotly 的 React wrapper；已安裝但**目前未使用** |

---

### recharts

| 項目 | 說明 |
|---|---|
| **版本** | `recharts@^3.8.1` |
| **安裝** | `npm install recharts` |
| **用途** | React 版圖表函式庫；已安裝，可用於非 K 線圖表（如長條圖、折線圖）|

```tsx
import { BarChart, Bar, XAxis, YAxis, Tooltip } from 'recharts';

<BarChart data={revenueData} width={400} height={200}>
  <Bar dataKey="revenue" fill="#3b82f6" />
  <XAxis dataKey="month" />
  <YAxis />
  <Tooltip />
</BarChart>
```

---

### axios

| 項目 | 說明 |
|---|---|
| **版本** | `axios@^1.16.0` |
| **安裝** | `npm install axios` |
| **用途** | 前端所有 API 呼叫；封裝在 `lib/api.ts`，型別定義在 `lib/types.ts` |

```ts
// lib/api.ts 的典型呼叫方式
import axios from 'axios';

export async function analyzeTW(symbol: string) {
  const { data } = await axios.get(`${API_BASE}/analyze/tw`, {
    params: { symbol: symbol.trim() },
  });
  return data;
}
```

---

## 10. 環境變數

環境變數設定在 `backend/.env`（從 `backend/.env.example` 複製後填入）。

> ⚠️ **`.env` 絕對不可以 commit 到 git。** 此檔案已在 `.gitignore` 中，請確認不要手動 `git add backend/.env`。

### 變數說明

| 變數名稱 | 說明 | 缺少時的行為 |
|---|---|---|
| `GEMINI_API_KEY` | Google Gemini 2.5 Pro API 金鑰，用於 AI 分析（PydanticAI agent）| 回傳 mock 摘要文字 |
| `FINMIND_API_KEY` | FinMind 台股資料 API 金鑰（K 線、法人、月營收、財務等）| 回傳 mock K 線資料 |
| `FMP_API_KEY` | Financial Modeling Prep API（美股基本面、同業比較、市場概況）| 回傳 mock 資料 |
| `FINNHUB_API_KEY` | Finnhub API（美股新聞）| 回傳 mock 新聞 |
| `POLYGON_API_KEY` | Polygon.io API（美股歷史價格）| 回傳 mock 價格資料 |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token（啟用 `/tw/telegram/*` endpoints）| Telegram 功能不可用 |
| `TELEGRAM_WEB_CHAT_ID` | Telegram 聊天室 ID（用於主動推播）| Telegram 推播不可用 |

> ⚠️ **注意：** 使用者在 section 5 中要求記錄 `ANTHROPIC_API_KEY`，但此專案**已從 Anthropic 切換為 Gemini**（commit `1fc405f`）。目前使用的是 `GEMINI_API_KEY`。

### `.env.example`

```bash
# 複製此範本並填入你的 API 金鑰
cp backend/.env.example backend/.env
```

```
GEMINI_API_KEY=
POLYGON_API_KEY=
FINNHUB_API_KEY=
FMP_API_KEY=
FINMIND_API_KEY=

# Telegram Bot（選用 — 啟用 /tw/telegram/* endpoints）
TELEGRAM_BOT_TOKEN=
TELEGRAM_WEB_CHAT_ID=
```

---

## 11. 常見開發工作流程

### 啟動後端

```bash
# 方式 A：直接用 .venv 路徑（推薦，不需 source）
.venv/bin/uvicorn backend.app.main:app --reload --port 8000

# 方式 B：先啟動 venv
source .venv/bin/activate
uvicorn backend.app.main:app --reload --port 8000

# 確認後端正在運行
curl http://localhost:8000/health
# 預期: {"status": "ok", "version": "3.0.0"}
```

---

### 啟動前端

```bash
# 在另一個終端機視窗執行
cd ai-stock-frontend && npm run dev

# 開啟瀏覽器
# http://localhost:3000
# （若 3000 被占用，Next.js 會自動改用 3001）
```

---

### 執行測試

```bash
# 執行全部後端測試
.venv/bin/python -m pytest backend/tests/ -q

# 執行特定測試（開發中常用）
.venv/bin/python -m pytest backend/tests/test_tw_indicators.py -v

# 前端型別檢查
cd ai-stock-frontend && npx tsc --noEmit
```

---

### 更新 GitHub（提交與推送）

```bash
# 查看變更
git status
git diff

# 暫存特定檔案（不要用 git add -A，避免意外 commit .env）
git add backend/app/main.py
git add backend/app/models/schemas.py
git add ai-stock-frontend/app/components/NewComponent.tsx

# 建立 commit
git commit -m "feat: add new feature description"

# 推送
git push
```

---

### 在另一台電腦拉取最新版本

```bash
# 拉取最新變更
git pull

# 後端：更新依賴（若 requirements 有變動）
.venv/bin/pip install -r backend/requirements.txt

# 前端：更新套件（若 package.json 有變動）
cd ai-stock-frontend && npm install

# 重新啟動服務
.venv/bin/uvicorn backend.app.main:app --reload --port 8000
```

---

### 使用 Spec-kit 新增台股功能（推薦工作流程）

```bash
# 前提：specify CLI 已安裝且 spec-kit 已初始化
# 步驟 1：描述功能
/speckit-specify 新增台股外資持股比例趨勢圖，顯示在 /analyze/tw 頁面

# 步驟 2：產生技術計畫
/speckit-plan

# 步驟 3：拆解任務
/speckit-tasks
# → 會列出任務清單，例如：
# [ ] 在 finmind_detail.py 加入外資持股 API 呼叫
# [ ] 在 schemas.py 新增 ForeignHoldingPoint model
# [ ] 在 main.py 的 /analyze/tw 加入資料
# [ ] 在前端新增圖表元件

# 步驟 4：逐步實作
/speckit-implement
# → Claude 會一個任務一個任務完成，每步暫停讓你確認
```

---

### 讓 Claude 安全地逐步實作任務

這是讓 Claude 開發新功能而不失控的最佳實踐：

```
# 1. 先讓 Claude 列出任務清單，不要直接動手
請先列出實作「法人籌碼警示功能」的步驟清單，不要開始寫程式

# 2. 確認清單後，讓 Claude 一次只做一個任務
好，請完成第 1 個任務：在 finmind_detail.py 加入 fetch_institutional_detail()

# 3. 確認第 1 個任務完成後，繼續下一個
好，請繼續第 2 個任務

# 4. 每個任務完成後執行測試
.venv/bin/python -m pytest backend/tests/ -q
```

> **為什麼要逐步做？** 一次給 Claude 太大的任務，容易出現跨多個檔案的錯誤很難回退。每個小任務完成後立即測試，問題能快速定位。
