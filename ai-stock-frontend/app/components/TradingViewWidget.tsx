'use client';

import { useEffect, useRef } from 'react';

declare global {
  interface Window {
    TradingView?: {
      widget: new (config: Record<string, unknown>) => void;
    };
  }
}

interface Props {
  symbol: string;
  range: string;
  widgetId: string;
  height?: number;
}

export default function TradingViewWidget({ symbol, range, widgetId, height = 500 }: Props) {
  const outerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const outer = outerRef.current;
    if (!outer) return;

    const innerId = `tv-${widgetId}`;
    outer.innerHTML = `<div id="${innerId}"></div>`;

    function createWidget() {
      if (!window.TradingView || !document.getElementById(innerId)) return;
      new window.TradingView.widget({
        autosize: true,
        symbol,
        interval: 'D',
        range,
        timezone: 'Asia/Taipei',
        theme: 'dark',
        style: '1',
        locale: 'zh_TW',
        enable_publishing: false,
        allow_symbol_change: false,
        container_id: innerId,
        save_image: false,
        hide_top_toolbar: false,
      });
    }

    if (window.TradingView) {
      createWidget();
    } else if (!document.querySelector('script[src="https://s3.tradingview.com/tv.js"]')) {
      const script = document.createElement('script');
      script.src = 'https://s3.tradingview.com/tv.js';
      script.async = true;
      script.onload = createWidget;
      document.head.appendChild(script);
    } else {
      // Script is already loading — poll until TradingView is ready
      const poll = window.setInterval(() => {
        if (window.TradingView) {
          window.clearInterval(poll);
          createWidget();
        }
      }, 100);
      return () => {
        window.clearInterval(poll);
        if (outer) outer.innerHTML = '';
      };
    }

    return () => {
      if (outer) outer.innerHTML = '';
    };
  }, [symbol, range, widgetId, height]);

  return <div ref={outerRef} style={{ height: `${height}px`, width: '100%' }} />;
}
