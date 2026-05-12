'use client';

import type { TaiwanStockAnalysisResponse } from '@/lib/types';
import { useAIAnalysis } from '@/hooks/useAIAnalysis';
import { VerdictBar } from './verdict/VerdictBar';
import { ThreeHorizonView } from './horizons/ThreeHorizonView';
import { ScenarioPlaybook } from './scenarios/ScenarioPlaybook';
import { EvidenceLedger } from './evidence/EvidenceLedger';
import { WyckoffStructurePanel } from './structure/WyckoffStructurePanel';
import { DeepResearchReport } from './report/DeepResearchReport';
import { ProvenanceFooter } from './provenance/ProvenanceFooter';
import { LoadingSkeleton } from './states/LoadingSkeleton';
import { ErrorBoundary } from './states/ErrorBoundary';
import { MockDataBanner } from './states/MockDataBanner';
import { LowQualityBanner } from './states/LowQualityBanner';
import { DispositionWarning } from './shared/DispositionWarning';

interface AIAnalysisPageProps {
  symbol: string;
  sourceData?: TaiwanStockAnalysisResponse | null;
}

/**
 * AI analysis decision page: assembles the seven-layer decision pyramid for
 * Topics A-E while keeping future Topics F-T extension points visible.
 */
export function AIAnalysisPage({ symbol, sourceData }: AIAnalysisPageProps) {
  const { data, isLoading, error, refetch } = useAIAnalysis(symbol, { sourceData });

  if (isLoading) return <LoadingSkeleton />;
  if (error || !data) return <ErrorBoundary error={error} onRetry={refetch} />;

  return (
    <div className="ai-analysis-page mx-auto flex max-w-[1080px] flex-col gap-6 px-4 py-5">
      {data.data_quality === 'mock' && <MockDataBanner />}
      {data.data_quality_score < 60 && <LowQualityBanner score={data.data_quality_score} />}
      <DispositionWarning status={data.disposition_status} />

      <VerdictBar data={data} />
      <ThreeHorizonView data={data} />
      <ScenarioPlaybook data={data} />
      <EvidenceLedger data={data} />
      <WyckoffStructurePanel data={data.structure_panel} />
      <DeepResearchReport data={data} />
      <ProvenanceFooter data={data} onRecompute={refetch} />
    </div>
  );
}
