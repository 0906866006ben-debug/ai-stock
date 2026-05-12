'use client';

import type {
  RevenueSummary, ValuationSummary, InstitutionalSummary,
  ChipRiskSummary, MacroEnvironmentSummary,
} from '@/lib/types';

function fmt(val: number | null | undefined, digits = 2): string {
  if (val == null) return 'N/A';
  return val.toFixed(digits);
}

function fmtPct(val: number | null | undefined): string {
  if (val == null) return 'N/A';
  const sign = val >= 0 ? '+' : '';
  return `${sign}${val.toFixed(2)}%`;
}

function fmtNum(val: number | null | undefined): string {
  if (val == null) return 'N/A';
  return val.toLocaleString();
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    ok: 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300',
    no_data: 'bg-zinc-100 text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400',
    cheap: 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300',
    fair: 'bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300',
    expensive: 'bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300',
    live: 'bg-green-100 text-green-700 dark:bg-green-900 dark:text-green-300',
    mock: 'bg-amber-100 text-amber-700 dark:bg-amber-900 dark:text-amber-300',
  };
  const cls = map[status] ?? map['no_data'];
  return <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}>{status}</span>;
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <h3 className="mb-3 text-sm font-semibold text-zinc-700 dark:text-zinc-300">{title}</h3>
      {children}
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-1 text-sm">
      <span className="text-zinc-500 dark:text-zinc-400">{label}</span>
      <span className="font-medium text-zinc-800 dark:text-zinc-200">{value}</span>
    </div>
  );
}

// ── Revenue ────────────────────────────────────────────────────────────────────

function RevenueCard({ data }: { data: RevenueSummary }) {
  if (data.status === 'no_data') {
    return (
      <Card title="營收概況">
        <p className="text-sm text-zinc-400">暫無營收資料</p>
      </Card>
    );
  }
  return (
    <Card title="營收概況">
      <Row label="最新月營收" value={data.latest_revenue ? `${data.latest_revenue} 千元` : 'N/A'} />
      <Row label="年增率 (YoY)" value={
        <span className={data.yoy_pct != null && data.yoy_pct >= 0 ? 'text-red-500' : 'text-green-600'}>
          {fmtPct(data.yoy_pct)}
        </span>
      } />
      <Row label="月增率 (MoM)" value={
        <span className={data.mom_pct != null && data.mom_pct >= 0 ? 'text-red-500' : 'text-green-600'}>
          {fmtPct(data.mom_pct)}
        </span>
      } />
      <Row label="可用月數" value={`${data.available_months} 個月`} />
    </Card>
  );
}

// ── Valuation ─────────────────────────────────────────────────────────────────

function ValuationCard({ data }: { data: ValuationSummary }) {
  const statusLabels: Record<string, string> = {
    cheap: '便宜', fair: '合理', expensive: '昂貴', no_data: '無資料',
  };
  return (
    <Card title="估值指標">
      <Row label="本益比 (PER)" value={fmt(data.per, 1)} />
      <Row label="股價淨值比 (PBR)" value={fmt(data.pbr, 2)} />
      <Row label="殖利率" value={data.dividend_yield != null ? `${fmt(data.dividend_yield, 2)}%` : 'N/A'} />
      <Row label="估值狀態" value={<StatusBadge status={data.status} />} />
    </Card>
  );
}

// ── Institutional ─────────────────────────────────────────────────────────────

function InstitutionalCard({ data }: { data: InstitutionalSummary }) {
  if (data.status === 'no_data') {
    return (
      <Card title="法人動向">
        <p className="text-sm text-zinc-400">暫無法人資料</p>
      </Card>
    );
  }
  const dirLabel: Record<string, string> = {
    net_buy: '淨買超', net_sell: '淨賣超', neutral: '持平', unknown: '未知',
  };
  const dirColor: Record<string, string> = {
    net_buy: 'text-red-500', net_sell: 'text-green-600', neutral: 'text-zinc-500', unknown: 'text-zinc-400',
  };
  return (
    <Card title="法人動向">
      <Row label="方向" value={
        <span className={dirColor[data.direction] ?? 'text-zinc-400'}>
          {dirLabel[data.direction] ?? data.direction}
        </span>
      } />
      <Row label="外資 5日淨" value={fmtNum(data.foreign_net_5d)} />
      <Row label="外資 10日淨" value={fmtNum(data.foreign_net_10d)} />
      <Row label="投信 5日淨" value={fmtNum(data.trust_net_5d)} />
      <Row label="自營商 5日淨" value={fmtNum(data.dealer_net_5d)} />
    </Card>
  );
}

// ── Chip Risk ─────────────────────────────────────────────────────────────────

function ChipRiskCard({ data }: { data: ChipRiskSummary }) {
  if (data.status === 'no_data') {
    return (
      <Card title="籌碼風險">
        <p className="text-sm text-zinc-400">暫無籌碼資料</p>
      </Card>
    );
  }
  const riskColor: Record<string, string> = {
    low: 'text-green-600', medium: 'text-amber-500', high: 'text-red-500', unknown: 'text-zinc-400',
  };
  return (
    <Card title="籌碼風險">
      <Row label="籌碼方向" value={data.chip_direction} />
      <Row label="風險等級" value={
        <span className={riskColor[data.risk_level] ?? 'text-zinc-400'}>{data.risk_level}</span>
      } />
      <Row label="融資餘額" value={fmtNum(data.margin_balance)} />
      <Row label="放空餘額" value={fmtNum(data.short_balance)} />
    </Card>
  );
}

// ── Macro ─────────────────────────────────────────────────────────────────────

function MacroCard({ data }: { data: MacroEnvironmentSummary }) {
  return (
    <Card title="總體環境">
      <Row label="美元/台幣" value={fmt(data.usd_twd, 2)} />
      <Row label="美債 10Y" value={data.us_10y_yield != null ? `${fmt(data.us_10y_yield, 2)}%` : 'N/A'} />
      <Row label="S&P 500" value={fmtNum(data.sp500 ? Math.round(data.sp500) : null)} />
      <Row label="Nasdaq" value={fmtNum(data.nasdaq ? Math.round(data.nasdaq) : null)} />
      <Row label="黃金 (USD/oz)" value={fmt(data.gold_price, 0)} />
      <Row label="WTI 原油" value={fmt(data.oil_wti, 2)} />
      {data.status === 'mock' && (
        <p className="mt-2 text-xs text-amber-500">* 模擬資料</p>
      )}
    </Card>
  );
}

// ── Main export ───────────────────────────────────────────────────────────────

interface Props {
  revenue_summary?: RevenueSummary | null;
  valuation_summary?: ValuationSummary | null;
  institutional_summary?: InstitutionalSummary | null;
  chip_risk_summary?: ChipRiskSummary | null;
  macro_summary?: MacroEnvironmentSummary | null;
}

export default function TwDetailedAnalysis({
  revenue_summary,
  valuation_summary,
  institutional_summary,
  chip_risk_summary,
  macro_summary,
}: Props) {
  const hasAny = revenue_summary || valuation_summary || institutional_summary
    || chip_risk_summary || macro_summary;

  if (!hasAny) return null;

  return (
    <div className="space-y-4">
      <h2 className="text-base font-semibold text-zinc-800 dark:text-zinc-200">詳細分析</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        {revenue_summary && <RevenueCard data={revenue_summary} />}
        {valuation_summary && <ValuationCard data={valuation_summary} />}
        {institutional_summary && <InstitutionalCard data={institutional_summary} />}
        {chip_risk_summary && <ChipRiskCard data={chip_risk_summary} />}
      </div>
      {macro_summary && <MacroCard data={macro_summary} />}
    </div>
  );
}
