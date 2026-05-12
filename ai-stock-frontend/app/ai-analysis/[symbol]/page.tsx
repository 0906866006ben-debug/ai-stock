import { AIAnalysisPage } from '@/app/components/ai-analysis/AIAnalysisPage';

interface PageProps {
  params: Promise<{ symbol: string }>;
}

export default async function SymbolAIAnalysisPage({ params }: PageProps) {
  const { symbol } = await params;

  return (
    <main className="min-h-screen bg-zinc-50 px-4 py-6 dark:bg-zinc-950">
      <AIAnalysisPage symbol={decodeURIComponent(symbol)} />
    </main>
  );
}
