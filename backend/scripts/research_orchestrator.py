"""Persistent autonomous-research worker with graceful shutdown."""

from __future__ import annotations

import argparse
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from threading import Event

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.research_platform.orchestrator import ResearchOrchestrator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Process at most one queued job")
    parser.add_argument("--schedule-cycle", action="store_true", help="Enqueue the current UTC-day cycle before running")
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    orchestrator = ResearchOrchestrator()
    if args.schedule_cycle:
        cycle_key = datetime.now(timezone.utc).strftime("cycle:%Y-%m-%d")
        orchestrator.schedule_cycle(cycle_key)
    if args.once:
        orchestrator.run_once()
        return

    stop = Event()

    def request_stop(*_args) -> None:
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    orchestrator.run_forever(stop, poll_seconds=args.poll_seconds)


if __name__ == "__main__":
    main()
