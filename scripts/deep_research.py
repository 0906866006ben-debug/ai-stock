#!/usr/bin/env python3
"""Gemini Deep Research runner with persistent, resumable job state.

Adapted for the ai-stock value-quant project (mirrors the ICT project's script).
Reports land in Docs/research/. GEMINI_API_KEY is read from backend/.env (paid tier
required for the Deep Research agent).

    python scripts/deep_research.py "台股回購文化對 Shareholder Yield 因子的影響與證據"
    python scripts/deep_research.py --job-file <path> --status-only   # poll a background job
    python scripts/deep_research.py --job-file <path> --cancel        # cancel
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

# Load GEMINI_API_KEY from backend/.env so the script is self-sufficient (the
# backend loads it via dotenv at import; a standalone script must do it itself).
try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / "backend" / ".env")
except ImportError:
    pass

AGENT = os.environ.get("DR_AGENT", "deep-research-preview-04-2026")
OUT_DIR = ROOT / "Docs" / "research"
JOB_DIR = OUT_DIR / ".deep-research-jobs"
POLL_SECONDS = max(5, int(os.environ.get("DR_POLL_SECONDS", "15")))
MAX_WAIT_SECONDS = max(0, int(os.environ.get("DR_MAX_WAIT_SECONDS", "3600")))
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def now_iso() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")


def slugify(text: str) -> str:
    value = re.sub(r"\s+", "-", text.strip())[:60]
    return re.sub(r"[^0-9A-Za-z一-鿿\-]", "", value) or "research"


def default_job_file(query: str) -> Path:
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    digest = hashlib.sha256(query.encode("utf-8")).hexdigest()[:12]
    return JOB_DIR / f"{timestamp}-{digest}.json"


def load_state(job_file: Path) -> dict[str, Any]:
    try:
        return json.loads(job_file.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def update_state(job_file: Path, **updates: Any) -> dict[str, Any]:
    job_file.parent.mkdir(parents=True, exist_ok=True)
    state = load_state(job_file)
    state.update(updates)
    state["updated_at"] = now_iso()
    temporary = job_file.with_suffix(f"{job_file.suffix}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary, job_file)
    return state


def interaction_status(interaction: Any) -> str:
    return str(getattr(interaction, "status", "unknown"))


def interaction_error(interaction: Any) -> str:
    error = getattr(interaction, "error", None)
    return str(error) if error else ""


def write_report(
    job_file: Path, state: dict[str, Any], interaction: Any
) -> dict[str, Any]:
    report = getattr(interaction, "output_text", "") or ""
    report_path_value = state.get("report_path")
    if report_path_value:
        report_path = ROOT / report_path_value
    else:
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        report_path = OUT_DIR / f"{timestamp}-{slugify(state['query'])}.md"

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        f"# Gemini Deep Research：{state['query']}\n\n"
        f"- agent：{state.get('agent', AGENT)}\n"
        f"- interaction：{state.get('interaction_id', '')}\n"
        f"- 完成時間：{now_iso()}\n\n---\n\n{report}\n",
        encoding="utf-8",
    )
    relative_report = str(report_path.relative_to(ROOT))
    return update_state(
        job_file,
        remote_status="completed",
        worker_status="completed",
        report_path=relative_report,
        completed_at=now_iso(),
        last_error="",
    )


def refresh_once(client: Any, job_file: Path) -> dict[str, Any]:
    state = load_state(job_file)
    interaction_id = state.get("interaction_id")
    if not interaction_id:
        raise RuntimeError(f"Job has no interaction_id: {job_file}")

    interaction = client.interactions.get(interaction_id)
    status = interaction_status(interaction)
    state = update_state(
        job_file,
        remote_status=status,
        last_checked_at=now_iso(),
        last_error=interaction_error(interaction),
    )
    if status == "completed":
        return write_report(job_file, state, interaction)
    if status in {"failed", "cancelled"}:
        return update_state(job_file, worker_status=status)
    return state


def create_or_resume(client: Any, query: str, job_file: Path) -> dict[str, Any]:
    state = load_state(job_file)
    if state.get("interaction_id"):
        return update_state(
            job_file,
            query=query,
            agent=state.get("agent", AGENT),
            worker_pid=os.getpid(),
            worker_status="running",
            resumed_at=now_iso(),
            last_error="",
        )

    tools: list[dict[str, Any]] = [{"type": "google_search"}]
    store = os.environ.get("DR_FILE_SEARCH_STORE")
    if store:
        tools.append(
            {"type": "file_search", "file_search_store_names": [store]}
        )

    print(f"[deep_research] agent={AGENT} submitting query", file=sys.stderr)
    interaction = client.interactions.create(
        agent=AGENT,
        input=query,
        background=True,
        tools=tools,
    )
    return update_state(
        job_file,
        query=query,
        agent=AGENT,
        interaction_id=interaction.id,
        remote_status=interaction_status(interaction),
        worker_pid=os.getpid(),
        worker_status="running",
        started_at=state.get("started_at", now_iso()),
        last_checked_at=now_iso(),
        last_error="",
    )


def run_worker(
    client: Any, query: str, job_file: Path, max_wait_seconds: int
) -> int:
    state = create_or_resume(client, query, job_file)
    started = time.monotonic()

    try:
        while True:
            state = refresh_once(client, job_file)
            status = state.get("remote_status", "unknown")
            elapsed = int(time.monotonic() - started)
            print(
                f"[deep_research] status={status} elapsed={elapsed}s "
                f"interaction={state.get('interaction_id', '')}",
                file=sys.stderr,
            )
            if status in TERMINAL_STATUSES:
                break
            if max_wait_seconds and elapsed >= max_wait_seconds:
                update_state(
                    job_file,
                    worker_status="timed_out",
                    last_error=(
                        f"Local wait exceeded {max_wait_seconds}s; remote interaction "
                        "is still resumable."
                    ),
                )
                print(
                    f"[deep_research] local timeout; resume job {job_file}",
                    file=sys.stderr,
                )
                return 3
            time.sleep(POLL_SECONDS)
    except BaseException as error:
        update_state(
            job_file,
            worker_status="interrupted",
            last_error=f"{type(error).__name__}: {error}",
        )
        raise

    if state.get("remote_status") != "completed":
        print(
            f"Deep Research failed: status={state.get('remote_status')} "
            f"error={state.get('last_error', '')}",
            file=sys.stderr,
        )
        return 1

    print(str(ROOT / state["report_path"]))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query", nargs="?", help="Research query")
    parser.add_argument("--job-file", type=Path, help="Persistent job JSON path")
    parser.add_argument(
        "--max-wait-seconds", type=int, default=MAX_WAIT_SECONDS
    )
    parser.add_argument(
        "--status-only", action="store_true", help="Refresh state once and exit"
    )
    parser.add_argument(
        "--cancel", action="store_true", help="Cancel the remote interaction"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    state = load_state(args.job_file) if args.job_file else {}
    query = args.query or state.get("query")
    if not query:
        print("A query or an existing --job-file is required", file=sys.stderr)
        return 2

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY is not configured (set it in backend/.env)", file=sys.stderr)
        return 2

    try:
        from google import genai
    except ImportError:
        print("Install google-genai first: pip install google-genai", file=sys.stderr)
        return 2

    job_file = (args.job_file or default_job_file(query)).resolve()
    client = genai.Client(api_key=api_key)

    if args.cancel:
        interaction_id = load_state(job_file).get("interaction_id")
        if not interaction_id:
            print(f"Job has no interaction_id: {job_file}", file=sys.stderr)
            return 2
        interaction = client.interactions.cancel(interaction_id)
        state = update_state(
            job_file,
            remote_status=interaction_status(interaction),
            worker_status="cancelled",
            cancelled_at=now_iso(),
        )
        print(json.dumps(state, ensure_ascii=False))
        return 0

    if args.status_only:
        state = refresh_once(client, job_file)
        print(json.dumps(state, ensure_ascii=False))
        return 0

    return run_worker(client, query, job_file, max(0, args.max_wait_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
