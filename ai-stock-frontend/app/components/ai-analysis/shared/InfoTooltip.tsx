import type { ReactNode } from 'react';

interface InfoTooltipProps {
  label: string;
  children: ReactNode;
}

/**
 * Keyboard-friendly tooltip wrapper for technical traceability fields.
 */
export function InfoTooltip({ label, children }: InfoTooltipProps) {
  return (
    <span className="group relative inline-flex">
      <span
        tabIndex={0}
        className="cursor-help rounded outline-none focus:ring-2 focus:ring-blue-400"
        aria-label={label}
      >
        {children}
      </span>
      <span className="pointer-events-none absolute bottom-full left-0 z-10 mb-2 hidden w-64 rounded-lg border border-zinc-200 bg-white p-2 text-xs leading-relaxed text-zinc-600 shadow-lg group-hover:block group-focus-within:block dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300">
        {label}
      </span>
    </span>
  );
}
