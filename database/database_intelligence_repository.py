#!/usr/bin/env python3
"""DB1-DB6 backend-neutral database intelligence read model."""

from __future__ import annotations

import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from database_intelligence_schema import database_intelligence_ddl


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        number = float(value or 0)
        return number if math.isfinite(number) else 0.0
    except (TypeError, ValueError):
        return 0.0


class DatabaseIntelligenceRepository:
    def __init__(self, backend):
        self.backend = backend
        self.name = str(backend.name or "").lower()
        self.ph = "?" if self.name == "sqlite" else "%s"

    def initialize(self) -> None:
        self.backend.initialize()

    def _execute(self, connection, sql: str, params: tuple[Any, ...] = ()):
        if self.name == "mysql":
            cursor = connection.cursor(dictionary=True)
            cursor.execute(sql, params)
            return cursor
        return connection.execute(sql, params)

    def _rows(self, connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        cursor = self._execute(connection, sql, params)
        try:
            return [dict(row) for row in cursor.fetchall()]
        finally:
            try:
                cursor.close()
            except Exception:
                pass

    def _one(self, connection, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
        rows = self._rows(connection, sql, params)
        return rows[0] if rows else {}

    def _ensure_snapshot_schema(self, connection) -> None:
        ddl = database_intelligence_ddl(self.name)
        if self.name == "sqlite":
            connection.executescript(ddl)
        elif self.name == "mysql":
            import mysql_engine
            mysql_engine._execute_script(connection, ddl)
        else:
            connection.execute(ddl)

    def health(self) -> dict[str, Any]:
        started = datetime.now(timezone.utc)
        backend_health = dict(self.backend.health_check() or {})
        backend_status = dict(self.backend.status() or {})
        with self.backend.connect() as connection:
            if self.name == "postgresql":
                db = self._one(connection, """
                    SELECT pg_database_size(current_database()) AS database_size_bytes,
                           current_database() AS database_name,
                           current_setting('server_version') AS server_version
                """)
                connections = self._one(connection, """
                    SELECT COUNT(*) AS active_connections,
                           current_setting('max_connections')::int AS max_connections
                    FROM pg_stat_activity WHERE datname=current_database()
                """)
                longq = self._one(connection, """
                    SELECT COUNT(*) FILTER (WHERE state='active' AND now()-query_start > interval '5 seconds') AS long_queries,
                           COALESCE(MAX(EXTRACT(EPOCH FROM (now()-query_start)))
                             FILTER (WHERE state='active'),0) AS max_active_seconds
                    FROM pg_stat_activity WHERE datname=current_database()
                """)
                locks = self._one(connection, "SELECT COUNT(*) AS waiting_locks FROM pg_locks WHERE NOT granted")
            elif self.name == "mysql":
                db = self._one(connection, """
                    SELECT DATABASE() AS database_name, VERSION() AS server_version,
                           COALESCE(SUM(data_length+index_length),0) AS database_size_bytes
                    FROM information_schema.tables WHERE table_schema=DATABASE()
                """)
                connections = self._one(connection, "SHOW STATUS LIKE 'Threads_connected'")
                maximum = self._one(connection, "SHOW VARIABLES LIKE 'max_connections'")
                connections = {
                    "active_connections": _safe_int(connections.get("Value")),
                    "max_connections": _safe_int(maximum.get("Value")),
                }
                try:
                    longq = self._one(connection, """
                        SELECT COUNT(*) AS long_queries, COALESCE(MAX(TIME),0) AS max_active_seconds
                        FROM information_schema.processlist
                        WHERE COMMAND<>'Sleep' AND TIME>5 AND ID<>CONNECTION_ID()
                    """)
                except Exception:
                    longq = {"long_queries": 0, "max_active_seconds": 0}
                locks = {"waiting_locks": 0}
            else:
                path = Path(self.backend.config.database).expanduser().resolve()
                page = self._one(connection, "PRAGMA page_count")
                size = path.stat().st_size if path.exists() else _safe_int(next(iter(page.values()), 0))
                version = self._one(connection, "SELECT sqlite_version() AS server_version")
                db = {"database_name": path.name, "database_size_bytes": size, **version}
                connections = {"active_connections": 1, "max_connections": 1}
                longq = {"long_queries": 0, "max_active_seconds": 0}
                locks = {"waiting_locks": 0}

        active = _safe_int(connections.get("active_connections"))
        maximum = max(1, _safe_int(connections.get("max_connections")))
        long_queries = _safe_int(longq.get("long_queries"))
        waiting_locks = _safe_int(locks.get("waiting_locks"))
        utilization = 0.0 if self.name == "sqlite" else round(active * 100.0 / maximum, 2)
        health = "critical" if waiting_locks > 5 or utilization >= 95 else "degraded" if long_queries or waiting_locks or utilization >= 80 else "healthy"
        elapsed = (datetime.now(timezone.utc) - started).total_seconds() * 1000
        return {
            "schema_version": 1,
            "kind": "CapivaraDatabaseHealth",
            "backend": self.name,
            "health": health,
            "database_name": db.get("database_name") or self.backend.config.database,
            "server_version": db.get("server_version"),
            "database_size_bytes": _safe_int(db.get("database_size_bytes")),
            "connections": {"active": active, "max": maximum, "utilization_pct": utilization},
            "long_queries": long_queries,
            "max_active_seconds": round(_safe_float(longq.get("max_active_seconds")), 3),
            "waiting_locks": waiting_locks,
            "schema_version_current": _safe_int(backend_status.get("current_migration")),
            "backend_health": backend_health.get("health") or backend_health.get("status"),
            "latency_ms": round(elapsed, 2),
            "generated_at": _now(),
        }

    def storage(self, limit: int = 50) -> dict[str, Any]:
        bounded = max(1, min(int(limit), 500))
        with self.backend.connect() as connection:
            if self.name == "postgresql":
                rows = self._rows(connection, """
                    SELECT relname AS table_name,
                           n_live_tup AS row_count,
                           n_dead_tup AS dead_rows,
                           n_tup_ins AS insert_count,
                           n_tup_upd AS update_count,
                           n_tup_del AS delete_count,
                           pg_relation_size(relid) AS data_size_bytes,
                           pg_indexes_size(relid) AS index_size_bytes,
                           pg_total_relation_size(relid) AS total_size_bytes,
                           last_autovacuum, last_autoanalyze
                    FROM pg_stat_user_tables
                    ORDER BY pg_total_relation_size(relid) DESC
                    LIMIT %s
                """, (bounded,))
            elif self.name == "mysql":
                rows = self._rows(connection, """
                    SELECT table_name,
                           COALESCE(table_rows,0) AS row_count,
                           0 AS dead_rows,
                           0 AS insert_count,
                           0 AS update_count,
                           0 AS delete_count,
                           COALESCE(data_length,0) AS data_size_bytes,
                           COALESCE(index_length,0) AS index_size_bytes,
                           COALESCE(data_length+index_length,0) AS total_size_bytes,
                           NULL AS last_autovacuum,
                           NULL AS last_autoanalyze
                    FROM information_schema.tables
                    WHERE table_schema=DATABASE()
                    ORDER BY total_size_bytes DESC
                    LIMIT %s
                """, (bounded,))
            else:
                names = self._rows(connection, "SELECT name AS table_name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
                rows = []
                for item in names[:1000]:
                    name = str(item["table_name"]).replace('"', '""')
                    try:
                        count = self._one(connection, f'SELECT COUNT(*) AS row_count FROM "{name}"')
                    except Exception:
                        count = {"row_count": 0}
                    rows.append({
                        "table_name": item["table_name"],
                        "row_count": _safe_int(count.get("row_count")),
                        "dead_rows": 0,
                        "insert_count": 0,
                        "update_count": 0,
                        "delete_count": 0,
                        "data_size_bytes": 0,
                        "index_size_bytes": 0,
                        "total_size_bytes": 0,
                        "last_autovacuum": None,
                        "last_autoanalyze": None,
                    })
                rows.sort(key=lambda item: (item["row_count"], str(item["table_name"])), reverse=True)
                rows = rows[:bounded]
                path = Path(self.backend.config.database).expanduser().resolve()
                if rows:
                    rows[0]["total_size_bytes"] = path.stat().st_size if path.exists() else 0
        normalized = []
        for row in rows:
            item = dict(row)
            for key in ("row_count","dead_rows","insert_count","update_count","delete_count","data_size_bytes","index_size_bytes","total_size_bytes"):
                item[key] = _safe_int(item.get(key))
            item["index_ratio_pct"] = round(item["index_size_bytes"] * 100.0 / max(1, item["total_size_bytes"]), 2)
            item["dead_ratio_pct"] = round(item["dead_rows"] * 100.0 / max(1, item["row_count"]), 2)
            normalized.append(item)
        total = sum(item["total_size_bytes"] for item in normalized)
        return {"backend": self.name, "tables": normalized, "listed_total_bytes": total, "generated_at": _now()}

    def index_efficiency(self, limit: int = 50) -> list[dict[str, Any]]:
        bounded = max(1, min(int(limit), 500))
        with self.backend.connect() as connection:
            if self.name == "postgresql":
                rows = self._rows(connection, """
                    SELECT relname AS table_name,indexrelname AS index_name,
                           idx_scan AS scans,pg_relation_size(indexrelid) AS size_bytes
                    FROM pg_stat_user_indexes
                    ORDER BY pg_relation_size(indexrelid) DESC LIMIT %s
                """, (bounded,))
            elif self.name == "mysql":
                try:
                    rows = self._rows(connection, """
                        SELECT table_name,index_name,
                               0 AS scans,
                               COALESCE(stat_value,0) * @@innodb_page_size AS size_bytes
                        FROM mysql.innodb_index_stats
                        WHERE database_name=DATABASE() AND stat_name='size'
                        ORDER BY stat_value DESC LIMIT %s
                    """, (bounded,))
                except Exception:
                    rows = self._rows(connection, """
                        SELECT table_name,index_name,0 AS scans,0 AS size_bytes
                        FROM information_schema.statistics
                        WHERE table_schema=DATABASE()
                        GROUP BY table_name,index_name
                        ORDER BY table_name,index_name
                        LIMIT %s
                    """, (bounded,))
            else:
                rows = self._rows(connection, "SELECT tbl_name AS table_name,name AS index_name,0 AS scans,0 AS size_bytes FROM sqlite_master WHERE type='index' ORDER BY name")
        return [{
            "table_name": row.get("table_name"),
            "index_name": row.get("index_name"),
            "scans": _safe_int(row.get("scans")),
            "size_bytes": _safe_int(row.get("size_bytes")),
        } for row in rows[:bounded]]

    def observability_profile(self) -> dict[str, Any]:
        with self.backend.connect() as connection:
            total = self._one(connection, "SELECT COUNT(*) AS total FROM observability_samples")
            latest = self._one(connection, "SELECT COUNT(*) AS total FROM observability_latest")
            by_agent = self._rows(connection, "SELECT agent_id,COUNT(*) AS samples FROM observability_samples GROUP BY agent_id ORDER BY samples DESC")
            by_metric = self._rows(connection, "SELECT metric_name,COUNT(*) AS samples FROM observability_samples GROUP BY metric_name ORDER BY samples DESC")
        return {
            "historical_samples": _safe_int(total.get("total")),
            "latest_projection_rows": _safe_int(latest.get("total")),
            "by_agent": [{"agent_id": row.get("agent_id"), "samples": _safe_int(row.get("samples"))} for row in by_agent[:30]],
            "by_metric": [{"metric_name": row.get("metric_name"), "samples": _safe_int(row.get("samples"))} for row in by_metric[:30]],
        }

    def capture_snapshot(self, now: datetime | None = None) -> dict[str, Any]:
        instant = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        day = instant.date().isoformat()
        health = self.health()
        storage = self.storage(limit=500)
        rows = [{
            "snapshot_day": day,
            "table_name": "@database",
            "captured_at": instant.isoformat().replace("+00:00", "Z"),
            "backend": self.name,
            "database_size_bytes": health["database_size_bytes"],
            "row_count": 0,
            "data_size_bytes": 0,
            "index_size_bytes": 0,
            "dead_rows": 0,
            "insert_count": 0,
            "update_count": 0,
            "delete_count": 0,
            "metadata_json": json.dumps({"health": health["health"], "connections": health["connections"]}, separators=(",", ":"), sort_keys=True),
        }]
        for table in storage["tables"]:
            rows.append({
                "snapshot_day": day,
                "table_name": str(table["table_name"]),
                "captured_at": instant.isoformat().replace("+00:00", "Z"),
                "backend": self.name,
                "database_size_bytes": health["database_size_bytes"],
                "row_count": table["row_count"],
                "data_size_bytes": table["data_size_bytes"],
                "index_size_bytes": table["index_size_bytes"],
                "dead_rows": table["dead_rows"],
                "insert_count": table["insert_count"],
                "update_count": table["update_count"],
                "delete_count": table["delete_count"],
                "metadata_json": "{}",
            })
        columns = ("snapshot_day","table_name","captured_at","backend","database_size_bytes","row_count","data_size_bytes","index_size_bytes","dead_rows","insert_count","update_count","delete_count","metadata_json")
        with self.backend.transaction() as connection:
            self._ensure_snapshot_schema(connection)
            for row in rows:
                values = tuple(row[column] for column in columns)
                if self.name == "postgresql":
                    sql = f"INSERT INTO database_metrics_daily ({','.join(columns)}) VALUES ({','.join([self.ph]*len(columns))}) ON CONFLICT(snapshot_day,table_name) DO UPDATE SET captured_at=EXCLUDED.captured_at,backend=EXCLUDED.backend,database_size_bytes=EXCLUDED.database_size_bytes,row_count=EXCLUDED.row_count,data_size_bytes=EXCLUDED.data_size_bytes,index_size_bytes=EXCLUDED.index_size_bytes,dead_rows=EXCLUDED.dead_rows,insert_count=EXCLUDED.insert_count,update_count=EXCLUDED.update_count,delete_count=EXCLUDED.delete_count,metadata_json=EXCLUDED.metadata_json"
                elif self.name == "mysql":
                    sql = f"INSERT INTO database_metrics_daily ({','.join(columns)}) VALUES ({','.join([self.ph]*len(columns))}) ON DUPLICATE KEY UPDATE captured_at=VALUES(captured_at),backend=VALUES(backend),database_size_bytes=VALUES(database_size_bytes),row_count=VALUES(row_count),data_size_bytes=VALUES(data_size_bytes),index_size_bytes=VALUES(index_size_bytes),dead_rows=VALUES(dead_rows),insert_count=VALUES(insert_count),update_count=VALUES(update_count),delete_count=VALUES(delete_count),metadata_json=VALUES(metadata_json)"
                else:
                    sql = f"INSERT INTO database_metrics_daily ({','.join(columns)}) VALUES ({','.join([self.ph]*len(columns))}) ON CONFLICT(snapshot_day,table_name) DO UPDATE SET captured_at=excluded.captured_at,backend=excluded.backend,database_size_bytes=excluded.database_size_bytes,row_count=excluded.row_count,data_size_bytes=excluded.data_size_bytes,index_size_bytes=excluded.index_size_bytes,dead_rows=excluded.dead_rows,insert_count=excluded.insert_count,update_count=excluded.update_count,delete_count=excluded.delete_count,metadata_json=excluded.metadata_json"
                cursor = self._execute(connection, sql, values)
                try:
                    cursor.close()
                except Exception:
                    pass
        return {"snapshot_day": day, "rows": len(rows), "database_size_bytes": health["database_size_bytes"]}

    def growth(self, days: int = 90) -> dict[str, Any]:
        bounded = max(7, min(int(days), 365))
        with self.backend.connect() as connection:
            self._ensure_snapshot_schema(connection)
            rows = self._rows(connection, f"SELECT snapshot_day,database_size_bytes,captured_at FROM database_metrics_daily WHERE table_name={self.ph} ORDER BY snapshot_day DESC LIMIT {self.ph}", ("@database", bounded))
        rows = list(reversed(rows))
        series = [{"day": str(row.get("snapshot_day")), "database_size_bytes": _safe_int(row.get("database_size_bytes"))} for row in rows]
        deltas = [series[i]["database_size_bytes"] - series[i-1]["database_size_bytes"] for i in range(1, len(series))]
        avg = int(statistics.fmean(deltas)) if deltas else 0
        current = series[-1]["database_size_bytes"] if series else self.health()["database_size_bytes"]
        forecasts = {str(horizon): max(0, current + avg * horizon) for horizon in (7, 30, 90)}
        return {"days": bounded, "series": series, "average_daily_growth_bytes": avg, "forecast_bytes": forecasts}

    def analyze(self) -> dict[str, Any]:
        targets = ["observability_samples", "observability_latest", "universal_events", "activity_audit", "database_metrics_daily"]
        completed = []
        with self.backend.connect() as connection:
            for table in targets:
                try:
                    if self.name == "postgresql":
                        connection.execute(f'ANALYZE "{table}"')
                    elif self.name == "mysql":
                        cursor = connection.cursor()
                        try:
                            cursor.execute(f"ANALYZE TABLE {table}")
                        finally:
                            cursor.close()
                    else:
                        connection.execute(f'ANALYZE "{table}"')
                    completed.append(table)
                except Exception:
                    continue
            if self.name == "sqlite":
                connection.commit()
        return {"action": "analyze", "tables": completed, "completed": len(completed)}

    def insights(self) -> list[dict[str, Any]]:
        health = self.health()
        storage = self.storage(limit=100)
        profile = self.observability_profile()
        tables = storage["tables"]
        total = max(1, health["database_size_bytes"])
        insights: list[dict[str, Any]] = []
        if tables:
            top = tables[0]
            share = round(top["total_size_bytes"] * 100.0 / total, 1)
            insights.append({"severity": "info" if share < 50 else "warning", "code": "storage_concentration", "title": "Concentração de armazenamento", "message": f"{top['table_name']} representa aproximadamente {share}% do banco.", "value": share})
        historical = profile["historical_samples"]
        latest = profile["latest_projection_rows"]
        ratio = round(historical / max(1, latest), 1)
        insights.append({"severity": "warning" if ratio > 100 else "info", "code": "history_latest_ratio", "title": "Histórico versus estado atual", "message": f"Há {ratio} amostras históricas para cada linha da projeção atual.", "value": ratio})
        if profile["by_agent"]:
            leader = profile["by_agent"][0]
            pct = round(leader["samples"] * 100.0 / max(1, historical), 1)
            insights.append({"severity": "info", "code": "top_data_producer", "title": "Maior produtor de telemetria", "message": f"{leader['agent_id']} responde por aproximadamente {pct}% das amostras históricas.", "value": pct})
        dead = [row for row in tables if row["dead_ratio_pct"] >= 20]
        if dead:
            insights.append({"severity": "warning", "code": "dead_tuple_pressure", "title": "Pressão de manutenção", "message": f"{len(dead)} tabela(s) apresentam pelo menos 20% de dead tuples.", "value": len(dead)})
        if health["long_queries"] or health["waiting_locks"]:
            insights.append({"severity": "warning", "code": "database_contention", "title": "Contenção detectada", "message": f"{health['long_queries']} consulta(s) longa(s) e {health['waiting_locks']} lock(s) aguardando.", "value": health["waiting_locks"]})
        if not insights:
            insights.append({"severity": "info", "code": "healthy_baseline", "title": "Banco saudável", "message": "Nenhum desvio relevante foi identificado no snapshot atual.", "value": 0})
        return insights

    def capabilities(self) -> dict[str, Any]:
        return {
            "backend": self.name,
            "health": True,
            "storage": True,
            "growth_snapshots": True,
            "datamine": True,
            "retention_control": True,
            "analyze": True,
            "index_scan_stats": self.name == "postgresql",
            "lock_wait_stats": self.name == "postgresql",
            "query_duration_stats": self.name in {"postgresql", "mysql"},
            "precise_table_bytes": self.name in {"postgresql", "mysql"},
            "historical_snapshots": True,
            "physical_reclaim_action": False,
        }


__all__ = ["DatabaseIntelligenceRepository"]
