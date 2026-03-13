"""
BridgeManager: Bridge Memory Lifecycle Management

Handles bridge evaluation (active/effective/ineffective/retired),
blind spot enrichment with bridge history, and bridge storage.

Consumes the observer's blind spot output — does not re-query for candidates.
"""

import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from core.database import get_database
from core.logger import log_info, log_error


class BridgeManager:
    """
    Manages the lifecycle of bridge memories.

    Bridge memories are retrieval pathways written in the language of
    retrospection, connecting unreachable high-importance memories to
    the query patterns that future conversations will actually use.
    """

    def __init__(
        self,
        effectiveness_window_days: int = 14,
        self_sustaining_access_count: int = 3,
        max_attempts: int = 3,
    ):
        self.effectiveness_window_days = effectiveness_window_days
        self.self_sustaining_access_count = self_sustaining_access_count
        self.max_attempts = max_attempts

    def _db(self):
        return get_database()

    def _execute(self, sql: str, params: tuple = (), fetch: bool = True):
        return self._db().execute(sql, params, fetch=fetch)

    # -------------------------------------------------------------------
    # 3a: Bridge Evaluation
    # -------------------------------------------------------------------

    def evaluate_bridges(self) -> Dict[str, int]:
        """
        Evaluate all active bridges and update their status.

        Returns dict with counts of status transitions.
        """
        transitions = {"effective": 0, "ineffective": 0, "retired": 0, "errors": 0}

        try:
            active_bridges = self._execute("""
                SELECT id, bridge_target_ids, bridge_status, bridge_access_baseline, created_at
                FROM memories
                WHERE bridge_status IN ('active', 'effective')
            """)
        except Exception as e:
            log_error(f"BridgeManager: Failed to query active bridges: {e}")
            return transitions

        now = datetime.utcnow()

        # Prune old retired/ineffective bridges to prevent unbounded growth.
        # Retired = targets became self-sustaining; ineffective = bridge failed.
        # 7-day grace period keeps recent transitions visible for debugging.
        try:
            prune_cutoff = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
            self._execute("""
                DELETE FROM memories
                WHERE bridge_status IN ('retired', 'ineffective')
                AND created_at < ?
            """, (prune_cutoff,), fetch=False)
        except Exception as e:
            log_error(f"BridgeManager: Error pruning old bridges: {e}")

        if not active_bridges:
            return transitions

        window = timedelta(days=self.effectiveness_window_days)

        for bridge in active_bridges:
            try:
                target_ids = json.loads(bridge["bridge_target_ids"])
                if not isinstance(target_ids, list) or not target_ids:
                    continue

                bridge_created = bridge["created_at"]
                if isinstance(bridge_created, str):
                    bridge_created = datetime.fromisoformat(bridge_created)

                # Query target memories for access data
                placeholders = ",".join("?" * len(target_ids))
                targets = self._execute(
                    f"SELECT id, access_count, last_accessed_at FROM memories WHERE id IN ({placeholders})",
                    tuple(target_ids)
                )

                if not targets:
                    # All target memories have been deleted — retire the bridge
                    log_info(
                        f"Bridge #{bridge['id']}: all targets deleted, retiring",
                        prefix="🌉"
                    )
                    self._execute(
                        "UPDATE memories SET bridge_status = 'retired' WHERE id = ?",
                        (bridge["id"],),
                        fetch=False
                    )
                    transitions["retired"] += 1
                    continue

                # Load baseline access counts (NULL for pre-baseline bridges → use 0)
                baseline_raw = bridge.get("bridge_access_baseline")
                if baseline_raw and isinstance(baseline_raw, str):
                    try:
                        access_baseline = json.loads(baseline_raw)
                    except (json.JSONDecodeError, TypeError):
                        access_baseline = {}
                elif isinstance(baseline_raw, dict):
                    access_baseline = baseline_raw
                else:
                    access_baseline = {}

                any_accessed_since_bridge = False
                any_self_sustaining = False

                for target in targets:
                    last_accessed = target["last_accessed_at"]
                    if isinstance(last_accessed, str):
                        last_accessed = datetime.fromisoformat(last_accessed)

                    if last_accessed and last_accessed > bridge_created:
                        any_accessed_since_bridge = True

                    # Post-bridge access delta for retirement check
                    current_count = target["access_count"] or 0
                    baseline_count = access_baseline.get(str(target["id"]), 0)
                    post_bridge_access = current_count - baseline_count
                    if post_bridge_access >= self.self_sustaining_access_count:
                        any_self_sustaining = True

                # Determine new status
                if any_self_sustaining:
                    new_status = "retired"
                elif any_accessed_since_bridge:
                    new_status = "effective"
                elif now - bridge_created > window:
                    new_status = "ineffective"
                else:
                    continue  # Still within window, keep active

                # Skip if status hasn't changed (effective bridge re-evaluated as effective)
                current_status = bridge.get("bridge_status", "active")
                if new_status == current_status:
                    continue

                transitions[new_status] += 1

                # Apply status transition with decay category changes
                if new_status == "ineffective":
                    # Ineffective bridges fade through normal freshness mechanism
                    self._execute(
                        "UPDATE memories SET bridge_status = ?, decay_category = 'ephemeral' WHERE id = ?",
                        (new_status, bridge["id"]),
                        fetch=False
                    )
                else:
                    self._execute(
                        "UPDATE memories SET bridge_status = ? WHERE id = ?",
                        (new_status, bridge["id"]),
                        fetch=False
                    )

            except (json.JSONDecodeError, TypeError) as e:
                log_error(f"BridgeManager: Bad bridge_target_ids on bridge #{bridge['id']}: {e}")
                transitions["errors"] += 1
                continue
            except Exception as e:
                log_error(f"BridgeManager: Error evaluating bridge #{bridge['id']}: {e}")
                transitions["errors"] += 1
                continue

        if any(v > 0 for v in transitions.values()):
            log_info(
                f"Bridge evaluation: {transitions}",
                prefix="🌉"
            )

        return transitions

    # -------------------------------------------------------------------
    # 3b: Enrich Blind Spot Data
    # -------------------------------------------------------------------
    # TODO (minor): _get_next_attempt_number still scans all bridges and
    # filters in Python. At scale, could share the bridge lookup from
    # enrich_blind_spots or add a bridge_targets junction table.

    def enrich_blind_spots(self, candidates: List[Dict[str, Any]]) -> str:
        """
        Take observer's blind spot candidates and enrich with bridge history.

        Args:
            candidates: List of dicts from observer.get_blind_spot_candidates()

        Returns:
            Formatted string for injection into the reflection prompt.
        """
        if not candidates:
            return ""

        # Build a lookup dict: target_memory_id → list of bridge info dicts.
        # One query instead of one per candidate.
        bridge_history: Dict[int, List[Dict[str, Any]]] = {}
        try:
            bridges = self._execute("""
                SELECT bridge_target_ids, bridge_status, bridge_attempt_number
                FROM memories
                WHERE bridge_target_ids IS NOT NULL
                AND bridge_status IS NOT NULL
            """)

            for bridge in bridges:
                try:
                    raw = bridge["bridge_target_ids"]
                    target_ids = json.loads(raw) if isinstance(raw, str) else raw
                    if not isinstance(target_ids, list):
                        continue
                    for tid in target_ids:
                        bridge_history.setdefault(tid, []).append({
                            "status": bridge["bridge_status"],
                            "attempt": bridge["bridge_attempt_number"],
                        })
                except (json.JSONDecodeError, TypeError):
                    continue

        except Exception as e:
            log_error(f"BridgeManager: Error querying bridge history: {e}")

        enriched = []
        for candidate in candidates:
            memory_id = candidate["id"]

            # Look up bridge history for this target
            history = bridge_history.get(memory_id, [])
            attempt_count = len(history)
            last_bridge_status = history[-1]["status"] if history else None

            # Filter out candidates with too many attempts
            if attempt_count >= self.max_attempts:
                continue

            # Format for prompt
            last_accessed = candidate.get("last_accessed_at")
            if last_accessed:
                if isinstance(last_accessed, str):
                    try:
                        last_accessed_dt = datetime.fromisoformat(last_accessed)
                        days_ago = (datetime.utcnow() - last_accessed_dt).days
                        access_str = f"last accessed: {days_ago} days ago"
                    except ValueError:
                        access_str = "last accessed: unknown"
                else:
                    days_ago = (datetime.utcnow() - last_accessed).days
                    access_str = f"last accessed: {days_ago} days ago"
            else:
                access_str = "never accessed"

            attempt_str = f"bridge attempts: {attempt_count}"
            if last_bridge_status and attempt_count > 0:
                attempt_str += f" ({last_bridge_status})"

            enriched.append(
                f'- [ID: {memory_id}] "{candidate["content"]}"\n'
                f'  importance: {candidate["importance"]:.2f} | '
                f'{access_str} | {attempt_str}'
            )

        return "\n\n".join(enriched)

    # -------------------------------------------------------------------
    # 3c: Bridge Storage
    # -------------------------------------------------------------------

    def store_bridge(
        self,
        content: str,
        target_ids: List[int],
        importance: float
    ) -> Optional[int]:
        """
        Store a new bridge memory.

        Uses VectorStore.add_memory() for embedding generation, then
        updates the row with bridge-specific fields.

        Returns the new memory ID, or None on failure.
        """
        from memory.vector_store import get_vector_store

        vector_store = get_vector_store()

        # Determine attempt number for this bridge's targets
        attempt_number = self._get_next_attempt_number(target_ids)

        # Capture baseline access counts for each target (for post-bridge retirement check)
        access_baseline = {}
        try:
            placeholders = ",".join("?" * len(target_ids))
            targets = self._execute(
                f"SELECT id, access_count FROM memories WHERE id IN ({placeholders})",
                tuple(target_ids)
            )
            for t in targets:
                access_baseline[str(t["id"])] = t["access_count"] or 0
        except Exception as e:
            log_error(f"BridgeManager: Failed to capture access baseline: {e}")
            # Fallback: assume 0 for all targets (equivalent to old behavior)
            for tid in target_ids:
                access_baseline[str(tid)] = 0

        # Store via normal memory pipeline (generates embedding)
        memory_id = vector_store.add_memory(
            content=content,
            source_conversation_ids=[],
            importance=importance,
            memory_type="reflection",
            decay_category="permanent",
            memory_category="factual",
            meta_source="bridge",
        )

        if memory_id is None:
            log_error("BridgeManager: Failed to store bridge memory (embedding failure)")
            return None

        # Update with bridge-specific fields
        try:
            self._execute(
                """
                UPDATE memories
                SET bridge_target_ids = ?,
                    bridge_status = 'active',
                    bridge_attempt_number = ?,
                    bridge_access_baseline = ?
                WHERE id = ?
                """,
                (json.dumps(target_ids), attempt_number, json.dumps(access_baseline), memory_id),
                fetch=False
            )
            log_info(
                f"Stored bridge memory #{memory_id} targeting {target_ids} (attempt {attempt_number})",
                prefix="🌉"
            )
            return memory_id
        except Exception as e:
            log_error(f"BridgeManager: Failed to set bridge fields on memory #{memory_id}: {e}")
            return memory_id  # Memory exists but without bridge metadata

    def _get_next_attempt_number(self, target_ids: List[int]) -> int:
        """Determine the next bridge attempt number for given targets."""
        max_attempt = 0
        try:
            bridges = self._execute("""
                SELECT bridge_target_ids, bridge_attempt_number
                FROM memories
                WHERE bridge_target_ids IS NOT NULL
                AND bridge_attempt_number IS NOT NULL
            """)

            for bridge in bridges:
                try:
                    existing_targets = json.loads(bridge["bridge_target_ids"]) if isinstance(bridge["bridge_target_ids"], str) else bridge["bridge_target_ids"]
                    if set(target_ids) & set(existing_targets):
                        max_attempt = max(max_attempt, bridge["bridge_attempt_number"] or 0)
                except (json.JSONDecodeError, TypeError):
                    continue
        except Exception:
            pass

        return max_attempt + 1
