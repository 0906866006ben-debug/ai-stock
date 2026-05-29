import sys
import os
import tempfile

# Ensure the project root (/home/benchang/project/ai-stock) is in sys.path
# so that `import backend.app.services...` resolves correctly.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

# Isolate the on-disk file cache so tests never read/write the real cache dir
# (prevents cross-run staleness in screening/analysis tests).
os.environ.setdefault("AISTOCK_CACHE_DIR", os.path.join(tempfile.gettempdir(), "aistock_test_cache"))

# Keep tests hermetic: force the FinMind token empty so the live-FinMind fallback
# (build_live_inputs/query_finmind) never makes a network call during tests.
os.environ["FINMIND_API_KEY"] = ""
os.environ["FINMIND_TOKEN"] = ""
# Disable the live Google-News fetch in get_tw_news (keyless → would otherwise
# hit the network in tests).
os.environ["AISTOCK_DISABLE_LIVE_NEWS"] = "1"
