'use client';

import { useEffect, useState } from 'react';
import type { Position } from '@/lib/types';
import { getTwPriceHistory, getTwStocks } from '@/lib/api';

const SHARES_PER_LOT = 1000;
type QuantityUnit = 'lot' | 'share';

interface Props {
  onAdd: (pos: Omit<Position, 'id'>) => void;
  currentAnalyzedStock?: {
    stock_code: string;
    company_name: string;
    current_price?: number | null;
  } | null;
}

export default function AddPosition({ onAdd, currentAnalyzedStock = null }: Props) {
  const [stockCode, setStockCode] = useState('');
  const [companyName, setCompanyName] = useState('');
  const [quantity, setQuantity] = useState('1');
  const [quantityUnit, setQuantityUnit] = useState<QuantityUnit>('lot');
  const [cost, setCost] = useState('');
  const [purchaseDate, setPurchaseDate] = useState(
    new Date().toISOString().slice(0, 10)
  );
  const [error, setError] = useState('');
  const [companyLookupState, setCompanyLookupState] = useState<'idle' | 'loading' | 'found' | 'not-found'>('idle');
  const [companyNameTouched, setCompanyNameTouched] = useState(false);
  const [quickBuying, setQuickBuying] = useState(false);

  useEffect(() => {
    const code = stockCode.trim();
    let cancelled = false;

    const updateLookup = (next: typeof companyLookupState, nextName?: string) => {
      queueMicrotask(() => {
        if (cancelled) return;
        setCompanyLookupState(next);
        if (nextName && (!companyNameTouched || !companyName.trim())) {
          setCompanyName(nextName);
        }
      });
    };

    if (!/^\d{4,6}$/.test(code)) {
      updateLookup('idle');
      return () => {
        cancelled = true;
      };
    }

    if (currentAnalyzedStock && currentAnalyzedStock.stock_code === code) {
      updateLookup('found', currentAnalyzedStock.company_name);
      return () => {
        cancelled = true;
      };
    }

    updateLookup('loading');

    const timer = setTimeout(async () => {
      try {
        const data = await getTwStocks({ q: code, limit: 10 });
        if (cancelled) return;

        const exactMatch = data.stocks.find((stock) => stock.stock_code === code);
        if (!exactMatch) {
          setCompanyLookupState('not-found');
          return;
        }

        setCompanyLookupState('found');
        if (!companyNameTouched || !companyName.trim()) {
          setCompanyName(exactMatch.company_name);
        }
      } catch {
        if (!cancelled) setCompanyLookupState('not-found');
      }
    }, 250);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [stockCode, companyNameTouched, companyName, currentAnalyzedStock]);

  async function resolveCompanyName(code: string): Promise<string> {
    if (!/^\d{4,6}$/.test(code)) return '';
    if (currentAnalyzedStock && currentAnalyzedStock.stock_code === code) {
      return currentAnalyzedStock.company_name;
    }
    try {
      const data = await getTwStocks({ q: code, limit: 10 });
      const exactMatch = data.stocks.find((stock) => stock.stock_code === code);
      return exactMatch?.company_name ?? '';
    } catch {
      return '';
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');

    const code = stockCode.trim();
    const quantityNum = parseFloat(quantity);
    const costNum = parseFloat(cost);
    let finalCompanyName = companyName.trim();
    const lotsNum = quantityUnit === 'share'
      ? quantityNum / SHARES_PER_LOT
      : quantityNum;

    if (!code) return setError('請輸入股票代碼');
    if (!quantityNum || quantityNum <= 0) {
      return setError(quantityUnit === 'share' ? '股數必須大於 0' : '張數必須大於 0');
    }
    if (!costNum || costNum <= 0) return setError('成本價必須大於 0');
    if (!finalCompanyName) {
      finalCompanyName = await resolveCompanyName(code);
      if (finalCompanyName) {
        setCompanyName(finalCompanyName);
        setCompanyLookupState('found');
      }
    }

    onAdd({
      stock_code: code,
      company_name: finalCompanyName || code,
      lots: lotsNum,
      cost_per_share: costNum,
      purchase_date: purchaseDate,
    });

    // Reset
    setStockCode('');
    setCompanyName('');
    setQuantity('1');
    setQuantityUnit('lot');
    setCost('');
    setCompanyNameTouched(false);
    setCompanyLookupState('idle');
  }

  // 快速購入：成本價自動帶最近收盤價（免手填），其餘驗證同一般送出
  async function handleQuickBuy() {
    setError('');
    const code = stockCode.trim();
    const quantityNum = parseFloat(quantity);
    const lotsNum = quantityUnit === 'share' ? quantityNum / SHARES_PER_LOT : quantityNum;

    if (!code) return setError('請輸入股票代碼');
    if (!quantityNum || quantityNum <= 0) {
      return setError(quantityUnit === 'share' ? '股數必須大於 0' : '張數必須大於 0');
    }

    setQuickBuying(true);
    try {
      // 先用畫面上已載入的即時價（分析中的個股）——避免冷啟動時的第二次網路請求失敗。
      let price: number | null = null;
      if (currentAnalyzedStock && currentAnalyzedStock.stock_code === code && currentAnalyzedStock.current_price) {
        price = currentAnalyzedStock.current_price;
      } else {
        const history = await getTwPriceHistory(code, 'D');
        const last = history.candles?.[history.candles.length - 1];
        if (last && last.close && !history.is_mock) price = last.close;
      }
      if (!price) {
        return setError('抓不到最近價格（後端喚醒中或代碼有誤），請稍候再試或手動輸入成本價');
      }
      setCost(String(price));
      const finalCompanyName = companyName.trim() || (await resolveCompanyName(code));

      onAdd({
        stock_code: code,
        company_name: finalCompanyName || code,
        lots: lotsNum,
        cost_per_share: price,
        purchase_date: new Date().toISOString().slice(0, 10),
      });

      setStockCode('');
      setCompanyName('');
      setQuantity('1');
      setQuantityUnit('lot');
      setCost('');
      setCompanyNameTouched(false);
      setCompanyLookupState('idle');
    } catch {
      setError('抓不到最近價格（代碼有誤或資料源暫時不可用），請手動輸入成本價');
    } finally {
      setQuickBuying(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className="mb-1 block text-xs font-medium text-zinc-600 dark:text-zinc-400">
            股票代碼 *
          </label>
          <input
            type="text"
            value={stockCode}
            onChange={(e) => {
              setStockCode(e.target.value);
              setCompanyNameTouched(false);
              setError('');
            }}
            placeholder="例如：2330"
            className="w-full rounded-2xl border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-pink-400 focus:ring-2 focus:ring-pink-200 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-zinc-600 dark:text-zinc-400">
            公司名稱
          </label>
          <input
            type="text"
            value={companyName}
            onChange={(e) => {
              setCompanyName(e.target.value);
              setCompanyNameTouched(true);
            }}
            placeholder="不輸入會依股票代碼自動帶入"
            className="w-full rounded-2xl border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-pink-400 focus:ring-2 focus:ring-pink-200 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
          />
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            {companyLookupState === 'loading' && '正在查詢公司名稱...'}
            {companyLookupState === 'found' && '已自動帶入公司名稱'}
            {companyLookupState === 'not-found' && '查不到對應公司名稱，仍可手動輸入'}
            {companyLookupState === 'idle' && '輸入台股代碼後會自動抓公司名稱'}
          </p>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-zinc-600 dark:text-zinc-400">
            數量 * (1張 = {SHARES_PER_LOT} 股)
          </label>
          <div className="flex gap-2">
            <input
              type="number"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              placeholder={quantityUnit === 'lot' ? '例如：1' : '例如：1000'}
              min={quantityUnit === 'lot' ? '0.001' : '1'}
              step={quantityUnit === 'lot' ? '0.001' : '1'}
              className="min-w-0 flex-1 rounded-2xl border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-pink-400 focus:ring-2 focus:ring-pink-200 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
            />
            <select
              value={quantityUnit}
              onChange={(e) => setQuantityUnit(e.target.value as QuantityUnit)}
              className="w-24 rounded-2xl border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-pink-400 focus:ring-2 focus:ring-pink-200 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
            >
              <option value="lot">張</option>
              <option value="share">股</option>
            </select>
          </div>
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            目前輸入為 {quantityUnit === 'lot' ? '張數' : '股數'}，送出時會自動換算。
          </p>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-zinc-600 dark:text-zinc-400">
            成本價（每股）*
          </label>
          <input
            type="number"
            value={cost}
            onChange={(e) => setCost(e.target.value)}
            placeholder="例如：950"
            min="0.01"
            step="0.01"
            className="w-full rounded-2xl border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-pink-400 focus:ring-2 focus:ring-pink-200 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-zinc-600 dark:text-zinc-400">
            購入日期
          </label>
          <input
            type="date"
            value={purchaseDate}
            onChange={(e) => setPurchaseDate(e.target.value)}
            className="w-full rounded-2xl border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-pink-400 focus:ring-2 focus:ring-pink-200 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100"
          />
        </div>
      </div>

      {error && (
        <p className="text-sm text-red-500">{error}</p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="submit"
          className="rounded-full bg-gradient-to-r from-pink-500 to-rose-500 px-6 py-2 text-sm font-semibold text-white shadow-md hover:from-pink-600 hover:to-rose-600 active:from-pink-700 active:to-rose-700 transition-all"
        >
          💖 加入寶貝清單
        </button>
        <button
          type="button"
          onClick={handleQuickBuy}
          disabled={quickBuying}
          title="成本價自動帶入最近收盤價、日期帶今天，其餘欄位照上方輸入"
          className="rounded-full bg-gradient-to-r from-amber-400 to-orange-500 px-6 py-2 text-sm font-semibold text-white shadow-md transition-all hover:from-amber-500 hover:to-orange-600 active:from-amber-600 active:to-orange-700 disabled:cursor-wait disabled:opacity-60"
        >
          {quickBuying ? '⏳ 抓價格中…' : '⚡ 快速購入（最近價格）'}
        </button>
      </div>
    </form>
  );
}
