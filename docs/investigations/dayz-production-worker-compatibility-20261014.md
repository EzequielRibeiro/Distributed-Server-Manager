# Production worker compatibility review

Read-only review on 2026-10-14. Production maintenance_worker.py SHA256: 53ce40a5d56adcc645da61c87bb0c48d33a03478b86ef0cc63304c8a119e0b3c (419 lines).

BLOCKER: do not replace production worker with current branch file. Branch drops existing production safeguards in _wait_native_shutdown: expected shutdown clock derived from native generated_at and deadline_minutes, extra termination grace period, and completed stopped-probe priority over timeout. The branch also modifies _advance. Reconcile both methods with production semantics, add regressions, then rerun integration tests. No production changes authorized.
