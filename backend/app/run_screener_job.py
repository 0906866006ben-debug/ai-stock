import sys
import os
import json
import urllib.request
from datetime import datetime, timedelta
import yfinance as yf
import pandas as pd
from pathlib import Path

# 加入專案根目錄到系統路徑
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.app.models.screener_schemas import ScreenerResponse
from backend.app.services.screener_service import evaluate_surge_candidate

def get_all_tw_tickers():
    tickers = []
    print("📥 正在從證交所與櫃買中心獲取最新股票清單...")
    try:
        req_twse = urllib.request.Request("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req_twse, timeout=10) as response:
            twse_data = json.loads(response.read().decode())
            for item in twse_data:
                if len(item['Code']) == 4:
                    tickers.append({"code": item['Code'] + '.TW', "name": item.get('Name', '')})
        
        req_tpex = urllib.request.Request("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_quotes", headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req_tpex, timeout=10) as response:
            tpex_data = json.loads(response.read().decode())
            for item in tpex_data:
                if len(item['SecuritiesCompanyCode']) == 4:
                    tickers.append({"code": item['SecuritiesCompanyCode'] + '.TWO', "name": item.get('CompanyName', '')})
            
        print(f"✅ 成功獲取 {len(tickers)} 檔股票！")
    except Exception as e:
        print(f"⚠️ 獲取股票清單失敗: {e}")
        tickers = [
            {"code": "2330.TW", "name": "台積電"},
            {"code": "2454.TW", "name": "聯發科"},
            {"code": "2317.TW", "name": "鴻海"}
        ]
    return tickers

def run_job():
    tickers = get_all_tw_tickers()
    end_date = datetime.now()
    start_date = end_date - timedelta(days=150)
    
    print(f"🔍 抓取大盤資料 (^TWII)...")
    try:
        df_market = yf.download("^TWII", start=start_date, end=end_date, progress=False)
        if isinstance(df_market.columns, pd.MultiIndex):
            df_market.columns = df_market.columns.get_level_values(0)
    except:
        df_market = pd.DataFrame()
        
    results = []
    total = len(tickers)
    
    for i, t_info in enumerate(tickers, 1):
        t, name = t_info['code'], t_info['name']
        print(f"[{i}/{total}] 正在分析 {t}...", end='\r')
        try:
            df = yf.download(t, start=start_date, end=end_date, progress=False)
            if df.empty: continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            
            res = evaluate_surge_candidate(t.replace(".TW", "").replace(".TWO", ""), name, df, df_market)
            if res: results.append(res)
        except Exception:
            pass

    print("\n✅ 分析結束！正在儲存結果...")
    results.sort(key=lambda x: x.surge_candidate_score, reverse=True)
    resp = ScreenerResponse(generated_at=datetime.now().isoformat(), universe_size=total, matched_count=len(results), parameters={"min_avg_volume_20": 500, "min_return_60d": 0.10, "max_return_60d": 0.35, "max_base_return": 0.05}, data_warnings=[], results=results)
    
    output_dir = Path(__file__).resolve().parent.parent / "screener_results"
    output_dir.mkdir(parents=True, exist_ok=True)
    out_file = output_dir / "surge_candidates.json"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(resp.model_dump_json(indent=2))
    print(f"✅ 儲存至 {out_file}，共 {len(results)} 檔符合候選。")

if __name__ == "__main__":
    run_job()