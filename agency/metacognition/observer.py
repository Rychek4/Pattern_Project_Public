"""
MemoryObserver: Statistical Signal Detection for Memory Metacognition

Adapted from memory_observer.py (project root) for server-side execution.
Uses the project's get_database() pattern instead of direct sqlite3 connections.

Runs as a pre-pass before the reflection pulse (Claude Opus 4.6).
No LLM calls. Pure SQL + numpy against the memory store.

Signal tiers:
  Tier 1 (core):  Rate anomalies, importance drift, decay distribution shifts, memory type shifts
  Tier 2 (structural): Novel clusters, retrieval blind spots
  Tier 3 (refinement):  Embedding density, temporal periodicity, topic co-occurrence
"""

import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from enum import Enum

from core.database import get_database
from core.logger import log_info, log_error


class SignalDirection(Enum):
    INCREASE = "increase"
    DECREASE = "decrease"
    STABLE = "stable"
    NOVEL = "novel"
    DORMANT = "dormant"
    UNREACHABLE = "unreachable"
    DENSE = "dense"
    SPARSE = "sparse"
    PERIODIC_BREAK = "periodic_break"
    ERROR = "error"


@dataclass
class Signal:
    """A single observation from the statistical pass."""
    signal_type: str
    direction: SignalDirection
    magnitude: float
    description: str
    representatives: List[str] = field(default_factory=list)

    def to_report_block(self) -> str:
        lines = [
            f"SIGNAL: {self.signal_type}",
            f"  Direction: {self.direction.value}",
            f"  Magnitude: {self.magnitude:.3f}",
            f"  Observation: {self.description}",
        ]
        for i, rep in enumerate(self.representatives, 1):
            lines.append(f"  Representative {i}: \"{rep}\"")
        return "\n".join(lines)


class MemoryObserver:
    """
    Monitors the memory store for structural signals that the retrieval
    pipeline cannot surface. Produces a signal report consumed by the
    reflection pulse.

    Uses get_database() for all queries — no direct connection management.
    """

    def __init__(
        self,
        rolling_window: int = 20,
        rate_z_threshold: float = 1.5,
        novelty_sim_threshold: float = 0.50,
        dormancy_multiplier: float = 3.0,
        blind_spot_days: int = 30,
        blind_spot_importance: float = 0.7,
        density_high_threshold: float = 0.85,
        density_low_threshold: float = 0.45,
    ):
        self.rolling_window = rolling_window
        self.rate_z_threshold = rate_z_threshold
        self.novelty_sim_threshold = novelty_sim_threshold
        self.dormancy_multiplier = dormancy_multiplier
        self.blind_spot_days = blind_spot_days
        self.blind_spot_importance = blind_spot_importance
        self.density_high_threshold = density_high_threshold
        self.density_low_threshold = density_low_threshold
        self._bridge_col_exists: Optional[bool] = None

    def _db(self):
        """Get the project database instance."""
        return get_database()

    def _execute(self, sql: str, params: tuple = (), fetch: bool = True):
        """Execute a query through the project database."""
        return self._db().execute(sql, params, fetch=fetch)

    @staticmethod
    def _deserialize_embedding(blob: bytes) -> Optional[np.ndarray]:
        from core.embeddings import safe_bytes_to_embedding
        return safe_bytes_to_embedding(blob)

    # -------------------------------------------------------------------
    # Store overview
    # -------------------------------------------------------------------

    def get_store_stats(self) -> dict:
        """Basic inventory of the memory store."""
        stats = {}

        rows = self._execute(
            "SELECT memory_category, COUNT(*) as cnt FROM memories GROUP BY memory_category"
        )
        stats["by_category"] = {r["memory_category"]: r["cnt"] for r in rows}
        stats["total"] = sum(stats["by_category"].values())

        rows = self._execute(
            "SELECT memory_type, COUNT(*) as cnt FROM memories WHERE memory_type IS NOT NULL GROUP BY memory_type"
        )
        stats["by_type"] = {r["memory_type"]: r["cnt"] for r in rows}

        rows = self._execute(
            "SELECT decay_category, COUNT(*) as cnt FROM memories GROUP BY decay_category"
        )
        stats["by_decay"] = {r["decay_category"]: r["cnt"] for r in rows}

        row = self._execute(
            "SELECT MIN(created_at) as oldest, MAX(created_at) as newest FROM memories"
        )
        if row and row[0]["oldest"] is not None:
            stats["oldest_memory"] = row[0]["oldest"]
            stats["newest_memory"] = row[0]["newest"]
        else:
            stats["oldest_memory"] = None
            stats["newest_memory"] = None

        row = self._execute(
            "SELECT COUNT(DISTINCT source_session_id) as cnt FROM memories WHERE source_session_id IS NOT NULL"
        )
        stats["source_sessions"] = row[0]["cnt"] if row else 0

        row = self._execute("SELECT AVG(importance) as avg_imp FROM memories")
        avg = row[0]["avg_imp"] if row else None
        stats["avg_importance"] = round(avg, 3) if avg is not None else 0

        return stats

    def _format_store_stats(self, stats: dict) -> str:
        oldest = stats.get('oldest_memory') or 'N/A'
        newest = stats.get('newest_memory') or 'N/A'
        lines = [
            f"  Total memories: {stats['total']}",
            f"  By category: {stats['by_category']}",
            f"  By type: {stats['by_type']}",
            f"  By decay: {stats['by_decay']}",
            f"  Temporal range: {oldest} to {newest}",
            f"  Source sessions: {stats.get('source_sessions', 0)}",
            f"  Average importance: {stats['avg_importance']}",
        ]
        return "\n".join(lines)

    # -------------------------------------------------------------------
    # TIER 1: Core statistical signals
    # -------------------------------------------------------------------

    def detect_rate_anomalies(self) -> List[Signal]:
        """Z-score on memory creation rate per session, by category."""
        signals = []

        for category in ["episodic", "factual"]:
            rows = self._execute("""
                SELECT source_session_id, COUNT(*) as cnt
                FROM memories
                WHERE memory_category = ?
                AND source_session_id IS NOT NULL
                GROUP BY source_session_id
                ORDER BY source_session_id DESC
                LIMIT ?
            """, (category, self.rolling_window + 1))

            if len(rows) < 4:
                continue

            current_session_id = rows[0]["source_session_id"]
            current_count = rows[0]["cnt"]
            historical = np.array([r["cnt"] for r in rows[1:]], dtype=float)

            mean = np.mean(historical)
            std = np.std(historical)
            if std == 0:
                continue

            z = (current_count - mean) / std
            if abs(z) < self.rate_z_threshold:
                continue

            direction = SignalDirection.INCREASE if z > 0 else SignalDirection.DECREASE

            reps = self._execute("""
                SELECT content FROM memories
                WHERE memory_category = ? AND source_session_id = ?
                ORDER BY importance DESC LIMIT 3
            """, (category, current_session_id))

            signals.append(Signal(
                signal_type=f"RATE_{category.upper()}",
                direction=direction,
                magnitude=abs(z),
                description=(
                    f"{category.title()} memory creation at {current_count} "
                    f"for session {current_session_id} "
                    f"(baseline {mean:.1f} +/- {std:.1f}, z={z:+.2f})"
                ),
                representatives=[r["content"] for r in reps],
            ))

        return signals

    def detect_importance_drift(self) -> List[Signal]:
        """Tracks mean importance per session against a rolling baseline."""
        signals = []

        rows = self._execute("""
            SELECT source_session_id,
                   AVG(importance) as mean_imp,
                   COUNT(*) as cnt
            FROM memories
            WHERE source_session_id IS NOT NULL
            GROUP BY source_session_id
            ORDER BY source_session_id DESC
            LIMIT ?
        """, (self.rolling_window + 1,))

        if len(rows) < 4:
            return signals

        current_session_id = rows[0]["source_session_id"]
        current_mean = rows[0]["mean_imp"]
        historical_means = np.array([r["mean_imp"] for r in rows[1:]], dtype=float)

        h_mean = np.mean(historical_means)
        h_std = np.std(historical_means)

        if h_std > 0:
            z = (current_mean - h_mean) / h_std
            if abs(z) > self.rate_z_threshold:
                direction = SignalDirection.INCREASE if z > 0 else SignalDirection.DECREASE

                reps = self._execute("""
                    SELECT content FROM memories
                    WHERE source_session_id = ?
                    ORDER BY importance DESC LIMIT 2
                """, (current_session_id,))

                signals.append(Signal(
                    signal_type="IMPORTANCE_DRIFT",
                    direction=direction,
                    magnitude=abs(z),
                    description=(
                        f"Mean importance {current_mean:.3f} for session "
                        f"{current_session_id} "
                        f"(baseline {h_mean:.3f} +/- {h_std:.3f}, z={z:+.2f})"
                    ),
                    representatives=[r["content"] for r in reps],
                ))

        # Within-session variance
        cycle_scores = self._execute("""
            SELECT importance FROM memories WHERE source_session_id = ?
        """, (current_session_id,))

        if len(cycle_scores) >= 3:
            variance = float(np.var([r["importance"] for r in cycle_scores]))

            hist_vars = []
            for row in rows[1:]:
                hv = self._execute("""
                    SELECT importance FROM memories WHERE source_session_id = ?
                """, (row["source_session_id"],))
                if len(hv) >= 2:
                    hist_vars.append(float(np.var([r["importance"] for r in hv])))

            if hist_vars:
                var_mean = np.mean(hist_vars)
                var_std = np.std(hist_vars)
                if var_std > 0:
                    var_z = (variance - var_mean) / var_std
                    if var_z > self.rate_z_threshold:
                        extremes = self._execute("""
                            SELECT content, importance FROM memories
                            WHERE source_session_id = ?
                            ORDER BY importance DESC
                        """, (current_session_id,))

                        reps = []
                        if extremes:
                            reps.append(
                                f"[imp={extremes[0]['importance']:.2f}] "
                                f"{extremes[0]['content']}"
                            )
                        if len(extremes) > 1:
                            reps.append(
                                f"[imp={extremes[-1]['importance']:.2f}] "
                                f"{extremes[-1]['content']}"
                            )

                        signals.append(Signal(
                            signal_type="IMPORTANCE_VARIANCE",
                            direction=SignalDirection.INCREASE,
                            magnitude=var_z,
                            description=(
                                f"Within-session importance variance "
                                f"{variance:.4f} "
                                f"(baseline {var_mean:.4f}, z={var_z:+.2f}) "
                                f"— session mixed significant and trivial content"
                            ),
                            representatives=reps,
                        ))

        return signals

    def detect_decay_distribution_shift(self) -> List[Signal]:
        """Compares decay category ratios between recent and historical sessions."""
        signals = []

        sessions = self._execute("""
            SELECT DISTINCT source_session_id
            FROM memories
            WHERE source_session_id IS NOT NULL
            ORDER BY source_session_id DESC
            LIMIT ?
        """, (self.rolling_window,))

        if len(sessions) < 6:
            return signals

        recent_ids = [s["source_session_id"] for s in sessions[:5]]
        historical_ids = [s["source_session_id"] for s in sessions[5:]]
        categories = ["permanent", "standard", "ephemeral"]

        def get_distribution(session_ids: list) -> np.ndarray:
            placeholders = ",".join("?" * len(session_ids))
            counts = []
            for cat in categories:
                row = self._execute(
                    f"SELECT COUNT(*) as cnt FROM memories WHERE decay_category = ? AND source_session_id IN ({placeholders})",
                    (cat, *session_ids)
                )
                counts.append(row[0]["cnt"] if row else 0)
            total = sum(counts)
            if total == 0:
                return np.zeros(len(categories))
            return np.array(counts, dtype=float) / total

        recent_dist = get_distribution(recent_ids)
        historical_dist = get_distribution(historical_ids)
        shift = np.sum(np.abs(recent_dist - historical_dist))

        if shift > 0.15:
            diffs = recent_dist - historical_dist
            max_idx = int(np.argmax(np.abs(diffs)))
            shifted_cat = categories[max_idx]
            direction = SignalDirection.INCREASE if diffs[max_idx] > 0 else SignalDirection.DECREASE

            placeholders = ",".join("?" * len(recent_ids))
            reps = self._execute(
                f"SELECT content FROM memories WHERE decay_category = ? AND source_session_id IN ({placeholders}) ORDER BY importance DESC LIMIT 3",
                (shifted_cat, *recent_ids)
            )

            dist_str = ", ".join(
                f"{cat}: {recent_dist[i]:.0%} (was {historical_dist[i]:.0%})"
                for i, cat in enumerate(categories)
            )

            signals.append(Signal(
                signal_type="DECAY_DISTRIBUTION",
                direction=direction,
                magnitude=float(shift),
                description=(
                    f"Decay distribution shifted: {dist_str}. "
                    f"Largest: {shifted_cat} ({diffs[max_idx]:+.0%})"
                ),
                representatives=[r["content"] for r in reps],
            ))

        return signals

    def detect_memory_type_shift(self) -> List[Signal]:
        """Tracks shifts in memory_type distribution."""
        signals = []

        sessions = self._execute("""
            SELECT DISTINCT source_session_id
            FROM memories
            WHERE source_session_id IS NOT NULL
            ORDER BY source_session_id DESC
            LIMIT ?
        """, (self.rolling_window,))

        if len(sessions) < 6:
            return signals

        recent_ids = [s["source_session_id"] for s in sessions[:5]]
        historical_ids = [s["source_session_id"] for s in sessions[5:]]
        types = ["fact", "preference", "event", "reflection", "observation"]

        def get_distribution(session_ids: list) -> np.ndarray:
            placeholders = ",".join("?" * len(session_ids))
            counts = []
            for mtype in types:
                row = self._execute(
                    f"SELECT COUNT(*) as cnt FROM memories WHERE memory_type = ? AND source_session_id IN ({placeholders})",
                    (mtype, *session_ids)
                )
                counts.append(row[0]["cnt"] if row else 0)
            total = sum(counts)
            if total == 0:
                return np.zeros(len(types))
            return np.array(counts, dtype=float) / total

        recent_dist = get_distribution(recent_ids)
        historical_dist = get_distribution(historical_ids)
        shift = np.sum(np.abs(recent_dist - historical_dist))

        if shift > 0.20:
            diffs = recent_dist - historical_dist
            max_idx = int(np.argmax(np.abs(diffs)))
            shifted_type = types[max_idx]
            direction = SignalDirection.INCREASE if diffs[max_idx] > 0 else SignalDirection.DECREASE

            placeholders = ",".join("?" * len(recent_ids))
            reps = self._execute(
                f"SELECT content FROM memories WHERE memory_type = ? AND source_session_id IN ({placeholders}) ORDER BY importance DESC LIMIT 3",
                (shifted_type, *recent_ids)
            )

            dist_str = ", ".join(
                f"{t}: {recent_dist[i]:.0%} (was {historical_dist[i]:.0%})"
                for i, t in enumerate(types)
            )

            signals.append(Signal(
                signal_type="MEMORY_TYPE_SHIFT",
                direction=direction,
                magnitude=float(shift),
                description=(
                    f"Memory type distribution shifted: {dist_str}. "
                    f"Largest: {shifted_type} ({diffs[max_idx]:+.0%})"
                ),
                representatives=[r["content"] for r in reps],
            ))

        return signals

    # -------------------------------------------------------------------
    # TIER 2: Structural signals
    # -------------------------------------------------------------------

    def detect_novel_clusters(self, recent_session_count: int = 3) -> List[Signal]:
        """Find memories forming in novel embedding territory."""
        signals = []

        boundary_row = self._execute("""
            SELECT DISTINCT source_session_id FROM memories
            WHERE source_session_id IS NOT NULL
            ORDER BY source_session_id DESC
            LIMIT 1 OFFSET ?
        """, (recent_session_count,))

        if not boundary_row:
            return signals

        boundary_session = boundary_row[0]["source_session_id"]

        new_rows = self._execute("""
            SELECT id, content, embedding FROM memories
            WHERE source_session_id > ? AND embedding IS NOT NULL
        """, (boundary_session,))

        if not new_rows:
            return signals

        hist_rows = self._execute("""
            SELECT embedding FROM memories
            WHERE source_session_id <= ? AND embedding IS NOT NULL
            ORDER BY importance DESC LIMIT 500
        """, (boundary_session,))

        if not hist_rows:
            return signals

        deserialized = [self._deserialize_embedding(r["embedding"]) for r in hist_rows]
        valid_hist = [v for v in deserialized if v is not None]
        if not valid_hist:
            return signals
        hist_vectors = np.array(valid_hist)
        hist_norms = np.linalg.norm(hist_vectors, axis=1, keepdims=True)
        hist_normalized = hist_vectors / np.where(hist_norms == 0, 1, hist_norms)

        novel_memories = []
        for row in new_rows:
            vec = self._deserialize_embedding(row["embedding"])
            if vec is None:
                continue
            norm = np.linalg.norm(vec)
            if norm == 0:
                continue
            normalized = vec / norm
            similarities = hist_normalized @ normalized
            max_sim = float(np.max(similarities))

            if max_sim < self.novelty_sim_threshold:
                novel_memories.append((row["content"], max_sim))

        if len(novel_memories) >= 2:
            avg_max_sim = np.mean([m[1] for m in novel_memories])
            signals.append(Signal(
                signal_type="CLUSTER_NOVEL",
                direction=SignalDirection.NOVEL,
                magnitude=float(1.0 - avg_max_sim),
                description=(
                    f"{len(novel_memories)} memories forming in novel "
                    f"territory (avg nearest historical similarity: "
                    f"{avg_max_sim:.3f})"
                ),
                representatives=[m[0] for m in novel_memories[:3]],
            ))
        elif len(novel_memories) == 1:
            signals.append(Signal(
                signal_type="CLUSTER_NOVEL",
                direction=SignalDirection.NOVEL,
                magnitude=float(1.0 - novel_memories[0][1]) * 0.5,
                description=(
                    f"Single memory in novel territory "
                    f"(nearest historical similarity: "
                    f"{novel_memories[0][1]:.3f})"
                ),
                representatives=[novel_memories[0][0]],
            ))

        return signals

    def detect_retrieval_blind_spots(self) -> List[Signal]:
        """
        Find high-importance permanent memories the system has lost access to.
        Returns signal with representatives including IDs for bridge targeting.
        Filters out memories with active bridges to prevent redundant attempts.
        """
        signals = []

        cutoff = (datetime.utcnow() - timedelta(days=self.blind_spot_days)).strftime("%Y-%m-%d %H:%M:%S")

        # Check if bridge_status column exists (defensive against partial migration)
        has_bridge_col = self._has_bridge_status_column()

        if has_bridge_col:
            blind = self._execute("""
                SELECT id, content, importance, created_at, access_count, last_accessed_at
                FROM memories
                WHERE importance >= ?
                AND decay_category = 'permanent'
                AND (last_accessed_at IS NULL OR last_accessed_at < ?)
                AND (bridge_status IS NULL OR bridge_status != 'active')
                AND meta_source IS NULL
                ORDER BY importance DESC
                LIMIT 5
            """, (self.blind_spot_importance, cutoff))
        else:
            blind = self._execute("""
                SELECT id, content, importance, created_at, access_count, last_accessed_at
                FROM memories
                WHERE importance >= ?
                AND decay_category = 'permanent'
                AND (last_accessed_at IS NULL OR last_accessed_at < ?)
                ORDER BY importance DESC
                LIMIT 5
            """, (self.blind_spot_importance, cutoff))

        if blind:
            signals.append(Signal(
                signal_type="RETRIEVAL_BLIND_SPOT",
                direction=SignalDirection.UNREACHABLE,
                magnitude=float(len(blind)),
                description=(
                    f"{len(blind)} high-importance permanent memories "
                    f"not retrieved in {self.blind_spot_days}+ days"
                ),
                representatives=[
                    f"[ID: {r['id']}] [imp={r['importance']:.2f}, "
                    f"accesses={r['access_count'] or 0}] "
                    f"{r['content']}"
                    for r in blind
                ],
            ))

        return signals

    def get_blind_spot_candidates(self) -> List[Dict[str, Any]]:
        """
        Return raw blind spot candidate data for BridgeManager consumption.
        Separate from signal detection — returns structured dicts with IDs.
        """
        cutoff = (datetime.utcnow() - timedelta(days=self.blind_spot_days)).strftime("%Y-%m-%d %H:%M:%S")

        has_bridge_col = self._has_bridge_status_column()

        if has_bridge_col:
            rows = self._execute("""
                SELECT id, content, importance, created_at, access_count, last_accessed_at
                FROM memories
                WHERE importance >= ?
                AND decay_category = 'permanent'
                AND (last_accessed_at IS NULL OR last_accessed_at < ?)
                AND (bridge_status IS NULL OR bridge_status != 'active')
                AND meta_source IS NULL
                ORDER BY importance DESC
                LIMIT 5
            """, (self.blind_spot_importance, cutoff))
        else:
            rows = self._execute("""
                SELECT id, content, importance, created_at, access_count, last_accessed_at
                FROM memories
                WHERE importance >= ?
                AND decay_category = 'permanent'
                AND (last_accessed_at IS NULL OR last_accessed_at < ?)
                ORDER BY importance DESC
                LIMIT 5
            """, (self.blind_spot_importance, cutoff))

        return [
            {
                "id": r["id"],
                "content": r["content"],
                "importance": r["importance"],
                "created_at": r["created_at"],
                "access_count": r["access_count"] or 0,
                "last_accessed_at": r["last_accessed_at"],
            }
            for r in rows
        ]

    def _has_bridge_status_column(self) -> bool:
        """Check if bridge_status column exists on memories table.

        Cached per observer instance (one per metacognition cycle).
        Only treats OperationalError as 'column missing'; other
        exceptions are logged and treated as missing to avoid crashing
        the caller, but the log makes them visible for debugging.
        """
        if self._bridge_col_exists is not None:
            return self._bridge_col_exists

        try:
            self._execute("SELECT bridge_status FROM memories LIMIT 1")
            self._bridge_col_exists = True
        except Exception as e:
            # OperationalError for missing column is expected on
            # pre-migration databases; anything else is unexpected.
            if "bridge_status" not in str(e).lower():
                log_error(f"Unexpected error checking bridge_status column: {e}")
            self._bridge_col_exists = False

        return self._bridge_col_exists

    # -------------------------------------------------------------------
    # Report generation
    # -------------------------------------------------------------------
    # TODO (minor optimizations, not urgent):
    #   - detect_retrieval_blind_spots() and get_blind_spot_candidates() run
    #     near-identical SQL; share results or cache after first call.
    #   - Z-score detectors use np.std/np.var with ddof=0 (population); ddof=1
    #     (sample) would be more correct at low session counts (<10).

    def generate_signal_report(self, include_tier3: bool = False) -> str:
        """Run all detection methods and compile a structured signal report."""
        try:
            stats = self.get_store_stats()
            stats_section = self._format_store_stats(stats)
        except Exception as e:
            log_error(f"get_store_stats() failed: {e}")
            stats_section = "  [Store stats unavailable — database error]"

        all_signals: List[Signal] = []

        detectors = [
            # Tier 1
            (self.detect_rate_anomalies, "RATE_ANOMALIES"),
            (self.detect_importance_drift, "IMPORTANCE_DRIFT"),
            (self.detect_decay_distribution_shift, "DECAY_DISTRIBUTION"),
            (self.detect_memory_type_shift, "MEMORY_TYPE_SHIFT"),
            # Tier 2
            (self.detect_novel_clusters, "CLUSTER_NOVEL"),
            (self.detect_retrieval_blind_spots, "RETRIEVAL_BLIND_SPOT"),
        ]

        for detector_fn, signal_name in detectors:
            try:
                all_signals.extend(detector_fn())
            except Exception as e:
                log_error(f"Detector {signal_name} failed: {e}")
                all_signals.append(Signal(
                    signal_type=signal_name,
                    direction=SignalDirection.ERROR,
                    magnitude=0.0,
                    description=f"Detector failed — {type(e).__name__}: {e}",
                ))

        all_signals.sort(key=lambda s: s.magnitude, reverse=True)

        header = (
            f"MEMORY TELEMETRY REPORT\n"
            f"Timestamp: {datetime.utcnow().isoformat()}\n"
            f"Analysis window: {self.rolling_window} sessions\n"
            f"Signals detected: {len(all_signals)}\n"
            f"\nSTORE OVERVIEW:\n"
            f"{stats_section}"
        )

        if not all_signals:
            return f"{header}\n\nNo anomalous signals detected. Store is stable."

        body = "\n\n".join(s.to_report_block() for s in all_signals)
        return f"{header}\n\n{body}"
