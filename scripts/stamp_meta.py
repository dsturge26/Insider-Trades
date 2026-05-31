#!/usr/bin/env python3
"""Write data/last_updated.json reflecting whether congress data is live or seed."""
import json, os
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(ROOT, "data", "congress_trades.json")) as f:
    c = json.load(f)
live = not c.get("is_sample", True)
meta = {
    "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "congress_source": c.get("source", ""),
    "live": live,
    "message": "" if live else "Seed data. Add an FMP_API_KEY secret and run the 'Update data' Action to go live.",
}
with open(os.path.join(ROOT, "data", "last_updated.json"), "w") as f:
    json.dump(meta, f, indent=1)
print("live =", live)
