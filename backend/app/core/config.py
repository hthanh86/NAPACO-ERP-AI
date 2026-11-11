import json
from pathlib import Path

# Shared schema for the Python adapter and retained JavaScript business logic.
LEGACY_CONFIG = json.loads(Path(__file__).with_name('legacy_schema.json').read_text())
