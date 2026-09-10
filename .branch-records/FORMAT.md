# Branch registry, schema 1

`BRANCHES.md` is JSON. `changes` retains business deltas; `records` maps task IDs
to their `state.json`. `active` lists current tasks and `pending` lists operation
references as `task/event`. Events are JSONL with unique IDs within each task.
Request references use the same `task/event` notation in the index and a local
event ID within that task's events. File evidence uses repository-relative paths.

Dates use Asia/Singapore (UTC+08:00). `date` is the first requirement date;
`implementedAt`, `integratedAt`, and `deployedAt` are distinct evidenced milestones.
Null means unknown or not yet evidenced, not a successful operation.
Task state holds current requirements; request events preserve their provenance.
Operation `after` fields are intentions. Successful operations require live Git
verification or a checkpoint referencing the observed result.

Validate using `python scripts/validate_registry.py` before committing changes.
