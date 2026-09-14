"""Validate this repository's JSON branch registry and local references."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
ledger = json.loads((root / "BRANCHES.md").read_text(encoding="utf-8-sig"))
events = {}
for task, filename in ledger["records"].items():
    # Registry paths are shared by Windows and Linux CI. Windows accepts backslashes
    # locally, but POSIX treats them as literal filename characters.
    assert "\\" not in filename, f"Use forward slashes in registry path: {filename}"
    path = root / filename
    state = json.loads(path.read_text(encoding="utf-8-sig"))
    for field in ("purpose", "requirements", "constraints", "acceptance", "status", "integration", "evidence", "next"):
        assert field in state, (task, field)
    assert state["status"] in ("active", "blocked", "complete", "unknown")
    assert state["integration"] in ("unmerged", "verified", "unknown", "not_applicable")
    entries = [json.loads(line) for line in path.with_name("events.jsonl").read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    assert len({e["id"] for e in entries}) == len(entries), task
    events[task] = {e["id"]: e for e in entries}
    for event in entries:
        if "request" in event:
            assert events[task][event["request"]]["type"] == "user_request"
        for previous in event.get("supersedes", []):
            assert previous in events[task]
assert set(ledger["active"]) <= set(events)
assert len({c["id"] for c in ledger["changes"]}) == len(ledger["changes"])
for change in ledger["changes"]:
    task, event = change["request"].split("/", 1)
    assert events[task][event]["type"] == "user_request"
    for path in change["evidence"]:
        assert "\\" not in path, f"Use forward slashes in evidence path: {path}"
        assert (root / path).exists(), path
for reference in ledger["pending"]:
    task, event = reference.split("/", 1)
    operation = events[task][event]
    assert operation["type"] == "operation"
    for field in ("operation", "reason", "source", "before", "after"):
        assert operation.get(field), reference
print("Registry valid")
