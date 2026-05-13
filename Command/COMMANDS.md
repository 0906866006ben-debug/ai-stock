# AI Stock Commands

Run these commands from the project root:

```powershell
cd "C:\Users\09068\OneDrive\文件\GitHub\ai-stock"
```

---

## Check Environment

```powershell
python --version
where.exe python
where.exe node
where.exe npm
```

Expected:

- Python is required for the backend.
- Node.js and npm are required for the frontend.
- If `node` or `npm` cannot be found, install Node.js LTS first, then reopen PowerShell.

Install Node.js LTS with winget:

```powershell
winget install OpenJS.NodeJS.LTS
```

After installation, close all PowerShell windows, open PowerShell again, then check:

```powershell
node --version
npm.cmd --version
```

If Node is installed but PowerShell still cannot find `node` or `npm`, add Node.js to PATH:

```powershell
$nodePath = "C:\Program Files\nodejs\"
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (($userPath -split ";") -notcontains $nodePath) {
  [Environment]::SetEnvironmentVariable("Path", "$userPath;$nodePath", "User")
}
$env:Path = "$env:Path;$nodePath"
node --version
npm.cmd --version
```

---

## Open Backend (FastAPI)

Create the Python virtual environment once:

```powershell
python -m venv .venv
```

Install backend dependencies once:

```powershell
.\.venv\Scripts\python.exe -m pip install fastapi uvicorn python-dotenv httpx pydantic pydantic-ai langgraph yfinance pandas numpy pytest pytest-asyncio pytest-httpx
```

Start the backend:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --port 8000
```

Backend URL:

```text
http://localhost:8000
```

Health check:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

Expected response:

```text
status version
------ -------
ok     3.0.0
```

---

## Open Frontend (Next.js)

Check Node/npm first:

```powershell
node --version
npm.cmd --version
```

If PowerShell shows `npm : The term 'npm' is not recognized`, install Node.js LTS:

```powershell
winget install OpenJS.NodeJS.LTS
```

Then close PowerShell, open it again, and run the frontend commands below.

If it is already installed but still not recognized, fix PATH in the current PowerShell:

```powershell
$nodePath = "C:\Program Files\nodejs\"
$env:Path = "$env:Path;$nodePath"
node --version
npm.cmd --version
```

If PowerShell says `npm.ps1 cannot be loaded because running scripts is disabled`, use `npm.cmd`:

```powershell
npm.cmd install
npm.cmd run dev
```

Install frontend dependencies once:

```powershell
cd ai-stock-frontend
npm.cmd install
```

Start the frontend:

```powershell
cd ai-stock-frontend
npm.cmd run dev
```

Frontend URL:

```text
http://localhost:3000
```

If you see `Another next dev server is already running`, the frontend is already open. Use the shown URL, usually:

```text
http://localhost:3000
```

To stop the existing frontend server, use the PID shown by Next.js:

```powershell
taskkill /PID 16580 /F
```

Or stop whatever is using port `3000`:

```powershell
$frontendPid = (Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue).OwningProcess
if ($frontendPid) { Stop-Process -Id $frontendPid -Force }
```

The frontend defaults to:

```text
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## Open Backend And Frontend Together

Run this from the project root after dependencies are installed. It opens two new PowerShell windows:

```powershell
Start-Process powershell -ArgumentList '-NoExit', '-Command', 'cd "C:\Users\09068\OneDrive\文件\GitHub\ai-stock"; .\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --port 8000'
Start-Process powershell -ArgumentList '-NoExit', '-Command', 'cd "C:\Users\09068\OneDrive\文件\GitHub\ai-stock\ai-stock-frontend"; npm.cmd run dev'
```

Open the app:

```text
http://localhost:3000
```

---

## Test Taiwan Stock Analysis

```powershell
Invoke-RestMethod "http://localhost:8000/analyze/tw?symbol=2330"
```

---

## Run Backend Tests

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests/ -q
```

Tested result:

```text
141 passed, 1 warning
```

---

## Run AI Stock Backtest

The backtest runner supports local CSV files first, then FinMind if `FINMIND_API_KEY`
is configured in `backend/.env`. Results are written to:

```text
backend/backtest_results/<timestamp>_v2_quant_<symbols>/
```

Each run creates:

- `backtest_results.xlsx`
- `Summary.csv`
- `Trades.csv`
- `DailySignals.csv`
- `Hypotheses.csv`
- `EquityCurve.csv`
- `Config.csv`
- `summary.json`

Run a balanced v2 backtest:

```powershell
cd "C:\Users\09068\OneDrive\文件\GitHub\ai-stock"
.\.venv\Scripts\python.exe -m backend.technical_analyzer.v1.backtest.runner `
  --symbols 2330,2454,2317 `
  --start 2023-01-01 `
  --end 2025-12-31 `
  --min-signal 60 `
  --min-confidence 45 `
  --max-risk 75
```

Run strict v2 mode, requiring RR >= 3:

```powershell
.\.venv\Scripts\python.exe -m backend.technical_analyzer.v1.backtest.runner `
  --symbols 2330,2454,2317 `
  --start 2023-01-01 `
  --end 2025-12-31 `
  --require-rr-pass
```

Use local CSV files instead of FinMind:

```powershell
.\.venv\Scripts\python.exe -m backend.technical_analyzer.v1.backtest.runner `
  --symbols 2330,2454 `
  --start 2023-01-01 `
  --end 2025-12-31 `
  --data-dir data\tw_ohlcv
```

CSV file names should be:

```text
data/tw_ohlcv/2330.csv
data/tw_ohlcv/2454.csv
```

Supported CSV columns:

```text
date, open, high, low, close, volume, turnover_value
```

FinMind-style names are also accepted:

```text
date, open, max, min, close, Trading_Volume, Trading_money
```

If you only want to test the runner without real data:

```powershell
.\.venv\Scripts\python.exe -m backend.technical_analyzer.v1.backtest.runner `
  --symbols 2330 `
  --start 2025-01-01 `
  --end 2025-12-31 `
  --allow-mock
```

---

## TypeScript Check

Requires Node/npm and frontend dependencies.

```powershell
cd ai-stock-frontend
npx.cmd tsc --noEmit
```

---

## Git Push

Check Git first:

```powershell
git --version
```

If PowerShell says `git` is not recognized, install Git, then reopen PowerShell:

```powershell
winget install Git.Git
```

Run from the project root:

```powershell
cd "C:\Users\09068\OneDrive\文件\GitHub\ai-stock"
```

Check changed files:

```powershell
git status
```

Add all safe tracked/untracked project files:

```powershell
git add -A
```

`backend/.env` is ignored by `.gitignore`, so secrets should not be committed. Still check before committing:

```powershell
git status
```

Commit:

```powershell
git commit -m "Update AI stock assistant docs and frontend"
```

Push to the current branch:

```powershell
git push
```

If this is the first push for a new branch, use:

```powershell
git push -u origin main
```

If your branch is not `main`, check the branch name:

```powershell
git branch --show-current
```

Then push it:

```powershell
$branch = git branch --show-current
git push -u origin $branch
```

---

## Stop Services

Stop by pressing `Ctrl+C` in each terminal window.

Or stop the processes using ports `8000` and `3000`:

```powershell
$backendPid = (Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue).OwningProcess
$frontendPid = (Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue).OwningProcess
$backendPid, $frontendPid | Where-Object { $_ } | ForEach-Object { Stop-Process -Id $_ }
```
