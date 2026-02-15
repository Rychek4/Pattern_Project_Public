#!/usr/bin/env python3
"""
Memory Database Charting Tool

Generates two charts analyzing memory creation trends and projected retrieval landscape:

  Chart A: Memory creation breakdown by week (last 13 weeks)
           - By decay category (permanent / standard / ephemeral)
           - By memory type (fact / preference / event / reflection / observation)

  Chart B: Projected effective memory pool over next 90 days
           - Shows how many memories remain above freshness threshold per decay category
           - Assumes no new memories are created (snapshot projection)

Usage:
    python scripts/chart_memories.py

Output:
    charts/memory_creation_breakdown.png
    charts/memory_freshness_projection.png
"""

import sqlite3
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

# Add project root to path for config import
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from config import DATABASE_PATH, DECAY_HALF_LIFE_STANDARD, DECAY_HALF_LIFE_EPHEMERAL

# --- Configuration ---

CHARTS_DIR = PROJECT_ROOT / "charts"
FRESHNESS_THRESHOLD = 0.5
WEEKS_BACK = 13
PROJECTION_DAYS = 90

DECAY_CATEGORIES = ["permanent", "standard", "ephemeral"]
MEMORY_TYPES = ["fact", "preference", "event", "reflection", "observation"]

DECAY_COLORS = {
    "permanent": "#2ecc71",
    "standard": "#3498db",
    "ephemeral": "#e74c3c",
}

TYPE_COLORS = {
    "fact": "#2ecc71",
    "preference": "#3498db",
    "event": "#f39c12",
    "reflection": "#9b59b6",
    "observation": "#e74c3c",
}

HALF_LIVES = {
    "permanent": None,
    "standard": DECAY_HALF_LIFE_STANDARD,
    "ephemeral": DECAY_HALF_LIFE_EPHEMERAL,
}


def get_connection():
    """Get a read-only database connection."""
    if not DATABASE_PATH.exists():
        print(f"Database not found at: {DATABASE_PATH}")
        sys.exit(1)
    conn = sqlite3.connect(f"file:{DATABASE_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def parse_timestamp(ts_str):
    """Parse a timestamp string into a datetime object."""
    if not ts_str:
        return None
    try:
        if "T" in ts_str:
            return datetime.fromisoformat(
                ts_str.replace("Z", "+00:00")
            ).replace(tzinfo=None)
        return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


def fetch_memories(conn):
    """Fetch all memory records needed for charting."""
    cursor = conn.execute(
        """
        SELECT
            created_at,
            COALESCE(source_timestamp, created_at) AS effective_timestamp,
            decay_category,
            memory_type,
            memory_category,
            importance
        FROM memories
        ORDER BY created_at
        """
    )
    return cursor.fetchall()


def chart_creation_breakdown(memories, now):
    """
    Chart A: Memory creation breakdown by week.
    Two subplots - one by decay category, one by memory type.
    """
    cutoff = now - timedelta(weeks=WEEKS_BACK)

    # Week boundaries starting from the Monday of the cutoff week
    week_start = cutoff - timedelta(days=cutoff.weekday())
    weeks = []
    current = week_start
    while current <= now:
        weeks.append(current)
        current += timedelta(weeks=1)

    # Bucket memories into weeks
    decay_buckets = defaultdict(lambda: defaultdict(int))
    type_buckets = defaultdict(lambda: defaultdict(int))

    for mem in memories:
        created = parse_timestamp(mem["created_at"])
        if created is None or created < week_start:
            continue

        week_idx = (created - week_start).days // 7
        if week_idx < 0 or week_idx >= len(weeks):
            continue

        week_label = weeks[week_idx]
        decay_cat = mem["decay_category"] or "standard"
        mem_type = mem["memory_type"] or "unknown"

        decay_buckets[week_label][decay_cat] += 1
        type_buckets[week_label][mem_type] += 1

    # --- Build figure ---
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))
    fig.suptitle(
        "Memory Creation Breakdown (Last 13 Weeks)", fontsize=14, fontweight="bold"
    )

    bar_width = 4.5  # days (in matplotlib date units)

    # Subplot 1: By decay category
    for i, cat in enumerate(DECAY_CATEGORIES):
        values = [decay_buckets[w].get(cat, 0) for w in weeks]
        bottoms = [
            sum(decay_buckets[w].get(c, 0) for c in DECAY_CATEGORIES[:i])
            for w in weeks
        ]
        ax1.bar(
            weeks,
            values,
            bottom=bottoms,
            width=bar_width,
            label=cat,
            color=DECAY_COLORS[cat],
            edgecolor="white",
            linewidth=0.5,
        )

    ax1.set_ylabel("Memories Created")
    ax1.set_title("By Decay Category")
    ax1.legend(loc="upper left")
    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax1.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0, interval=2))
    plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45, ha="right")
    ax1.set_xlim(week_start - timedelta(days=3), now + timedelta(days=3))

    # Subplot 2: By memory type
    for i, mtype in enumerate(MEMORY_TYPES):
        values = [type_buckets[w].get(mtype, 0) for w in weeks]
        bottoms = [
            sum(type_buckets[w].get(t, 0) for t in MEMORY_TYPES[:i]) for w in weeks
        ]
        ax2.bar(
            weeks,
            values,
            bottom=bottoms,
            width=bar_width,
            label=mtype,
            color=TYPE_COLORS[mtype],
            edgecolor="white",
            linewidth=0.5,
        )

    ax2.set_ylabel("Memories Created")
    ax2.set_title("By Memory Type")
    ax2.legend(loc="upper left")
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax2.xaxis.set_major_locator(mdates.WeekdayLocator(byweekday=0, interval=2))
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=45, ha="right")
    ax2.set_xlim(week_start - timedelta(days=3), now + timedelta(days=3))

    fig.tight_layout()
    output_path = CHARTS_DIR / "memory_creation_breakdown.png"
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {output_path}")


def chart_freshness_projection(memories, now):
    """
    Chart B: Projected effective memory pool over next 90 days.
    For each future day, count memories that remain above the freshness threshold.

    Freshness formula: exp(-ln(2) * age_days / half_life)
    Permanent memories never decay (freshness always 1.0).
    """
    # Pre-compute current age for each memory
    memory_ages = []
    for mem in memories:
        ts = parse_timestamp(mem["effective_timestamp"])
        if ts is None:
            ts = parse_timestamp(mem["created_at"])
        if ts is None:
            continue
        age_days = max(0.0, (now - ts).total_seconds() / 86400.0)
        decay_cat = mem["decay_category"] or "standard"
        memory_ages.append((age_days, decay_cat))

    # Count memories above threshold at each projected day
    days = list(range(0, PROJECTION_DAYS + 1))
    counts = {cat: [] for cat in DECAY_CATEGORIES}

    for d in days:
        for cat in DECAY_CATEGORIES:
            count = 0
            hl = HALF_LIVES[cat]
            for age, decay_cat in memory_ages:
                if decay_cat != cat:
                    continue
                if hl is None:
                    # Permanent: always above threshold
                    count += 1
                else:
                    freshness = math.exp(-math.log(2) * (age + d) / hl)
                    if freshness >= FRESHNESS_THRESHOLD:
                        count += 1
            counts[cat].append(count)

    totals = [
        sum(counts[cat][i] for cat in DECAY_CATEGORIES) for i in range(len(days))
    ]

    # --- Build figure ---
    fig, ax = plt.subplots(figsize=(12, 5))
    fig.suptitle(
        "Projected Effective Memory Pool (Next 90 Days)",
        fontsize=14,
        fontweight="bold",
    )

    for cat in DECAY_CATEGORIES:
        ax.fill_between(days, counts[cat], alpha=0.2, color=DECAY_COLORS[cat])
        ax.plot(
            days,
            counts[cat],
            label=f"{cat} ({counts[cat][0]} now)",
            color=DECAY_COLORS[cat],
            linewidth=2,
        )

    ax.plot(
        days,
        totals,
        label=f"total ({totals[0]} now)",
        color="#2c3e50",
        linewidth=2,
        linestyle="--",
    )

    ax.set_xlabel("Days From Now")
    ax.set_ylabel(f"Memories Above {FRESHNESS_THRESHOLD} Freshness")
    ax.set_title(
        f"Freshness threshold: {FRESHNESS_THRESHOLD} | "
        f"Standard half-life: {DECAY_HALF_LIFE_STANDARD}d | "
        f"Ephemeral half-life: {DECAY_HALF_LIFE_EPHEMERAL}d"
    )
    ax.legend(loc="upper right")
    ax.set_xlim(0, PROJECTION_DAYS)
    ax.set_ylim(bottom=0)
    ax.grid(True, alpha=0.3)

    # Vertical markers at key intervals
    for marker_day in [7, 30, 60, 90]:
        if marker_day <= PROJECTION_DAYS:
            ax.axvline(x=marker_day, color="gray", linestyle=":", alpha=0.5)
            y_top = ax.get_ylim()[1]
            ax.text(
                marker_day, y_top * 0.97, f"{marker_day}d",
                ha="center", va="top", fontsize=8, color="gray",
            )

    fig.tight_layout()
    output_path = CHARTS_DIR / "memory_freshness_projection.png"
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved: {output_path}")


def print_summary(memories):
    """Print a text summary of the current memory database state."""
    total = len(memories)
    if total == 0:
        print("\nNo memories in database.")
        return

    decay_counts = defaultdict(int)
    type_counts = defaultdict(int)
    cat_counts = defaultdict(int)
    importance_by_type = defaultdict(list)

    for mem in memories:
        decay_cat = mem["decay_category"] or "standard"
        mem_type = mem["memory_type"] or "unknown"
        mem_cat = mem["memory_category"] or "episodic"

        decay_counts[decay_cat] += 1
        type_counts[mem_type] += 1
        cat_counts[mem_cat] += 1
        importance_by_type[mem_type].append(mem["importance"] or 0.5)

    print(f"\n{'=' * 50}")
    print("MEMORY DATABASE SUMMARY")
    print(f"{'=' * 50}")
    print(f"Total memories: {total}")

    print("\nBy decay category:")
    for cat in DECAY_CATEGORIES:
        count = decay_counts.get(cat, 0)
        pct = count / total * 100
        print(f"  {cat:12s}: {count:4d} ({pct:5.1f}%)")

    print("\nBy memory type:")
    for mtype in MEMORY_TYPES + (["unknown"] if "unknown" in type_counts else []):
        count = type_counts.get(mtype, 0)
        pct = count / total * 100
        vals = importance_by_type.get(mtype, [0.5])
        avg_imp = sum(vals) / len(vals)
        print(f"  {mtype:12s}: {count:4d} ({pct:5.1f}%)  avg importance: {avg_imp:.2f}")

    print("\nBy extraction method:")
    for cat in ["episodic", "factual"]:
        count = cat_counts.get(cat, 0)
        pct = count / total * 100
        print(f"  {cat:12s}: {count:4d} ({pct:5.1f}%)")

    print(f"{'=' * 50}")


def main():
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    try:
        memories = fetch_memories(conn)
    finally:
        conn.close()

    if not memories:
        print("No memories found in database. Nothing to chart.")
        return

    now = datetime.now()
    print(f"Found {len(memories)} memories. Generating charts...")

    chart_creation_breakdown(memories, now)
    chart_freshness_projection(memories, now)
    print_summary(memories)

    print(f"\nCharts saved to: {CHARTS_DIR}/")


if __name__ == "__main__":
    main()
