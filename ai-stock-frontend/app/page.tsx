'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  analyzeStock, analyzeTW, getCompetitors, syncTelegramWatchlist,
  StockAnalysisResponse,
} from '@/lib/api';
import {
  TaiwanStockAnalysisResponse, CompetitorResponse, Position,
} from '@/lib/types';

import TwSearchBar from './components/TwSearchBar';
import AnalysisCard from './components/AnalysisCard';
import TwAnalysisCard from './components/TwAnalysisCard';
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
import Watchlist from './components/Watchlist';
import AddPosition from './components/AddPosition';
import DividendCalendar from './components/DividendCalendar';
import EarningsCalendar from './components/EarningsCalendar';
import ETFHoldingsCard from './components/ETFHoldingsCard';
import EquityResearchReport from './components/EquityResearchReport';

type Page = 'analysis' | 'portfolio' | 'directory' | 'news' | 'calendar' | 'watchlist' | 'add-position';
const TW_RE = /^\d{4,6}$/;
const STORAGE_POSITIONS = 'stockAssistant.positions';
const STORAGE_FAVORITES = 'stockAssistant.favorites';
const STORAGE_RECENTS = 'stockAssistant.recents';

interface FavoriteItem { code: string; name: string }

// ── Sidebar nav ────────────────────────────────────────────────────────────────

const NAV: { page: Page; label: string; icon: string }[] = [
  { page: 'analysis', label: 'AI 分析', icon: '🔍' },
  { page: 'portfolio', label: '投資組合', icon: '📊' },
  { page: 'directory', label: '股票目錄', icon: '📋' },
  { page: 'news', label: '市場新聞', icon: '📰' },
  { page: 'calendar', label: '行事曆', icon: '📅' },
  { page: 'watchlist', label: '自選清單', icon: '★' },
  { page: 'add-position', label: '新增持倉', icon: '+' },
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
        className={`fixed inset-y-0 left-0 z-30 w-56 transform bg-white shadow-lg transition-transform dark:bg-zinc-900 lg:static lg:translate-x-0 lg:shadow-none ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="border-b border-zinc-200 p-4 dark:border-zinc-800">
          <p className="text-xs font-bold text-zinc-500 dark:text-zinc-400 uppercase tracking-wider">
            股票助理
          </p>
        </div>
        <nav className="p-2">
          {NAV.map(({ page, label, icon }) => (
            <button
              key={page}
              onClick={() => { onChange(page); onClose(); }}
              className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                current === page
                  ? 'bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300'
                  : 'text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800'
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
  const [page, setPage] = useState<Page>('analysis');
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

  // Watchlist / recents
  const [favorites, setFavorites] = useState<FavoriteItem[]>([]);
  const [recents, setRecents] = useState<FavoriteItem[]>([]);

  // Load persisted state
  useEffect(() => {
    try {
      const p = localStorage.getItem(STORAGE_POSITIONS);
      if (p) setPositions(JSON.parse(p));
    } catch { /* empty */ }
    try {
      const f = localStorage.getItem(STORAGE_FAVORITES);
      if (f) setFavorites(JSON.parse(f));
    } catch { /* empty */ }
    try {
      const r = localStorage.getItem(STORAGE_RECENTS);
      if (r) setRecents(JSON.parse(r));
    } catch { /* empty */ }
  }, []);

  function savePositions(next: Position[]) {
    setPositions(next);
    localStorage.setItem(STORAGE_POSITIONS, JSON.stringify(next));
  }

  function saveFavorites(next: FavoriteItem[]) {
    setFavorites(next);
    localStorage.setItem(STORAGE_FAVORITES, JSON.stringify(next));
  }

  function saveRecents(next: FavoriteItem[]) {
    setRecents(next);
    localStorage.setItem(STORAGE_RECENTS, JSON.stringify(next));
  }

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
        setPositions((prev) =>
          prev.map((p) =>
            p.stock_code === symbol
              ? { ...p, current_price: data.current_price }
              : p
          )
        );
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recents]);

  // Navigate to analysis and pre-fill symbol
  function goAnalyze(code: string, name: string) {
    setPage('analysis');
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

  // Portfolio management
  function addPosition(pos: Omit<Position, 'id'>) {
    const newPos: Position = { ...pos, id: `${Date.now()}-${Math.random()}` };
    savePositions([...positions, newPos]);
    setPage('portfolio');
  }

  function deletePosition(id: string) {
    savePositions(positions.filter((p) => p.id !== id));
  }

  return (
    <div className="flex min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <Sidebar
        current={page}
        onChange={setPage}
        sidebarOpen={sidebarOpen}
        onClose={() => setSidebarOpen(false)}
      />

      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Top bar */}
        <header className="border-b border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
          <div className="flex items-center gap-3 px-4 py-3">
            <button
              className="rounded-lg p-1.5 text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800 lg:hidden"
              onClick={() => setSidebarOpen(true)}
              aria-label="Open navigation"
            >
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
            <h1 className="text-base font-bold text-zinc-900 dark:text-zinc-50">
              {NAV.find((n) => n.page === page)?.label ?? 'AI 股票分析'}
            </h1>
          </div>
        </header>

        {/* Main content */}
        <main className="flex-1 overflow-y-auto px-4 py-6">
          <div className="mx-auto max-w-6xl space-y-6">

            {/* ── Analysis ── */}
            {page === 'analysis' && (
              <>
                <MarketOverview />
                <TwSearchBar onSearch={handleSearch} loading={loading} />

                {error && (
                  <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
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
                    <TwAnalysisCard data={twResult} />

                    {/* Next dividend banner */}
                    {twResult.next_dividend && (
                      <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-2.5 text-sm dark:border-amber-900 dark:bg-amber-950/40">
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

                    {/* Dedicated price history chart with indicators */}
                    <div className="grid grid-cols-1 gap-6 xl:grid-cols-[minmax(0,2fr)_minmax(280px,1fr)]">
                      <div className="min-w-0">
                        <PriceHistoryChart
                          stockCode={twResult.symbol}
                          initialCandles={twResult.chart_data}
                        />
                      </div>
                      <div className="min-w-0">
                        <TwFinancialSummary
                          currency={twResult.currency}
                          market_type={twResult.market_type}
                          current_price={twResult.current_price}
                          price_change_percent={twResult.price_change_percent}
                          volume={twResult.volume}
                        />
                      </div>
                    </div>

                    {/* ETF holdings (only when analyzing an ETF) */}
                    {twResult.is_etf && twResult.etf_holdings && (
                      <ETFHoldingsCard data={twResult.etf_holdings} />
                    )}

                    {/* Detailed analysis: revenue, valuation, institutional, chip, macro */}
                    <TwDetailedAnalysis
                      revenue_summary={twResult.revenue_summary}
                      valuation_summary={twResult.valuation_summary}
                      institutional_summary={twResult.institutional_summary}
                      chip_risk_summary={twResult.chip_risk_summary}
                      macro_summary={twResult.macro_summary}
                    />

                    <NewsSection news={twResult.recent_news} />

                    {/* Elite equity research report */}
                    {twResult.equity_research && (
                      <EquityResearchReport
                        data={twResult.equity_research}
                        currentPrice={twResult.current_price}
                        companyName={twResult.company_name}
                        symbol={twResult.symbol}
                      />
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

                    <AnalysisCard data={usResult} />
                    <StockChart chartData={usResult.chart_data} symbol={usResult.symbol} />
                    <NewsSection news={usResult.recent_news} />
                    <FinancialSummary summary={usResult.financial_summary} />

                    {usResult.fundamentals && <FundamentalsCard data={usResult.fundamentals} />}

                    {(peersLoading || competitors) && (
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

            {/* ── Portfolio ── */}
            {page === 'portfolio' && (
              <PortfolioDashboard
                positions={positions}
                onDelete={deletePosition}
                onSelect={(code, name) => goAnalyze(code, name)}
              />
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
              <div className="rounded-xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-zinc-900">
                <h2 className="mb-4 text-base font-semibold text-zinc-800 dark:text-zinc-200">
                  新增持倉
                </h2>
                <AddPosition onAdd={addPosition} />
              </div>
            )}

          </div>
        </main>
      </div>
    </div>
  );
}
