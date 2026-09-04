# v2.0.24 Baseline v2 preflight regression

The v2.0.24 release package must accept the observed PostgreSQL preflight state where the Database Baseline v2 identity is correct, no tables are missing, the upgrade ledger is present and complete at version 5/latest 5, no upgrades are pending, and only the consolidated baseline checksum differs from the target release.

The release builder performs this exact classifier regression before producing artifacts.
