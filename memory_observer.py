"""
MemoryObserver: Statistical Signal Detection for Memory Landscape Generation

Runs as a pre-pass before the reflection pulse (Claude Opus 4.6).
No LLM calls. Pure SQL + arithmetic against the memory store.

The math finds the patterns. The vectors provide the meaning.
The reflection model interprets the combination.

Schema mapping (pattern.db):
  memories.memory_category  -> 'episodic' | 'factual'
  memories.memory_type      -> 'fact' | 'preference' | 'event' | 'reflection' | 'observation'
  memories.source_session_id -> proxy for integration cycle
  memories.last_accessed_at  -> last retrieval timestamp
  memories.access_count      -> retrieval hit counter
  memories.importance        -> 0.0 to 1.0
  memories.decay_category    -> 'permanent' | 'standard' | 'ephemeral'
  memories.embedding         -> BLOB (float32 vector)

Signal tiers:
  Tier 1 (core):  Rate anomalies, importance drift, decay distribution shifts, memory type shifts
  Tier 2 (structural): Novel clusters, retrieval blind spots
  Tier 3 (refinement):  Embedding density, temporal periodicity, topic co-occurrence

Output: A structured signal report with representative memory content,
consumed by the reflection pulse to generate meta-memories for the
memory_landscape table.
"""

import sqlite3
import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime, timedelta
from enum import Enum


# ---------------------------------------------------------------------------
# Signal data structures
# ---------------------------------------------------------------------------

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


@dataclass
class Signal:
    """
    A single observation from the statistical pass.
    Carries its own semantic payload so the reflection model
    doesn't have to go looking.
    """
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


# ---------------------------------------------------------------------------
# MemoryObserver
# ---------------------------------------------------------------------------

class MemoryObserver:
    """
    Monitors the memory store for structural signals that the retrieval
    pipeline cannot surface. Designed to run before the reflection pulse,
    producing a signal report that the reflection model (Opus) interprets
    into meta-memories for the memory_landscape table.

    No model calls. No embeddings generated. Just SQL and arithmetic
    against data that already exists in pattern.db.
    """

    def __init__(
        self,
        db_path: str,
        rolling_window: int = 20,
        rate_z_threshold: float = 1.5,
        novelty_sim_threshold: float = 0.50,
        dormancy_multiplier: float = 3.0,
        blind_spot_days: int = 30,
        blind_spot_importance: float = 0.7,
        density_high_threshold: float = 0.85,
        density_low_threshold: float = 0.45,
    ):
        self.db = sqlite3.connect(db_path)
        self.db.row_factory = sqlite3.Row
        self.rolling_window = rolling_window
        self.rate_z_threshold = rate_z_threshold
        self.novelty_sim_threshold = novelty_sim_threshold
        self.dormancy_multiplier = dormancy_multiplier
        self.blind_spot_days = blind_spot_days
        self.blind_spot_importance = blind_spot_importance
        self.density_high_threshold = density_high_threshold
        self.density_low_threshold = density_low_threshold
        self._embedding_dim: Optional[int] = None

    def _deserialize_embedding(self, blob: bytes) -> Optional[np.ndarray]:
        if not blob:
            return None
        return np.frombuffer(blob, dtype=np.float32)

    # -------------------------------------------------------------------
    # Store overview (always included in report header)
    # -------------------------------------------------------------------

    def get_store_stats(self) -> dict:
        """
        Basic inventory of the memory store. Cheap to compute,
        gives the reflection model grounding context for interpreting
        the signals that follow.
        """
        stats = {}

        rows = self.db.execute("""
            SELECT memory_category, COUNT(*) as cnt
            FROM memories GROUP BY memory_category
        """).fetchall()
        stats["by_category"] = {r["memory_category"]: r["cnt"] for r in rows}
        stats["total"] = sum(stats["by_category"].values())

        rows = self.db.execute("""
            SELECT memory_type, COUNT(*) as cnt
            FROM memories WHERE memory_type IS NOT NULL
            GROUP BY memory_type
        """).fetchall()
        stats["by_type"] = {r["memory_type"]: r["cnt"] for r in rows}

        rows = self.db.execute("""
            SELECT decay_category, COUNT(*) as cnt
            FROM memories GROUP BY decay_category
        """).fetchall()
        stats["by_decay"] = {r["decay_category"]: r["cnt"] for r in rows}

        row = self.db.execute("""
            SELECT MIN(created_at) as oldest, MAX(created_at) as newest
            FROM memories
        """).fetchone()
        stats["oldest_memory"] = row["oldest"]
        stats["newest_memory"] = row["newest"]

        row = self.db.execute("""
            SELECT COUNT(DISTINCT source_session_id) as cnt
            FROM memories WHERE source_session_id IS NOT NULL
        """).fetchone()
        stats["source_sessions"] = row["cnt"]

        row = self.db.execute(
            "SELECT AVG(importance) as avg_imp FROM memories"
        ).fetchone()
        stats["avg_importance"] = (
            round(row["avg_imp"], 3) if row["avg_imp"] else 0
        )

        return stats

    def _format_store_stats(self, stats: dict) -> str:
        lines = [
            f"  Total memories: {stats['total']}",
            f"  By category: {stats['by_category']}",
            f"  By type: {stats['by_type']}",
            f"  By decay: {stats['by_decay']}",
            f"  Temporal range: {stats['oldest_memory']} to {stats['newest_memory']}",
            f"  Source sessions: {stats['source_sessions']}",
            f"  Average importance: {stats['avg_importance']}",
        ]
        return "\n".join(lines)

    # -------------------------------------------------------------------
    # TIER 1: Core statistical signals
    # -------------------------------------------------------------------

    def detect_rate_anomalies(self) -> List[Signal]:
        """
        Z-score on memory creation rate per session.
        Uses source_session_id as the integration cycle proxy.
        Computed separately for episodic and factual stores.
        """
        signals = []

        for category in ["episodic", "factual"]:
            rows = self.db.execute("""
                SELECT source_session_id, COUNT(*) as cnt
                FROM memories
                WHERE memory_category = ?
                AND source_session_id IS NOT NULL
                GROUP BY source_session_id
                ORDER BY source_session_id DESC
                LIMIT ?
            """, (category, self.rolling_window + 1)).fetchall()

            if len(rows) < 4:
                continue

            current_session_id = rows[0]["source_session_id"]
            current_count = rows[0]["cnt"]
            historical = np.array(
                [r["cnt"] for r in rows[1:]], dtype=float
            )

            mean = np.mean(historical)
            std = np.std(historical)
            if std == 0:
                continue

            z = (current_count - mean) / std
            if abs(z) < self.rate_z_threshold:
                continue

            direction = (
                SignalDirection.INCREASE if z > 0
                else SignalDirection.DECREASE
            )

            reps = self.db.execute("""
                SELECT content FROM memories
                WHERE memory_category = ? AND source_session_id = ?
                ORDER BY importance DESC LIMIT 3
            """, (category, current_session_id)).fetchall()

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
        """
        Tracks mean importance per session against a rolling baseline.
        Also flags high within-session variance — batches that mixed
        significant and trivial content.
        """
        signals = []

        rows = self.db.execute("""
            SELECT source_session_id,
                   AVG(importance) as mean_imp,
                   COUNT(*) as cnt
            FROM memories
            WHERE source_session_id IS NOT NULL
            GROUP BY source_session_id
            ORDER BY source_session_id DESC
            LIMIT ?
        """, (self.rolling_window + 1,)).fetchall()

        if len(rows) < 4:
            return signals

        current_session_id = rows[0]["source_session_id"]
        current_mean = rows[0]["mean_imp"]
        historical_means = np.array(
            [r["mean_imp"] for r in rows[1:]], dtype=float
        )

        h_mean = np.mean(historical_means)
        h_std = np.std(historical_means)

        if h_std > 0:
            z = (current_mean - h_mean) / h_std
            if abs(z) > self.rate_z_threshold:
                direction = (
                    SignalDirection.INCREASE if z > 0
                    else SignalDirection.DECREASE
                )

                reps = self.db.execute("""
                    SELECT content FROM memories
                    WHERE source_session_id = ?
                    ORDER BY importance DESC LIMIT 2
                """, (current_session_id,)).fetchall()

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
        cycle_scores = self.db.execute("""
            SELECT importance FROM memories
            WHERE source_session_id = ?
        """, (current_session_id,)).fetchall()

        if len(cycle_scores) >= 3:
            variance = float(
                np.var([r["importance"] for r in cycle_scores])
            )

            hist_vars = []
            for row in rows[1:]:
                hv = self.db.execute("""
                    SELECT importance FROM memories
                    WHERE source_session_id = ?
                """, (row["source_session_id"],)).fetchall()
                if len(hv) >= 2:
                    hist_vars.append(
                        float(np.var([r["importance"] for r in hv]))
                    )

            if hist_vars:
                var_mean = np.mean(hist_vars)
                var_std = np.std(hist_vars)
                if var_std > 0:
                    var_z = (variance - var_mean) / var_std
                    if var_z > self.rate_z_threshold:
                        extremes = self.db.execute("""
                            SELECT content, importance FROM memories
                            WHERE source_session_id = ?
                            ORDER BY importance DESC
                        """, (current_session_id,)).fetchall()

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
                                f"— session mixed significant and "
                                f"trivial content"
                            ),
                            representatives=reps,
                        ))

        return signals

    def detect_decay_distribution_shift(self) -> List[Signal]:
        """
        Compares decay category ratios (permanent/standard/ephemeral)
        between recent sessions and historical baseline.
        """
        signals = []

        sessions = self.db.execute("""
            SELECT DISTINCT source_session_id
            FROM memories
            WHERE source_session_id IS NOT NULL
            ORDER BY source_session_id DESC
            LIMIT ?
        """, (self.rolling_window,)).fetchall()

        if len(sessions) < 6:
            return signals

        recent_ids = [s["source_session_id"] for s in sessions[:5]]
        historical_ids = [s["source_session_id"] for s in sessions[5:]]

        categories = ["permanent", "standard", "ephemeral"]

        def get_distribution(session_ids: list) -> np.ndarray:
            placeholders = ",".join("?" * len(session_ids))
            counts = []
            for cat in categories:
                row = self.db.execute(f"""
                    SELECT COUNT(*) as cnt FROM memories
                    WHERE decay_category = ?
                    AND source_session_id IN ({placeholders})
                """, (cat, *session_ids)).fetchone()
                counts.append(row["cnt"])
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
            direction = (
                SignalDirection.INCREASE if diffs[max_idx] > 0
                else SignalDirection.DECREASE
            )

            placeholders = ",".join("?" * len(recent_ids))
            reps = self.db.execute(f"""
                SELECT content FROM memories
                WHERE decay_category = ?
                AND source_session_id IN ({placeholders})
                ORDER BY importance DESC LIMIT 3
            """, (shifted_cat, *recent_ids)).fetchall()

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
        """
        Tracks shifts in memory_type distribution (fact, preference,
        event, reflection, observation). Free structural data from
        the existing schema.
        """
        signals = []

        sessions = self.db.execute("""
            SELECT DISTINCT source_session_id
            FROM memories
            WHERE source_session_id IS NOT NULL
            ORDER BY source_session_id DESC
            LIMIT ?
        """, (self.rolling_window,)).fetchall()

        if len(sessions) < 6:
            return signals

        recent_ids = [s["source_session_id"] for s in sessions[:5]]
        historical_ids = [s["source_session_id"] for s in sessions[5:]]

        types = ["fact", "preference", "event", "reflection", "observation"]

        def get_distribution(session_ids: list) -> np.ndarray:
            placeholders = ",".join("?" * len(session_ids))
            counts = []
            for mtype in types:
                row = self.db.execute(f"""
                    SELECT COUNT(*) as cnt FROM memories
                    WHERE memory_type = ?
                    AND source_session_id IN ({placeholders})
                """, (mtype, *session_ids)).fetchone()
                counts.append(row["cnt"])
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
            direction = (
                SignalDirection.INCREASE if diffs[max_idx] > 0
                else SignalDirection.DECREASE
            )

            placeholders = ",".join("?" * len(recent_ids))
            reps = self.db.execute(f"""
                SELECT content FROM memories
                WHERE memory_type = ?
                AND source_session_id IN ({placeholders})
                ORDER BY importance DESC LIMIT 3
            """, (shifted_type, *recent_ids)).fetchall()

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

    def detect_novel_clusters(
        self, recent_session_count: int = 3
    ) -> List[Signal]:
        """
        For memories added in the last N sessions, compute max cosine
        similarity to the historical store. New memories distant from
        everything historical indicate novel topic formation.
        """
        signals = []

        boundary_row = self.db.execute("""
            SELECT DISTINCT source_session_id FROM memories
            WHERE source_session_id IS NOT NULL
            ORDER BY source_session_id DESC
            LIMIT 1 OFFSET ?
        """, (recent_session_count,)).fetchone()

        if not boundary_row:
            return signals

        boundary_session = boundary_row["source_session_id"]

        new_rows = self.db.execute("""
            SELECT id, content, embedding FROM memories
            WHERE source_session_id > ?
            AND embedding IS NOT NULL
        """, (boundary_session,)).fetchall()

        if not new_rows:
            return signals

        hist_rows = self.db.execute("""
            SELECT embedding FROM memories
            WHERE source_session_id <= ?
            AND embedding IS NOT NULL
            ORDER BY importance DESC
            LIMIT 500
        """, (boundary_session,)).fetchall()

        if not hist_rows:
            return signals

        hist_vectors = np.array([
            self._deserialize_embedding(r["embedding"])
            for r in hist_rows
        ])
        hist_norms = np.linalg.norm(hist_vectors, axis=1, keepdims=True)
        hist_normalized = hist_vectors / np.where(
            hist_norms == 0, 1, hist_norms
        )

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
        Finds high-importance permanent memories the system has lost
        access to. Uses last_accessed_at and access_count from schema.
        Candidates for bridge meta-memories.
        """
        signals = []

        cutoff = (
            datetime.utcnow() - timedelta(days=self.blind_spot_days)
        ).strftime("%Y-%m-%d %H:%M:%S")

        blind = self.db.execute("""
            SELECT content, importance, created_at, access_count
            FROM memories
            WHERE importance >= ?
            AND decay_category = 'permanent'
            AND (last_accessed_at IS NULL OR last_accessed_at < ?)
            ORDER BY importance DESC
            LIMIT 10
        """, (self.blind_spot_importance, cutoff)).fetchall()

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
                    f"[imp={r['importance']:.2f}, "
                    f"accesses={r['access_count'] or 0}] "
                    f"{r['content']}"
                    for r in blind[:5]
                ],
            ))

        return signals

    # -------------------------------------------------------------------
    # TIER 3: Refinement signals (cluster_id dependent)
    # -------------------------------------------------------------------

    def _has_cluster_ids(self) -> bool:
        try:
            self.db.execute("SELECT cluster_id FROM memories LIMIT 1")
            return True
        except sqlite3.OperationalError:
            return False

    def analyze_embedding_density(self) -> List[Signal]:
        """Per-cluster internal similarity. Requires cluster_id."""
        signals = []
        if not self._has_cluster_ids():
            return signals

        clusters = self.db.execute("""
            SELECT DISTINCT cluster_id FROM memories
            WHERE cluster_id IS NOT NULL
        """).fetchall()

        for row in clusters:
            cid = row["cluster_id"]
            members = self.db.execute("""
                SELECT content, embedding FROM memories
                WHERE cluster_id = ?
            """, (cid,)).fetchall()

            if len(members) < 3:
                continue

            vectors = np.array([
                self._deserialize_embedding(m["embedding"])
                for m in members
            ])
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            normalized = vectors / np.where(norms == 0, 1, norms)

            sim_matrix = normalized @ normalized.T
            n = len(members)
            upper = np.triu_indices(n, k=1)
            avg_sim = float(np.mean(sim_matrix[upper]))

            if avg_sim > self.density_high_threshold:
                reps = self.db.execute("""
                    SELECT content FROM memories
                    WHERE cluster_id = ? ORDER BY importance DESC LIMIT 2
                """, (cid,)).fetchall()
                signals.append(Signal(
                    signal_type="CLUSTER_DENSITY",
                    direction=SignalDirection.DENSE,
                    magnitude=avg_sim,
                    description=(
                        f"Cluster {cid} ({n} memories): high internal "
                        f"similarity ({avg_sim:.3f}) — possible redundancy"
                    ),
                    representatives=[r["content"] for r in reps],
                ))

            elif avg_sim < self.density_low_threshold:
                reps = self.db.execute("""
                    SELECT content FROM memories
                    WHERE cluster_id = ? ORDER BY importance DESC LIMIT 2
                """, (cid,)).fetchall()
                signals.append(Signal(
                    signal_type="CLUSTER_DENSITY",
                    direction=SignalDirection.SPARSE,
                    magnitude=1.0 - avg_sim,
                    description=(
                        f"Cluster {cid} ({n} memories): low internal "
                        f"similarity ({avg_sim:.3f}) — may lack "
                        f"coherent thread"
                    ),
                    representatives=[r["content"] for r in reps],
                ))

        return signals

    def detect_periodicity_breaks(self) -> List[Signal]:
        """Autocorrelation on per-session cluster rates. Requires cluster_id."""
        signals = []
        if not self._has_cluster_ids():
            return signals

        all_sessions = self.db.execute("""
            SELECT DISTINCT source_session_id FROM memories
            WHERE source_session_id IS NOT NULL
            ORDER BY source_session_id ASC
        """).fetchall()

        if len(all_sessions) < 10:
            return signals

        sess_to_idx = {
            s["source_session_id"]: i for i, s in enumerate(all_sessions)
        }
        n_sess = len(all_sessions)

        clusters = self.db.execute("""
            SELECT cluster_id, COUNT(*) as cnt FROM memories
            WHERE cluster_id IS NOT NULL
            GROUP BY cluster_id HAVING cnt >= 8
        """).fetchall()

        for crow in clusters:
            cid = crow["cluster_id"]
            rows = self.db.execute("""
                SELECT source_session_id, COUNT(*) as cnt FROM memories
                WHERE cluster_id = ? AND source_session_id IS NOT NULL
                GROUP BY source_session_id
            """, (cid,)).fetchall()

            series = np.zeros(n_sess)
            for r in rows:
                sid = r["source_session_id"]
                if sid in sess_to_idx:
                    series[sess_to_idx[sid]] = r["cnt"]

            if np.sum(series > 0) < 4:
                continue

            n = len(series)
            mean = np.mean(series)
            var = np.var(series)
            if var == 0:
                continue

            max_lag = min(n // 3, 15)
            autocorr = np.array([
                np.mean(
                    (series[:n - lag] - mean) * (series[lag:] - mean)
                ) / var
                for lag in range(1, max_lag + 1)
            ])

            if len(autocorr) == 0:
                continue

            best_lag = int(np.argmax(autocorr)) + 1
            best_corr = float(autocorr[best_lag - 1])
            if best_corr < 0.3:
                continue

            recent = series[-best_lag * 2:]
            historical = series[:-best_lag * 2]
            if len(historical) < best_lag:
                continue

            recent_rate = np.mean(recent)
            hist_rate = np.mean(historical)

            if hist_rate > 0 and recent_rate < hist_rate * 0.25:
                reps = self.db.execute("""
                    SELECT content FROM memories
                    WHERE cluster_id = ?
                    ORDER BY importance DESC LIMIT 2
                """, (cid,)).fetchall()

                signals.append(Signal(
                    signal_type="PERIODICITY_BREAK",
                    direction=SignalDirection.PERIODIC_BREAK,
                    magnitude=float(best_corr),
                    description=(
                        f"Cluster {cid}: periodic activity "
                        f"(~every {best_lag} sessions, "
                        f"r={best_corr:.2f}) has gone quiet "
                        f"(recent {recent_rate:.2f} vs "
                        f"historical {hist_rate:.2f})"
                    ),
                    representatives=[r["content"] for r in reps],
                ))

        return signals

    def detect_topic_co_occurrence(self) -> List[Signal]:
        """Cluster pair co-occurrence breaking. Requires cluster_id."""
        signals = []
        if not self._has_cluster_ids():
            return signals

        clusters = self.db.execute("""
            SELECT DISTINCT cluster_id FROM memories
            WHERE cluster_id IS NOT NULL
        """).fetchall()
        cluster_ids = [c["cluster_id"] for c in clusters]

        if len(cluster_ids) < 2:
            return signals

        all_sessions = self.db.execute("""
            SELECT DISTINCT source_session_id FROM memories
            WHERE source_session_id IS NOT NULL
            ORDER BY source_session_id ASC
        """).fetchall()
        session_ids = [s["source_session_id"] for s in all_sessions]

        if len(session_ids) < 10:
            return signals

        cid_to_idx = {cid: i for i, cid in enumerate(cluster_ids)}
        presence = np.zeros(
            (len(cluster_ids), len(session_ids)), dtype=float
        )

        for i, sid in enumerate(session_ids):
            rows = self.db.execute("""
                SELECT DISTINCT cluster_id FROM memories
                WHERE source_session_id = ? AND cluster_id IS NOT NULL
            """, (sid,)).fetchall()
            for r in rows:
                cid = r["cluster_id"]
                if cid in cid_to_idx:
                    presence[cid_to_idx[cid], i] = 1.0

        n_c = len(cluster_ids)
        split = len(session_ids) * 2 // 3

        for i in range(n_c):
            for j in range(i + 1, n_c):
                hi, hj = presence[i, :split], presence[j, :split]
                ri, rj = presence[i, split:], presence[j, split:]

                if (np.sum(presence[i]) < 4 or np.sum(presence[j]) < 4):
                    continue
                if (np.std(hi) == 0 or np.std(hj) == 0 or
                        np.std(ri) == 0 or np.std(rj) == 0):
                    continue

                h_corr = float(np.corrcoef(hi, hj)[0, 1])
                r_corr = float(np.corrcoef(ri, rj)[0, 1])

                if np.isnan(h_corr) or np.isnan(r_corr):
                    continue

                if h_corr > 0.5 and r_corr < 0.15:
                    rep_i = self.db.execute("""
                        SELECT content FROM memories
                        WHERE cluster_id = ?
                        ORDER BY importance DESC LIMIT 1
                    """, (cluster_ids[i],)).fetchone()
                    rep_j = self.db.execute("""
                        SELECT content FROM memories
                        WHERE cluster_id = ?
                        ORDER BY importance DESC LIMIT 1
                    """, (cluster_ids[j],)).fetchone()

                    reps = []
                    if rep_i:
                        reps.append(
                            f"Cluster {cluster_ids[i]}: "
                            f"{rep_i['content']}"
                        )
                    if rep_j:
                        reps.append(
                            f"Cluster {cluster_ids[j]}: "
                            f"{rep_j['content']}"
                        )

                    signals.append(Signal(
                        signal_type="CO_OCCURRENCE_BREAK",
                        direction=SignalDirection.DORMANT,
                        magnitude=float(h_corr - r_corr),
                        description=(
                            f"Clusters {cluster_ids[i]} and "
                            f"{cluster_ids[j]} historically co-occurred "
                            f"(r={h_corr:.2f}) but decoupled recently "
                            f"(r={r_corr:.2f})"
                        ),
                        representatives=reps,
                    ))

        return signals

    # -------------------------------------------------------------------
    # Report generation
    # -------------------------------------------------------------------

    def generate_signal_report(
        self, include_tier3: bool = False
    ) -> str:
        """
        Runs all detection methods and compiles a structured signal
        report for injection into the reflection pulse prompt.
        """
        stats = self.get_store_stats()
        all_signals: List[Signal] = []

        # Tier 1
        all_signals.extend(self.detect_rate_anomalies())
        all_signals.extend(self.detect_importance_drift())
        all_signals.extend(self.detect_decay_distribution_shift())
        all_signals.extend(self.detect_memory_type_shift())

        # Tier 2
        all_signals.extend(self.detect_novel_clusters())
        all_signals.extend(self.detect_retrieval_blind_spots())

        # Tier 3
        if include_tier3:
            all_signals.extend(self.analyze_embedding_density())
            all_signals.extend(self.detect_periodicity_breaks())
            all_signals.extend(self.detect_topic_co_occurrence())

        all_signals.sort(key=lambda s: s.magnitude, reverse=True)

        header = (
            f"MEMORY TELEMETRY REPORT\n"
            f"Timestamp: {datetime.utcnow().isoformat()}\n"
            f"Analysis window: {self.rolling_window} sessions\n"
            f"Signals detected: {len(all_signals)}\n"
            f"\nSTORE OVERVIEW:\n"
            f"{self._format_store_stats(stats)}"
        )

        if not all_signals:
            return (
                f"{header}\n\n"
                f"No anomalous signals detected. Store is stable."
            )

        body = "\n\n".join(s.to_report_block() for s in all_signals)
        return f"{header}\n\n{body}"

    def close(self):
        self.db.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    db_path = sys.argv[1] if len(sys.argv) > 1 else "pattern.db"
    tier3 = "--tier3" in sys.argv

    print(f"Analyzing: {db_path}")
    print(f"Tier 3: {'enabled' if tier3 else 'disabled'}")
    print("=" * 60)

    observer = MemoryObserver(db_path)
    report = observer.generate_signal_report(include_tier3=tier3)
    print(report)
    observer.close()
