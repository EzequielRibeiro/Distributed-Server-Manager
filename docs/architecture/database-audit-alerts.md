# Database-backed audit, events, alerts, and notifications

Status: implementation in progress.

This branch removes file-backed operational state from the audit/alert path. Durable operator activity, operational events, alert lifecycle, and notification delivery state are stored in the configured Capivara database. No JSON/text-file fallback or legacy compatibility adapter is permitted.
