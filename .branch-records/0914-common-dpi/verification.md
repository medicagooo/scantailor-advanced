# Common input DPI checkpoint

Repository/worktree: D:/proj/scantailor-advanced; branch master; starting commit de1bcd069fcf11b09a3e6afc6e6e055e65f86464. Initially clean. Existing committed manual-release change remains in master and will accompany the requested normal push; it was not edited in this task.

Implemented: input/render DPI before output DPI; presets 150/300/600 and custom 72..1200; actual asymmetric/global values and page-rule notice; apply/cancel; shared Controller persistence and PDF render options. Three locale catalogs and MENU documentation updated. Existing page rules remain in the current task; portable preferences retain existing behavior of omitting source-specific rules.

Verification: 11 workbench tests passed, then the added image/PDF job-routing test passed (12 total). All 12 language tests passed with Python -X utf8. The initial language run used Windows cp1252 and could not read UTF-8 fixtures; UTF-8 invocation resolved it without source changes. Routing test used PyMuPDF from existing bin/ScanTailor-CLI-3.4.0-win64/python/Lib/site-packages through process-local PYTHONPATH because system Python lacks it.

Review: one independent review subagent examined the uncommitted changes, menu indices, persistence, routing and locales; no actionable defects found. Dedicated Bugbot tool unavailable; fallback was disclosed. No processing algorithm changes or new distribution package.

Publication: not yet pushed at this checkpoint. Next action: commit only this task's files including op-push intent, then git push origin master, then verify remote refs/heads/master equals HEAD. User requested skipping extra pre-push checks; no manual CI or release dispatch authorized.

Implementation committed to local master at ec92c6f9c8c83177003d423651ca822db0657079. HTTPS push rejected without remote changes because OAuth lacks workflow scope for the earlier release workflow commit. Existing SSH authentication verified; next execute predeclared op-push-ssh and verify remote SHA. No remote configuration change needed.
