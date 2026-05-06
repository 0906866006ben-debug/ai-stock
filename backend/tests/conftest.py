import sys
import os

# Ensure the project root (/home/benchang/project/ai-stock) is in sys.path
# so that `import backend.app.services...` resolves correctly.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))
