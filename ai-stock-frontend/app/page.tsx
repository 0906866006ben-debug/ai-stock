'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import {
  analyzeStock, analyzeTW, getCompetitors, getTwPriceHistory, syncTelegramWatchlist,
  StockAnalysisResponse,
} from '@/lib/api';
import {
  TaiwanStockAnalysisResponse, CompetitorResponse, Position,
} from '@/lib/types';

import TwSearchBar from './components/TwSearchBar';
import AnalysisCard from './components/AnalysisCard';
import StockChart from './components/StockChart';
import NewsSection from './components/NewsSection';
import FinancialSummary from './components/FinancialSummary';
import TwFinancialSummary from './components/TwFinancialSummary';
import FundamentalsCard from './components/FundamentalsCard';
import CompetitorCard from './components/CompetitorCard';
import MarketOverview from './components/MarketOverview';
import TwDetailedAnalysis from './components/TwDetailedAnalysis';
import PriceHistoryChart from './components/PriceHistoryChart';
import StockDirectory from './components/StockDirectory';
import ExternalNews from './components/ExternalNews';
import PortfolioDashboard from './components/PortfolioDashboard';
import AllocationCalculator from './components/AllocationCalculator';
import Watchlist from './components/Watchlist';
import AddPosition from './components/AddPosition';
import DividendCalendar from './components/DividendCalendar';
import EarningsCalendar from './components/EarningsCalendar';
import ETFHoldingsCard from './components/ETFHoldingsCard';
import { AIAnalysisPage } from './components/ai-analysis/AIAnalysisPage';
import EntryContextCard from './components/EntryContextCard';
import BoldPlanView from './components/BoldPlanView';
import MarketHeatmapView from './components/MarketHeatmapView';
import DailyOpportunitiesView from './components/DailyOpportunitiesView';
import BacktestDashboardView from './components/BacktestDashboardView';

type Page = 'analysis' | 'stock-analysis' | 'portfolio' | 'directory' | 'news' | 'calendar' | 'watchlist' | 'add-position' | 'bold-plan' | 'market-heatmap' | 'opportunities' | 'backtest-dashboard';
const TW_RE = /^\d{4,6}$/;
const STORAGE_POSITIONS = 'stockAssistant.positions';
const STORAGE_SIM_POSITIONS = 'stockAssistant.simPositions';
const STORAGE_FAVORITES = 'stockAssistant.favorites';
const STORAGE_RECENTS = 'stockAssistant.recents';

interface FavoriteItem { code: string; name: string }

function initialPageFromUrl(): Page {
  if (typeof window === 'undefined') return 'analysis';
  const requestedPage = new URLSearchParams(window.location.search).get('page');
  return NAV.some((item) => item.page === requestedPage) ? requestedPage as Page : 'analysis';
}

// ── Sidebar nav ────────────────────────────────────────────────────────────────

const NAV: { page: Page; label: string; icon: string }[] = [
  { page: 'analysis', label: '小幫手分析', icon: '🔮' },
  { page: 'opportunities', label: '每日交易機會', icon: '🎯' },
  { page: 'stock-analysis', label: '看看走勢', icon: '📈' },
  { page: 'portfolio', label: '我的小金庫', icon: '💖' },
  { page: 'directory', label: '股票目錄', icon: '📋' },
  { page: 'news', label: '今日新聞', icon: '📰' },
  { page: 'calendar', label: '小日曆', icon: '📅' },
  { page: 'watchlist', label: '私心清單', icon: '⭐' },
  { page: 'add-position', label: '加新寶貝', icon: '🌷' },
  { page: 'bold-plan', label: '大膽的計畫', icon: '🧪' },
  { page: 'market-heatmap', label: '板塊熱力圖', icon: '🗺️' },
  { page: 'backtest-dashboard', label: '回測儀表板', icon: '📊' },
];

function Sidebar({
  current,
  onChange,
  sidebarOpen,
  onClose,
}: {
  current: Page;
  onChange: (p: Page) => void;
  sidebarOpen: boolean;
  onClose: () => void;
}) {
  return (
    <>
      {/* Backdrop for mobile */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-20 bg-black/40 lg:hidden"
          onClick={onClose}
        />
      )}
      <aside
        className={`fixed inset-y-0 left-0 z-30 w-56 transform bg-gradient-to-b from-pink-50 to-purple-50 shadow-lg transition-transform dark:from-pink-950/30 dark:to-purple-950/30 lg:static lg:translate-x-0 lg:shadow-none ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="border-b border-pink-200 p-4 dark:border-pink-900/50">
          <p className="text-sm font-bold bg-gradient-to-r from-pink-500 via-rose-500 to-purple-500 bg-clip-text text-transparent animate-gradient-shift">
            🌸 寶貝的股票小幫手 ♡
          </p>
        </div>
        <nav className="p-2">
          {NAV.map(({ page, label, icon }) => (
            <button
              key={page}
              onClick={() => { onChange(page); onClose(); }}
              className={`flex w-full items-center gap-3 rounded-2xl px-3 py-2.5 text-sm font-medium transition-all duration-300 hover:translate-x-1 ${
                current === page
                  ? 'bg-gradient-to-r from-pink-200/80 to-purple-200/60 text-pink-800 shadow-sm dark:from-pink-900/40 dark:to-purple-900/40 dark:text-pink-200'
                  : 'text-zinc-600 hover:bg-pink-100/60 dark:text-zinc-300 dark:hover:bg-pink-950/30'
              }`}
            >
              <span className="text-base">{icon}</span>
              {label}
            </button>
          ))}
        </nav>
      </aside>
    </>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const [page, setPage] = useState<Page>(initialPageFromUrl);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  // Analysis state
  const [usResult, setUsResult] = useState<StockAnalysisResponse | null>(null);
  const [twResult, setTwResult] = useState<TaiwanStockAnalysisResponse | null>(null);
  const [competitors, setCompetitors] = useState<CompetitorResponse | null>(null);
  const [peersLoading, setPeersLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Portfolio
  const [positions, setPositions] = useState<Position[]>([]);
  const [priceRefreshing, setPriceRefreshing] = useState(false);
  const [priceRefreshError, setPriceRefreshError] = useState<string | null>(null);
  const positionsRef = useRef<Position[]>([]);
  const portfolioRefreshSeq = useRef(0);

  // Simulated portfolio (paper trading)
  const [simPositions, setSimPositions] = useState<Position[]>([]);
  const [simPriceRefreshing, setSimPriceRefreshing] = useState(false);
  const [simPriceRefreshError, setSimPriceRefreshError] = useState<string | null>(null);
  const simPositionsRef = useRef<Position[]>([]);
  const simPortfolioRefreshSeq = useRef(0);
  const [addTarget, setAddTarget] = useState<'real' | 'sim'>('real');
  const [floatingSimAddOpen, setFloatingSimAddOpen] = useState(false);
  const [quickBuyFlash, setQuickBuyFlash] = useState(false);

  // Watchlist / recents
  const [favorites, setFavorites] = useState<FavoriteItem[]>([]);
  const [recents, setRecents] = useState<FavoriteItem[]>([]);

  function savePositions(next: Position[]) {
    positionsRef.current = next;
    setPositions(next);
    localStorage.setItem(STORAGE_POSITIONS, JSON.stringify(next));
  }

  function saveSimPositions(next: Position[]) {
    simPositionsRef.current = next;
    setSimPositions(next);
    localStorage.setItem(STORAGE_SIM_POSITIONS, JSON.stringify(next));
  }

  function saveFavorites(next: FavoriteItem[]) {
    setFavorites(next);
    localStorage.setItem(STORAGE_FAVORITES, JSON.stringify(next));
  }

  function saveRecents(next: FavoriteItem[]) {
    setRecents(next);
    localStorage.setItem(STORAGE_RECENTS, JSON.stringify(next));
  }

  const refreshPortfolioPrices = useCallback(async (sourcePositions?: Position[]) => {
    const basePositions = sourcePositions ?? positionsRef.current;
    const codes = Array.from(
      new Set(
        basePositions
          .map((p) => p.stock_code.trim())
          .filter((code) => TW_RE.test(code))
      )
    );

    if (codes.length === 0) return;

    const seq = portfolioRefreshSeq.current + 1;
    portfolioRefreshSeq.current = seq;
    setPriceRefreshing(true);
    setPriceRefreshError(null);

    try {
      const results = await Promise.allSettled(
        codes.map(async (code) => {
          const history = await getTwPriceHistory(code, 'D');
          const latest = history.candles.at(-1);
          if (!latest || typeof latest.close !== 'number') return null;
          return [code, latest.close] as const;
        })
      );

      if (portfolioRefreshSeq.current !== seq) return;

      const priceMap = new Map<string, number>();
      let failed = 0;
      results.forEach((result) => {
        if (result.status === 'fulfilled' && result.value) {
          priceMap.set(result.value[0], result.value[1]);
        } else {
          failed += 1;
        }
      });

      if (priceMap.size > 0) {
        const updatedAt = new Date().toISOString();
        setPositions((prev) => {
          const next = prev.map((pos) => {
            const price = priceMap.get(pos.stock_code.trim());
            return price == null
              ? pos
              : { ...pos, current_price: price, current_price_updated_at: updatedAt };
          });
          positionsRef.current = next;
          localStorage.setItem(STORAGE_POSITIONS, JSON.stringify(next));
          return next;
        });
      }

      if (failed > 0) {
        setPriceRefreshError(`有 ${failed} 檔現價暫時無法更新`);
      }
    } catch {
      if (portfolioRefreshSeq.current === seq) {
        setPriceRefreshError('現價更新失敗');
      }
    } finally {
      if (portfolioRefreshSeq.current === seq) {
        setPriceRefreshing(false);
      }
    }
  }, []);

  const refreshSimPortfolioPrices = useCallback(async (sourcePositions?: Position[]) => {
    const basePositions = sourcePositions ?? simPositionsRef.current;
    const codes = Array.from(
      new Set(
        basePositions
          .map((p) => p.stock_code.trim())
          .filter((code) => TW_RE.test(code))
      )
    );

    if (codes.length === 0) return;

    const seq = simPortfolioRefreshSeq.current + 1;
    simPortfolioRefreshSeq.current = seq;
    setSimPriceRefreshing(true);
    setSimPriceRefreshError(null);

    try {
      const results = await Promise.allSettled(
        codes.map(async (code) => {
          const history = await getTwPriceHistory(code, 'D');
          const latest = history.candles.at(-1);
          if (!latest || typeof latest.close !== 'number') return null;
          return [code, latest.close] as const;
        })
      );

      if (simPortfolioRefreshSeq.current !== seq) return;

      const priceMap = new Map<string, number>();
      let failed = 0;
      results.forEach((result) => {
        if (result.status === 'fulfilled' && result.value) {
          priceMap.set(result.value[0], result.value[1]);
        } else {
          failed += 1;
        }
      });

      if (priceMap.size > 0) {
        const updatedAt = new Date().toISOString();
        setSimPositions((prev) => {
          const next = prev.map((pos) => {
            const price = priceMap.get(pos.stock_code.trim());
            return price == null
              ? pos
              : { ...pos, current_price: price, current_price_updated_at: updatedAt };
          });
          simPositionsRef.current = next;
          localStorage.setItem(STORAGE_SIM_POSITIONS, JSON.stringify(next));
          return next;
        });
      }

      if (failed > 0) {
        setSimPriceRefreshError(`有 ${failed} 檔現價暫時無法更新`);
      }
    } catch {
      if (simPortfolioRefreshSeq.current === seq) {
        setSimPriceRefreshError('現價更新失敗');
      }
    } finally {
      if (simPortfolioRefreshSeq.current === seq) {
        setSimPriceRefreshing(false);
      }
    }
  }, []);

  // Load persisted state
  useEffect(() => {
    let loadedPositions: Position[] = [];
    let loadedSimPositions: Position[] = [];
    let loadedFavorites: FavoriteItem[] | null = null;
    let loadedRecents: FavoriteItem[] | null = null;
    try {
      const p = localStorage.getItem(STORAGE_POSITIONS);
      if (p) {
        loadedPositions = JSON.parse(p);
        positionsRef.current = loadedPositions;
      }
    } catch { /* empty */ }
    try {
      const sp = localStorage.getItem(STORAGE_SIM_POSITIONS);
      if (sp) {
        loadedSimPositions = JSON.parse(sp);
        simPositionsRef.current = loadedSimPositions;
      }
    } catch { /* empty */ }
    try {
      const f = localStorage.getItem(STORAGE_FAVORITES);
      if (f) loadedFavorites = JSON.parse(f);
    } catch { /* empty */ }
    try {
      const r = localStorage.getItem(STORAGE_RECENTS);
      if (r) loadedRecents = JSON.parse(r);
    } catch { /* empty */ }

    queueMicrotask(() => {
      if (loadedPositions.length > 0) setPositions(loadedPositions);
      if (loadedSimPositions.length > 0) setSimPositions(loadedSimPositions);
      if (loadedFavorites) setFavorites(loadedFavorites);
      if (loadedRecents) setRecents(loadedRecents);
    });

    if (loadedPositions.length > 0) {
      refreshPortfolioPrices(loadedPositions);
    }
    if (loadedSimPositions.length > 0) {
      refreshSimPortfolioPrices(loadedSimPositions);
    }
  }, [refreshPortfolioPrices, refreshSimPortfolioPrices]);

  useEffect(() => {
    if (page === 'portfolio') {
      if (positionsRef.current.length > 0) refreshPortfolioPrices();
      if (simPositionsRef.current.length > 0) refreshSimPortfolioPrices();
    }
  }, [page, refreshPortfolioPrices, refreshSimPortfolioPrices]);

  // Analysis
  const handleSearch = useCallback(async (symbol: string) => {
    setLoading(true);
    setError(null);
    setCompetitors(null);

    // Track recent
    const item = { code: symbol, name: symbol };
    saveRecents([item, ...recents.filter((r) => r.code !== symbol)].slice(0, 20));

    try {
      if (TW_RE.test(symbol)) {
        const data = await analyzeTW(symbol);
        setTwResult(data);
        setUsResult(null);
        // Update current price in portfolio
        setPositions((prev) => {
          const updatedAt = new Date().toISOString();
          const next = prev.map((p) =>
            p.stock_code === symbol
              ? { ...p, current_price: data.current_price, current_price_updated_at: updatedAt }
              : p
          );
          positionsRef.current = next;
          localStorage.setItem(STORAGE_POSITIONS, JSON.stringify(next));
          return next;
        });
        setSimPositions((prev) => {
          const updatedAt = new Date().toISOString();
          const next = prev.map((p) =>
            p.stock_code === symbol
              ? { ...p, current_price: data.current_price, current_price_updated_at: updatedAt }
              : p
          );
          simPositionsRef.current = next;
          localStorage.setItem(STORAGE_SIM_POSITIONS, JSON.stringify(next));
          return next;
        });
      } else {
        const data = await analyzeStock(symbol);
        setUsResult(data);
        setTwResult(null);
        setPeersLoading(true);
        getCompetitors(symbol)
          .then(setCompetitors)
          .catch(() => null)
          .finally(() => setPeersLoading(false));
      }
    } catch (err: unknown) {
      const msg =
        err && typeof err === 'object' && 'message' in err
          ? String((err as { message: unknown }).message)
          : '查詢失敗，請稍後再試。';
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, [recents]);

  // Navigate to analysis and pre-fill symbol
  function goAnalyze(code: string, name: string) {
    setPage('stock-analysis');
    handleSearch(code);
    // Also update recent name if we have it
    saveRecents([{ code, name }, ...recents.filter((r) => r.code !== code)].slice(0, 20));
  }

  // Favorites management
  const favCodes = favorites.map((f) => f.code);

  function toggleFavorite(code: string, name: string) {
    if (favCodes.includes(code)) {
      saveFavorites(favorites.filter((f) => f.code !== code));
      syncTelegramWatchlist('remove', code).catch(() => null);
    } else {
      saveFavorites([...favorites, { code, name }]);
      syncTelegramWatchlist('add', code, name).catch(() => null);
    }
  }

  function addFavorite(code: string, name: string) {
    if (favCodes.includes(code)) return;
    saveFavorites([...favorites, { code, name }]);
    syncTelegramWatchlist('add', code, name).catch(() => null);
  }

  // Portfolio management
  function addPosition(pos: Omit<Position, 'id'>) {
    const newPos: Position = { ...pos, id: `${Date.now()}-${Math.random()}` };
    if (addTarget === 'sim') {
      const next = [...simPositionsRef.current, newPos];
      saveSimPositions(next);
      refreshSimPortfolioPrices(next);
    } else {
      const next = [...positionsRef.current, newPos];
      savePositions(next);
      refreshPortfolioPrices(next);
    }
    setPage('portfolio');
  }

  function deletePosition(id: string) {
    savePositions(positionsRef.current.filter((p) => p.id !== id));
  }

  function deleteSimPosition(id: string) {
    saveSimPositions(simPositionsRef.current.filter((p) => p.id !== id));
  }

  const latestTwCandle = twResult?.chart_data?.[twResult.chart_data.length - 1] ?? null;
  const currentAnalyzedStock = twResult
    ? { stock_code: twResult.symbol, company_name: twResult.company_name }
    : usResult
      ? { stock_code: usResult.symbol, company_name: usResult.company_name }
      : null;
  const quickBuyPrice: number | null =
    twResult?.current_price ?? latestTwCandle?.close ?? usResult?.current_price ?? null;

  // 一鍵以最近價格加 1 張到練習持倉（不動真實小金庫）
  function quickBuySim() {
    if (!currentAnalyzedStock || quickBuyPrice == null) return;
    const newPos: Position = {
      id: `${Date.now()}-${Math.random()}`,
      stock_code: currentAnalyzedStock.stock_code,
      company_name: currentAnalyzedStock.company_name,
      lots: 1,
      cost_per_share: quickBuyPrice,
      purchase_date: new Date().toISOString().slice(0, 10),
    };
    const next = [...simPositionsRef.current, newPos];
    saveSimPositions(next);
    refreshSimPortfolioPrices(next);
    setQuickBuyFlash(true);
    setTimeout(() => setQuickBuyFlash(false), 1600);
  }

  return (
    <div className="flex min-h-screen bg-gradient-to-br from-pink-50 via-white to-purple-50 dark:from-pink-950/20 dark:via-zinc-950 dark:to-purple-950/20">
      <Sidebar
        current={page}
        onChange={setPage}
        sidebarOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />

      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Top bar */}
        <header className="border-b border-pink-200 bg-white/80 backdrop-blur-sm dark:border-pink-900/40 dark:bg-zinc-900/80">
          <div className="flex items-center gap-3 px-4 py-3">
            <button
              className="rounded-2xl p-1.5 text-pink-500 hover:bg-pink-100 dark:hover:bg-pink-950/40 lg:hidden"
              onClick={() => setSidebarOpen(true)}
              aria-label="Open navigation"
            >
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
            <h1 className="text-base font-bold bg-gradient-to-r from-pink-600 via-rose-500 to-purple-600 bg-clip-text text-transparent">
              <span className="inline-block animate-sparkle mr-1">✨</span>
              {NAV.find((n) => n.page === page)?.label ?? 'AI 股票分析'}
            </h1>
          </div>
        </header>

        {/* Main content */}
        <main className="relative flex-1 overflow-y-auto px-4 py-6">
          {/* Decorative floating sparkles in background */}
          <div className="pointer-events-none absolute inset-0 overflow-hidden">
            <span className="absolute top-[10%] left-[8%] text-3xl opacity-20 animate-float-soft" style={{ animationDelay: '0s' }}>🌸</span>
            <span className="absolute top-[25%] right-[6%] text-2xl opacity-20 animate-float-soft" style={{ animationDelay: '1.2s' }}>✨</span>
            <span className="absolute top-[55%] left-[4%] text-2xl opacity-15 animate-float-soft" style={{ animationDelay: '0.6s' }}>💗</span>
            <span className="absolute top-[70%] right-[10%] text-3xl opacity-15 animate-float-soft" style={{ animationDelay: '2s' }}>🌷</span>
            <span className="absolute top-[88%] left-[15%] text-xl opacity-15 animate-float-soft" style={{ animationDelay: '1.5s' }}>♡</span>
          </div>
          <div key={page} className="relative mx-auto max-w-6xl space-y-6 animate-fade-in-up">

            {/* ── Stock / AI analysis ── */}
            {(page === 'analysis' || page === 'stock-analysis') && (
              <>
                <MarketOverview />
                <TwSearchBar onSearch={handleSearch} loading={loading} />

                {error && (
                  <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
                    {error}
                  </div>
                )}

                {loading && (
                  <div className="flex justify-center py-12">
                    <div className="h-8 w-8 animate-spin rounded-full border-4 border-blue-500 border-t-transparent" />
                  </div>
                )}

                {/* Taiwan results */}
                {twResult && !loading && (
                  <>
                    {/* Next dividend banner */}
                    {page === 'stock-analysis' && twResult.next_dividend && (
                      <div className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm dark:border-amber-900 dark:bg-amber-950/40">
                        <div className="flex items-center justify-between">
                          <span className="font-medium text-amber-800 dark:text-amber-200">
                            💰 即將除息
                          </span>
                          <span className="text-xs text-amber-700 dark:text-amber-300">
                            除息日：{twResult.next_dividend.ex_date}
                          </span>
                        </div>
                        <div className="mt-1 text-xs text-amber-700 dark:text-amber-300">
                          {twResult.next_dividend.cash_per_share != null && twResult.next_dividend.cash_per_share > 0 && (
                            <span>現金股利 {twResult.next_dividend.cash_per_share.toFixed(2)} 元</span>
                          )}
                          {twResult.next_dividend.stock_per_share != null && twResult.next_dividend.stock_per_share > 0 && (
                            <span className="ml-2">股票股利 {twResult.next_dividend.stock_per_share.toFixed(2)} 元</span>
                          )}
                          {twResult.next_dividend.payment_date && (
                            <span className="ml-2">· 發放日 {twResult.next_dividend.payment_date}</span>
                          )}
                        </div>
                      </div>
                    )}

                    {page === 'stock-analysis' && (
                      <div className="space-y-6">
                        <section className="space-y-4">
                          <div>
                            <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                              Fundamental
                            </p>
                            <h2 className="mt-1 text-lg font-semibold text-zinc-900 dark:text-zinc-50">
                              基本面
                            </h2>
                          </div>
                          <div className="grid grid-cols-1 gap-3 rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900 sm:grid-cols-3">
                            <div>
                              <p className="text-xs text-zinc-500 dark:text-zinc-400">股票編號</p>
                              <p className="mt-1 text-lg font-semibold text-zinc-900 dark:text-zinc-50">
                                {twResult.symbol}
                              </p>
                            </div>
                            <div>
                              <p className="text-xs text-zinc-500 dark:text-zinc-400">名稱</p>
                              <p className="mt-1 text-lg font-semibold text-zinc-900 dark:text-zinc-50">
                                {twResult.company_name}
                              </p>
                            </div>
                            <div>
                              <p className="text-xs text-zinc-500 dark:text-zinc-400">分類</p>
                              <p className="mt-1 text-lg font-semibold text-zinc-900 dark:text-zinc-50">
                                {twResult.is_etf ? 'ETF' : twResult.market_type}
                              </p>
                            </div>
                          </div>
                          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(280px,360px)]">
                            <div className="rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800 dark:bg-zinc-900">
                              <h3 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
                                最新價格資料
                              </h3>
                              {latestTwCandle ? (
                                <div className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-5">
                                  <div>
                                    <p className="text-xs text-zinc-500 dark:text-zinc-400">日期</p>
                                    <p className="mt-1 font-semibold text-zinc-800 dark:text-zinc-200">{latestTwCandle.time}</p>
                                  </div>
                                  <div>
                                    <p className="text-xs text-zinc-500 dark:text-zinc-400">開盤</p>
                                    <p className="mt-1 font-semibold text-zinc-800 dark:text-zinc-200">{latestTwCandle.open.toFixed(2)}</p>
                                  </div>
                                  <div>
                                    <p className="text-xs text-zinc-500 dark:text-zinc-400">收盤</p>
                                    <p className="mt-1 font-semibold text-zinc-800 dark:text-zinc-200">{latestTwCandle.close.toFixed(2)}</p>
                                  </div>
                                  <div>
                                    <p className="text-xs text-zinc-500 dark:text-zinc-400">最高 / 最低</p>
                                    <p className="mt-1 font-semibold text-zinc-800 dark:text-zinc-200">
                                      {latestTwCandle.high.toFixed(2)} / {latestTwCandle.low.toFixed(2)}
                                    </p>
                                  </div>
                                  <div>
                                    <p className="text-xs text-zinc-500 dark:text-zinc-400">成交量</p>
                                    <p className="mt-1 font-semibold text-zinc-800 dark:text-zinc-200">
                                      {latestTwCandle.volume.toLocaleString()}
                                    </p>
                                  </div>
                                </div>
                              ) : (
                                <p className="mt-3 text-sm text-zinc-400 dark:text-zinc-500">暫無價格資料</p>
                              )}
                            </div>
                            <TwFinancialSummary
                              currency={twResult.currency}
                              market_type={twResult.market_type}
                              current_price={twResult.current_price}
                              price_change_percent={twResult.price_change_percent}
                              volume={twResult.volume}
                            />
                          </div>
                          <TwDetailedAnalysis
                            revenue_summary={twResult.revenue_summary}
                            valuation_summary={twResult.valuation_summary}
                          />
                          {twResult.is_etf && twResult.etf_holdings && (
                            <ETFHoldingsCard data={twResult.etf_holdings} />
                          )}
                        </section>

                        {!twResult.is_etf && (
                          <section className="space-y-4">
                            <div>
                              <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                                Entry Timing
                              </p>
                              <h2 className="mt-1 text-lg font-semibold text-zinc-900 dark:text-zinc-50">
                                進場條件:貴不貴 / 等哪裡 / 能不能加
                              </h2>
                            </div>
                            <EntryContextCard symbol={twResult.symbol} />
                          </section>
                        )}

                        <section className="space-y-4">
                          <div>
                            <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                              Technical
                            </p>
                            <h2 className="mt-1 text-lg font-semibold text-zinc-900 dark:text-zinc-50">
                              技術面
                            </h2>
                          </div>
                          <PriceHistoryChart
                            stockCode={twResult.symbol}
                            initialCandles={twResult.chart_data}
                          />
                        </section>

                        <section className="space-y-4">
                          <div>
                            <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                              Chip
                            </p>
                            <h2 className="mt-1 text-lg font-semibold text-zinc-900 dark:text-zinc-50">
                              籌碼面
                            </h2>
                          </div>
                          <TwDetailedAnalysis
                            institutional_summary={twResult.institutional_summary}
                            chip_risk_summary={twResult.chip_risk_summary}
                            cashflow_summary={twResult.cashflow_summary}
                            macro_summary={twResult.macro_summary}
                          />
                        </section>

                        <section className="space-y-4">
                          <div>
                            <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                              News
                            </p>
                            <h2 className="mt-1 text-lg font-semibold text-zinc-900 dark:text-zinc-50">
                              消息面
                            </h2>
                          </div>
                          {twResult.news?.summary && (
                            <div className="rounded-xl border border-zinc-200 bg-white p-5 text-sm leading-relaxed text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300">
                              {twResult.news.summary}
                            </div>
                          )}
                          <NewsSection news={twResult.recent_news} />
                        </section>
                      </div>
                    )}

                    {page === 'analysis' && (
                      <section className="min-w-0 space-y-5">
                        <div>
                          <p className="text-xs font-semibold uppercase tracking-wide text-zinc-500 dark:text-zinc-400">
                            AI View
                          </p>
                          <h2 className="mt-1 text-lg font-semibold text-zinc-900 dark:text-zinc-50">
                            AI 分析判讀
                          </h2>
                        </div>

                        <AIAnalysisPage symbol={twResult.symbol} sourceData={twResult} />
                      </section>
                    )}

                    {/* Favorite toggle for analyzed stock */}
                    <div className="flex items-center justify-center gap-3">
                      <button
                        onClick={() => toggleFavorite(twResult.symbol, twResult.company_name)}
                        className="rounded-full border border-zinc-300 px-4 py-1.5 text-sm font-medium text-zinc-600 hover:border-zinc-400 dark:border-zinc-700 dark:text-zinc-300"
                      >
                        {favCodes.includes(twResult.symbol) ? '★ 已加自選' : '☆ 加入自選'}
                      </button>
                    </div>

                    <p className="pb-2 text-center text-xs text-zinc-400 dark:text-zinc-500">
                      {twResult.disclaimer}
                    </p>
                    <p className="-mt-4 pb-4 text-center text-xs text-zinc-400 dark:text-zinc-500">
                      分析時間：{new Date(twResult.analyzed_at).toLocaleString('zh-TW')}
                    </p>
                  </>
                )}

                {/* US results */}
                {usResult && !loading && (
                  <>
                    <div className="flex justify-end">
                      <span className={`rounded-full px-3 py-1 text-xs font-medium ${
                        usResult.data_source === 'live'
                          ? 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300'
                          : 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300'
                      }`}>
                        {usResult.data_source === 'live' ? '● Live Data' : '● Demo Data'}
                      </span>
                    </div>

                    {page === 'analysis' && <AnalysisCard data={usResult} />}

                    {page === 'stock-analysis' && (
                      <>
                        <StockChart chartData={usResult.chart_data} symbol={usResult.symbol} />
                        <NewsSection news={usResult.recent_news} />
                        <FinancialSummary summary={usResult.financial_summary} />
                      </>
                    )}

                    {page === 'stock-analysis' && usResult.fundamentals && <FundamentalsCard data={usResult.fundamentals} />}

                    {page === 'stock-analysis' && (peersLoading || competitors) && (
                      <CompetitorCard
                        symbol={usResult.symbol}
                        peers={competitors?.peers ?? []}
                        loading={peersLoading}
                      />
                    )}

                    <p className="pb-4 text-center text-xs text-zinc-400 dark:text-zinc-500">
                      This is financial analysis support only, not financial advice.
                    </p>
                  </>
                )}
              </>
            )}

            {/* ── Bold plan: FinMind playground ── */}
            {page === 'bold-plan' && <BoldPlanView />}

            {/* ── Market sector heatmap ── */}
            {page === 'market-heatmap' && <MarketHeatmapView />}

            {/* ── Daily opportunities (research-v2 three-bucket screen) ── */}
            {page === 'opportunities' && (
              <DailyOpportunitiesView onSelect={(code) => goAnalyze(code, code)} />
            )}

            {/* ── Backtest dashboard (opps_v2 events.csv, aggregated offline) ── */}
            {page === 'backtest-dashboard' && <BacktestDashboardView />}

            {/* ── Portfolio ── */}
            {page === 'portfolio' && (
              <div className="space-y-6">
                <div>
                  <div className="mb-3 flex items-center justify-between gap-2">
                    <h2 className="text-base font-semibold text-pink-700 dark:text-pink-300">
                      <span className="inline-block animate-heartbeat mr-1">💖</span>
                      我的寶貝資產
                    </h2>
                    <button
                      type="button"
                      onClick={() => { setAddTarget('real'); setPage('add-position'); }}
                      className="rounded-full bg-gradient-to-r from-pink-500 to-rose-500 px-4 py-1.5 text-xs font-semibold text-white shadow-md hover:from-pink-600 hover:to-rose-600 transition-all"
                    >
                      ➕ 加新寶貝
                    </button>
                  </div>
                  <PortfolioDashboard
                    positions={positions}
                    onDelete={deletePosition}
                    onSelect={(code, name) => goAnalyze(code, name)}
                    onRefreshPrices={() => refreshPortfolioPrices()}
                    refreshingPrices={priceRefreshing}
                    priceRefreshError={priceRefreshError}
                  />
                </div>

                <AllocationCalculator defaultSymbols={positions.map((p) => p.stock_code).join(' ')} />

                <div>
                  <div className="mb-3 flex items-center justify-between gap-2">
                    <h2 className="text-base font-semibold text-purple-700 dark:text-purple-300">🌸 練習小天地</h2>
                    <button
                      type="button"
                      onClick={() => { setAddTarget('sim'); setPage('add-position'); }}
                      className="rounded-full bg-gradient-to-r from-purple-400 to-fuchsia-500 px-4 py-1.5 text-xs font-semibold text-white shadow-md hover:from-purple-500 hover:to-fuchsia-600 transition-all"
                    >
                      ✨ 加練習寶貝
                    </button>
                  </div>
                  <p className="mb-3 text-xs text-zinc-500 dark:text-zinc-400">
                    這裡只是練習用的小天地，不會影響真正的小金庫～可以拿來追蹤想試試看的標的 ✿
                  </p>
                  <PortfolioDashboard
                    positions={simPositions}
                    onDelete={deleteSimPosition}
                    onSelect={(code, name) => goAnalyze(code, name)}
                    onRefreshPrices={() => refreshSimPortfolioPrices()}
                    refreshingPrices={simPriceRefreshing}
                    priceRefreshError={simPriceRefreshError}
                  />
                </div>
              </div>
            )}

            {/* ── Stock directory ── */}
            {page === 'directory' && (
              <StockDirectory
                onSelectStock={(code, name) => goAnalyze(code, name)}
                favorites={favCodes}
                onToggleFavorite={toggleFavorite}
              />
            )}

            {/* ── External news ── */}
            {page === 'news' && <ExternalNews />}

            {/* ── Calendar (dividends + earnings) ── */}
            {page === 'calendar' && (
              <div className="space-y-6">
                <DividendCalendar symbol={twResult?.symbol} />
                <EarningsCalendar symbol={twResult?.symbol} />
              </div>
            )}

            {/* ── Watchlist ── */}
            {page === 'watchlist' && (
              <Watchlist
                favorites={favorites}
                recents={recents}
                onSelect={(code, name) => goAnalyze(code, name)}
                onRemoveFavorite={(code) => saveFavorites(favorites.filter((f) => f.code !== code))}
                onClearRecents={() => saveRecents([])}
                telegramEnabled={false}
              />
            )}

            {/* ── Add position ── */}
            {page === 'add-position' && (
              <div className="rounded-2xl border border-pink-200 bg-white/90 p-6 shadow-sm dark:border-pink-900/40 dark:bg-zinc-900">
                <h2 className="mb-4 text-base font-semibold text-pink-700 dark:text-pink-300">
                  🌷 加新寶貝
                </h2>
                <div className="mb-4 flex items-center gap-2">
                  <span className="text-sm text-zinc-600 dark:text-zinc-400">加到哪裡：</span>
                  <button
                    type="button"
                    onClick={() => setAddTarget('real')}
                    className={`rounded-full px-3 py-1.5 text-xs font-semibold transition-all ${
                      addTarget === 'real'
                        ? 'bg-gradient-to-r from-pink-500 to-rose-500 text-white shadow-md'
                        : 'border border-pink-200 text-pink-600 hover:border-pink-400 hover:bg-pink-50 dark:border-pink-900/40 dark:text-pink-300'
                    }`}
                  >
                    💖 我的寶貝資產
                  </button>
                  <button
                    type="button"
                    onClick={() => setAddTarget('sim')}
                    className={`rounded-full px-3 py-1.5 text-xs font-semibold transition-all ${
                      addTarget === 'sim'
                        ? 'bg-gradient-to-r from-purple-400 to-fuchsia-500 text-white shadow-md'
                        : 'border border-purple-200 text-purple-600 hover:border-purple-400 hover:bg-purple-50 dark:border-purple-900/40 dark:text-purple-300'
                    }`}
                  >
                    🌸 練習小天地
                  </button>
                </div>
                <AddPosition
                  onAdd={addPosition}
                  currentAnalyzedStock={currentAnalyzedStock}
                />
              </div>
            )}

          </div>
        </main>
      </div>

      {/* ── Floating 模擬持倉 quick-add bubble (always visible, scroll-locked) ── */}
      <button
        type="button"
        onClick={() => setFloatingSimAddOpen(prev => !prev)}
        title={floatingSimAddOpen ? '關閉' : '快速加練習寶貝'}
        className={`fixed right-6 top-1/2 z-40 flex h-14 w-14 -translate-y-1/2 items-center justify-center rounded-full text-2xl shadow-xl transition-all hover:scale-110 active:scale-95 ${
          floatingSimAddOpen
            ? 'bg-zinc-600 text-white'
            : 'bg-gradient-to-br from-pink-400 via-rose-400 to-purple-400 text-white animate-gradient-shift hover:from-pink-500 hover:via-rose-500 hover:to-purple-500'
        }`}
        aria-label="快速加練習寶貝"
      >
        <span className={floatingSimAddOpen ? '' : 'inline-block animate-heartbeat'}>
          {floatingSimAddOpen ? '✕' : '💗'}
        </span>
      </button>

      {/* ── Floating 快速購入（練習持倉、最近價格、1 張）── */}
      {currentAnalyzedStock && quickBuyPrice != null && (
        <button
          type="button"
          onClick={quickBuySim}
          title={`快速購入 ${currentAnalyzedStock.stock_code} ${currentAnalyzedStock.company_name} 1 張（最近價格 ${quickBuyPrice.toFixed(2)}，練習持倉）`}
          aria-label="快速購入（練習持倉）"
          className={`fixed right-6 top-[calc(50%+4.5rem)] z-40 flex h-14 w-14 -translate-y-1/2 items-center justify-center rounded-full text-2xl shadow-xl transition-all hover:scale-110 active:scale-95 ${
            quickBuyFlash
              ? 'bg-emerald-500 text-white'
              : 'bg-gradient-to-br from-amber-400 via-orange-400 to-rose-400 text-white hover:from-amber-500 hover:via-orange-500 hover:to-rose-500'
          }`}
        >
          {quickBuyFlash ? '✓' : '⚡'}
        </button>
      )}

      {floatingSimAddOpen && (
        <div
          className="fixed right-24 top-1/2 z-40 w-[420px] max-w-[calc(100vw-7rem)] -translate-y-1/2 rounded-3xl border border-pink-200 bg-white shadow-2xl dark:border-pink-900/60 dark:bg-zinc-900 animate-pop-in"
          role="dialog"
          aria-label="快速加練習寶貝"
        >
          <div className="flex items-center justify-between gap-2 border-b border-pink-100 bg-gradient-to-r from-pink-50 to-purple-50 px-4 py-3 dark:border-pink-900/40 dark:from-pink-950/30 dark:to-purple-950/30">
            <h3 className="text-sm font-semibold text-pink-700 dark:text-pink-300">
              💗 快速加練習寶貝
            </h3>
            <button
              type="button"
              onClick={() => setFloatingSimAddOpen(false)}
              className="rounded-md p-1 text-pink-500 hover:bg-pink-100 hover:text-pink-700 dark:hover:bg-pink-950/40 dark:hover:text-pink-200"
              aria-label="關閉"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          <p className="px-4 pt-3 text-xs text-zinc-500 dark:text-zinc-400">
            ✿ 不會動到真正的小金庫，可以練習買進想試試看的標的～
          </p>
          <div className="max-h-[70vh] overflow-y-auto px-4 pb-4 pt-2">
            <AddPosition
              onAdd={(pos) => {
                const newPos: Position = { ...pos, id: `${Date.now()}-${Math.random()}` };
                const next = [...simPositionsRef.current, newPos];
                saveSimPositions(next);
                refreshSimPortfolioPrices(next);
                setFloatingSimAddOpen(false);
              }}
              currentAnalyzedStock={currentAnalyzedStock}
            />
          </div>
        </div>
      )}
    </div>
  );
}
