"""
Pattern Project - Database Module
SQLite with WAL mode, schema management, and connection handling
"""

import sqlite3
import json
from pathlib import Path
from datetime import datetime
from typing import Optional, Any, List, Tuple
from contextlib import contextmanager

from core.logger import log_info, log_success, log_error, log_config, log_section

# Schema version for migrations
SCHEMA_VERSION = 20

# SQL schema definition
SCHEMA_SQL = """
-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Sessions track distinct conversation periods
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,
    duration_seconds INTEGER,
    turn_count INTEGER DEFAULT 0,
    idle_time_seconds REAL DEFAULT 0,
    metadata JSON
);

-- Raw conversation turns with temporal context
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    input_type TEXT DEFAULT 'text',

    -- Temporal fields
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    time_since_last_turn_seconds REAL,

    -- Processing state
    processed_for_memory BOOLEAN DEFAULT FALSE,
    processed_at TIMESTAMP
);

-- Extracted memories with embeddings and temporal tracking
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    embedding BLOB NOT NULL,

    -- Source tracking
    source_conversation_ids JSON,
    source_session_id INTEGER REFERENCES sessions(id),

    -- Temporal fields
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_accessed_at TIMESTAMP,
    access_count INTEGER DEFAULT 0,
    source_timestamp TIMESTAMP,
    -- decay_category controls how quickly memories fade from relevance:
    --   'permanent': Never decays (core identity, lasting preferences)
    --   'standard': 30-day half-life (events, discussions, insights)
    --   'ephemeral': 7-day half-life (situational observations)
    decay_category TEXT DEFAULT 'standard' CHECK (decay_category IN ('permanent', 'standard', 'ephemeral')),

    -- Scoring
    importance REAL DEFAULT 0.5 CHECK (importance >= 0 AND importance <= 1),
    memory_type TEXT CHECK (memory_type IN ('fact', 'preference', 'event', 'reflection', 'observation')),
    -- memory_category distinguishes extraction method:
    --   'episodic': Narrative memories about what happened (default, existing behavior)
    --   'factual': Concrete facts extracted from conversations
    memory_category TEXT DEFAULT 'episodic' CHECK (memory_category IN ('episodic', 'factual'))
);

-- Core memories: permanent, foundational knowledge always included
CREATE TABLE IF NOT EXISTS core_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('identity', 'relationship', 'preference', 'fact', 'narrative')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    promoted_from_memory_id INTEGER REFERENCES memories(id)
);

-- Runtime state persistence
CREATE TABLE IF NOT EXISTS state (
    key TEXT PRIMARY KEY,
    value JSON,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Intentions: AI-created reminders, goals, and plans
CREATE TABLE IF NOT EXISTS intentions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- What type of intention this is
    type TEXT NOT NULL CHECK (type IN ('reminder', 'goal')),

    -- The content of the intention (what to do/remember)
    content TEXT NOT NULL,

    -- Why this intention was created (context from conversation)
    context TEXT,

    -- When this intention should trigger
    trigger_type TEXT NOT NULL CHECK (trigger_type IN ('time', 'next_session')),
    trigger_at TIMESTAMP,

    -- Lifecycle
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'triggered', 'completed', 'dismissed')),
    priority INTEGER DEFAULT 5 CHECK (priority >= 1 AND priority <= 10),

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    triggered_at TIMESTAMP,
    completed_at TIMESTAMP,

    -- Outcome note (when completed)
    outcome TEXT,

    -- Source session for context
    source_session_id INTEGER REFERENCES sessions(id)
);

-- Communication log: tracks sent emails and Telegram messages
CREATE TABLE IF NOT EXISTS communication_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL CHECK (type IN ('email', 'telegram')),
    recipient TEXT NOT NULL,
    subject TEXT,  -- NULL for Telegram
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'sent' CHECK (status IN ('sent', 'failed')),
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Active thoughts: AI's working memory - ranked list of current priorities
CREATE TABLE IF NOT EXISTS active_thoughts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rank INTEGER NOT NULL UNIQUE CHECK(rank >= 1 AND rank <= 10),
    slug TEXT NOT NULL UNIQUE,
    topic TEXT NOT NULL,
    elaboration TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Curiosity goals: AI's current and historical curiosity-driven exploration targets
CREATE TABLE IF NOT EXISTS curiosity_goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('dormant_revival', 'depth_seeking', 'fresh_discovery')),
    context TEXT,
    source_memory_id INTEGER REFERENCES memories(id),
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'explored', 'deferred', 'declined')),
    activated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP,
    outcome_notes TEXT,
    cooldown_until TIMESTAMP,
    interaction_count INTEGER DEFAULT 0
);

-- Active thoughts history: append-only archive of all thought states over time
-- Each batch shares an archived_at timestamp, representing the state before a change
CREATE TABLE IF NOT EXISTS active_thoughts_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    archived_at TIMESTAMP NOT NULL,
    rank INTEGER NOT NULL,
    slug TEXT NOT NULL,
    topic TEXT NOT NULL,
    elaboration TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

-- Growth threads: AI's long-term developmental aspirations
-- Tracks patterns the AI wants to integrate over weeks/months
CREATE TABLE IF NOT EXISTS growth_threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT 'seed' CHECK (stage IN ('seed', 'growing', 'integrating', 'dormant', 'abandoned')),
    stage_changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Reading sessions: tracks progress through a novel being read chapter-by-chapter
CREATE TABLE IF NOT EXISTS reading_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    title TEXT,
    status TEXT NOT NULL DEFAULT 'reading' CHECK (status IN ('reading', 'completed', 'abandoned')),
    total_chapters INTEGER NOT NULL DEFAULT 0,
    total_arcs INTEGER DEFAULT 0,
    has_prologue BOOLEAN DEFAULT FALSE,
    structure_json JSON,
    current_chapter INTEGER DEFAULT 0,
    current_arc INTEGER DEFAULT 0,
    chapters_read JSON DEFAULT '[]',
    observations_json TEXT DEFAULT '[]',
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_read_at TIMESTAMP,
    completed_at TIMESTAMP
);

-- Indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id);
CREATE INDEX IF NOT EXISTS idx_conversations_unprocessed ON conversations(processed_for_memory) WHERE processed_for_memory = FALSE;
CREATE INDEX IF NOT EXISTS idx_conversations_created ON conversations(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_recency ON memories(last_accessed_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_source_time ON memories(source_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance DESC);
CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(memory_category);
CREATE INDEX IF NOT EXISTS idx_sessions_active ON sessions(ended_at) WHERE ended_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_core_memories_category ON core_memories(category);
CREATE INDEX IF NOT EXISTS idx_intentions_status ON intentions(status);
CREATE INDEX IF NOT EXISTS idx_intentions_trigger_at ON intentions(trigger_at) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_intentions_type ON intentions(type);
CREATE INDEX IF NOT EXISTS idx_communication_log_type ON communication_log(type);
CREATE INDEX IF NOT EXISTS idx_communication_log_created ON communication_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_active_thoughts_rank ON active_thoughts(rank);
CREATE INDEX IF NOT EXISTS idx_curiosity_status ON curiosity_goals(status);
CREATE INDEX IF NOT EXISTS idx_curiosity_cooldown ON curiosity_goals(cooldown_until);
CREATE INDEX IF NOT EXISTS idx_curiosity_source ON curiosity_goals(source_memory_id);
CREATE INDEX IF NOT EXISTS idx_thoughts_history_archived ON active_thoughts_history(archived_at DESC);
CREATE INDEX IF NOT EXISTS idx_growth_threads_stage ON growth_threads(stage);
CREATE INDEX IF NOT EXISTS idx_growth_threads_slug ON growth_threads(slug);
CREATE INDEX IF NOT EXISTS idx_reading_sessions_status ON reading_sessions(status);
"""

# Migration SQL for v1 -> v2
MIGRATION_V2_SQL = """
-- Core memories: permanent, foundational knowledge always included
CREATE TABLE IF NOT EXISTS core_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('identity', 'relationship', 'preference', 'fact')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    promoted_from_memory_id INTEGER REFERENCES memories(id)
);

-- Relationship tracking: emergent affinity and trust (0-100 scale)
CREATE TABLE IF NOT EXISTS relationships (
    id INTEGER PRIMARY KEY DEFAULT 1,
    affinity INTEGER DEFAULT 50 CHECK (affinity >= 0 AND affinity <= 100),
    trust INTEGER DEFAULT 50 CHECK (trust >= 0 AND trust <= 100),
    interaction_count INTEGER DEFAULT 0,
    first_interaction TIMESTAMP,
    last_interaction TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for core memories
CREATE INDEX IF NOT EXISTS idx_core_memories_category ON core_memories(category);
"""

# Migration SQL for v2 -> v3 (add 'narrative' to core_memories category)
MIGRATION_V3_SQL = """
-- Recreate core_memories table with 'narrative' category
-- SQLite doesn't support ALTER TABLE for CHECK constraints

-- Create new table with updated constraint
CREATE TABLE core_memories_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('identity', 'relationship', 'preference', 'fact', 'narrative')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    promoted_from_memory_id INTEGER REFERENCES memories(id)
);

-- Copy existing data
INSERT INTO core_memories_new (id, content, category, created_at, promoted_from_memory_id)
SELECT id, content, category, created_at, promoted_from_memory_id FROM core_memories;

-- Drop old table
DROP TABLE core_memories;

-- Rename new table
ALTER TABLE core_memories_new RENAME TO core_memories;

-- Recreate index
CREATE INDEX IF NOT EXISTS idx_core_memories_category ON core_memories(category);
"""

# Migration SQL for v3 -> v4 (convert relationships to 0-100 integer scale)
MIGRATION_V4_SQL = """
-- Recreate relationships table with new 0-100 integer scale
-- SQLite doesn't support ALTER TABLE for CHECK constraints or type changes

-- Create new table with updated schema
CREATE TABLE relationships_new (
    id INTEGER PRIMARY KEY DEFAULT 1,
    affinity INTEGER DEFAULT 50 CHECK (affinity >= 0 AND affinity <= 100),
    trust INTEGER DEFAULT 50 CHECK (trust >= 0 AND trust <= 100),
    interaction_count INTEGER DEFAULT 0,
    first_interaction TIMESTAMP,
    last_interaction TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Copy and convert existing data with defensive handling:
-- - COALESCE handles NULL values (default to neutral 0 for affinity, 0.5 for trust)
-- - MIN/MAX clamps results to valid 0-100 range
-- Old affinity: -1.0 to 1.0 -> New: 0 to 100 (formula: (old + 1) * 50)
-- Old trust: 0.0 to 1.0 -> New: 0 to 100 (formula: old * 100)
INSERT INTO relationships_new (id, affinity, trust, interaction_count, first_interaction, last_interaction, updated_at)
SELECT id,
       MIN(100, MAX(0, CAST(ROUND((COALESCE(affinity, 0) + 1.0) * 50) AS INTEGER))),
       MIN(100, MAX(0, CAST(ROUND(COALESCE(trust, 0.5) * 100) AS INTEGER))),
       COALESCE(interaction_count, 0), first_interaction, last_interaction, updated_at
FROM relationships;

-- Drop old table
DROP TABLE relationships;

-- Rename new table
ALTER TABLE relationships_new RENAME TO relationships;
"""

# Migration SQL for v4 -> v5 (remove CHECK constraints from conversations table)
MIGRATION_V5_SQL = """
-- Remove restrictive CHECK constraints from conversations table
-- SQLite requires table recreation to modify constraints

-- Disable foreign keys during migration
PRAGMA foreign_keys=OFF;

-- Create new table without CHECK constraints
CREATE TABLE conversations_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    input_type TEXT DEFAULT 'text',

    -- Temporal fields
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    time_since_last_turn_seconds REAL,

    -- Processing state
    processed_for_memory BOOLEAN DEFAULT FALSE,
    processed_at TIMESTAMP
);

-- Copy all existing data
INSERT INTO conversations_new (
    id, session_id, role, content, input_type,
    created_at, time_since_last_turn_seconds,
    processed_for_memory, processed_at
)
SELECT
    id, session_id, role, content, input_type,
    created_at, time_since_last_turn_seconds,
    processed_for_memory, processed_at
FROM conversations;

-- Drop old table
DROP TABLE conversations;

-- Rename new table
ALTER TABLE conversations_new RENAME TO conversations;

-- Recreate indexes
CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id);
CREATE INDEX IF NOT EXISTS idx_conversations_unprocessed ON conversations(processed_for_memory) WHERE processed_for_memory = FALSE;
CREATE INDEX IF NOT EXISTS idx_conversations_created ON conversations(created_at DESC);

-- Re-enable foreign keys
PRAGMA foreign_keys=ON;
"""

# Migration SQL for v5 -> v6 (rename temporal_relevance to decay_category)
MIGRATION_V6_SQL = """
-- Rename temporal_relevance column to decay_category and update values
-- SQLite requires table recreation to rename columns and modify CHECK constraints
--
-- Value mapping:
--   'permanent' -> 'permanent' (unchanged)
--   'recent'    -> 'standard'  (normal decay)
--   'dated'     -> 'ephemeral' (fast decay)
--
-- New decay categories control memory freshness decay rate:
--   'permanent': Never decays (core identity, lasting preferences)
--   'standard':  30-day half-life (events, discussions, insights)
--   'ephemeral': 7-day half-life (situational observations)

-- Disable foreign keys during migration
PRAGMA foreign_keys=OFF;

-- Create new table with decay_category column
CREATE TABLE memories_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    embedding BLOB NOT NULL,

    -- Source tracking
    source_conversation_ids JSON,
    source_session_id INTEGER REFERENCES sessions(id),

    -- Temporal fields
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_accessed_at TIMESTAMP,
    access_count INTEGER DEFAULT 0,
    source_timestamp TIMESTAMP,
    decay_category TEXT DEFAULT 'standard' CHECK (decay_category IN ('permanent', 'standard', 'ephemeral')),

    -- Scoring
    importance REAL DEFAULT 0.5 CHECK (importance >= 0 AND importance <= 1),
    memory_type TEXT CHECK (memory_type IN ('fact', 'preference', 'event', 'reflection', 'observation'))
);

-- Copy existing data with value mapping
INSERT INTO memories_new (
    id, content, embedding, source_conversation_ids, source_session_id,
    created_at, last_accessed_at, access_count, source_timestamp,
    decay_category, importance, memory_type
)
SELECT
    id, content, embedding, source_conversation_ids, source_session_id,
    created_at, last_accessed_at, access_count, source_timestamp,
    CASE temporal_relevance
        WHEN 'permanent' THEN 'permanent'
        WHEN 'dated' THEN 'ephemeral'
        ELSE 'standard'  -- 'recent' and any other values become 'standard'
    END,
    importance, memory_type
FROM memories;

-- Drop old table
DROP TABLE memories;

-- Rename new table
ALTER TABLE memories_new RENAME TO memories;

-- Recreate indexes
CREATE INDEX IF NOT EXISTS idx_memories_recency ON memories(last_accessed_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_source_time ON memories(source_timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_memories_type ON memories(memory_type);
CREATE INDEX IF NOT EXISTS idx_memories_importance ON memories(importance DESC);

-- Re-enable foreign keys
PRAGMA foreign_keys=ON;
"""

# Migration SQL for v6 -> v7 (remove relationships table - feature removed)
MIGRATION_V7_SQL = """
-- Remove relationships table (affinity/trust feature removed in favor of emergent relationships)
DROP TABLE IF EXISTS relationships;
"""

# Migration SQL for v7 -> v8 (add intentions table for reminder/planning system)
MIGRATION_V8_SQL = """
-- Intentions table: AI-created reminders, goals, and plans
-- Enables the AI to track things it wants to follow up on
CREATE TABLE IF NOT EXISTS intentions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- What type of intention this is
    type TEXT NOT NULL CHECK (type IN ('reminder', 'goal')),

    -- The content of the intention (what to do/remember)
    content TEXT NOT NULL,

    -- Why this intention was created (context from conversation)
    context TEXT,

    -- When this intention should trigger
    -- For time-based: ISO timestamp or relative descriptor
    trigger_type TEXT NOT NULL CHECK (trigger_type IN ('time', 'next_session')),
    trigger_at TIMESTAMP,  -- For time-based triggers

    -- Lifecycle
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'triggered', 'completed', 'dismissed')),
    priority INTEGER DEFAULT 5 CHECK (priority >= 1 AND priority <= 10),

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    triggered_at TIMESTAMP,
    completed_at TIMESTAMP,

    -- Outcome note (when completed)
    outcome TEXT,

    -- Source session for context
    source_session_id INTEGER REFERENCES sessions(id)
);

-- Indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_intentions_status ON intentions(status);
CREATE INDEX IF NOT EXISTS idx_intentions_trigger_at ON intentions(trigger_at) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_intentions_type ON intentions(type);
"""

# Migration SQL for v8 -> v9 (add communication_log table)
MIGRATION_V9_SQL = """
-- Communication log table: tracks sent emails and SMS messages
CREATE TABLE IF NOT EXISTS communication_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL CHECK (type IN ('email', 'sms')),
    recipient TEXT NOT NULL,
    subject TEXT,  -- NULL for SMS
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'sent' CHECK (status IN ('sent', 'failed')),
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for communication log
CREATE INDEX IF NOT EXISTS idx_communication_log_type ON communication_log(type);
CREATE INDEX IF NOT EXISTS idx_communication_log_created ON communication_log(created_at DESC);
"""

# Migration SQL for v9 -> v10 (replace SMS with Telegram in communication_log)
MIGRATION_V10_SQL = """
-- Replace SMS with Telegram in communication_log type constraint
-- SQLite requires table recreation to modify CHECK constraints

-- Disable foreign keys during migration
PRAGMA foreign_keys=OFF;

-- Create new table with telegram type
CREATE TABLE communication_log_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL CHECK (type IN ('email', 'telegram')),
    recipient TEXT NOT NULL,
    subject TEXT,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'sent' CHECK (status IN ('sent', 'failed')),
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Copy existing data, converting 'sms' to 'telegram'
INSERT INTO communication_log_new (id, type, recipient, subject, body, status, error_message, created_at)
SELECT id,
       CASE type WHEN 'sms' THEN 'telegram' ELSE type END,
       recipient, subject, body, status, error_message, created_at
FROM communication_log;

-- Drop old table
DROP TABLE communication_log;

-- Rename new table
ALTER TABLE communication_log_new RENAME TO communication_log;

-- Recreate indexes
CREATE INDEX IF NOT EXISTS idx_communication_log_type ON communication_log(type);
CREATE INDEX IF NOT EXISTS idx_communication_log_created ON communication_log(created_at DESC);

-- Re-enable foreign keys
PRAGMA foreign_keys=ON;
"""

# Migration SQL for v10 -> v11 (add active_thoughts table)
MIGRATION_V11_SQL = """
-- Active thoughts: AI's working memory - ranked list of current priorities
-- This is the AI's private "stream of consciousness" that persists across sessions
CREATE TABLE IF NOT EXISTS active_thoughts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rank INTEGER NOT NULL UNIQUE CHECK(rank >= 1 AND rank <= 10),
    slug TEXT NOT NULL,
    topic TEXT NOT NULL,
    elaboration TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Index for efficient rank-ordered queries
CREATE INDEX IF NOT EXISTS idx_active_thoughts_rank ON active_thoughts(rank);
"""

# Migration SQL for v11 -> v12 (add memory_category column for dual-track extraction)
MIGRATION_V12_SQL = """
-- Add memory_category column to distinguish episodic vs factual memories
-- Episodic: Narrative memories about what happened (existing behavior)
-- Factual: Concrete facts extracted from conversations (new)
--
-- All existing memories are marked as 'episodic' since they were extracted
-- using the narrative-focused extraction prompts.

-- Add the column with default value
ALTER TABLE memories ADD COLUMN memory_category TEXT DEFAULT 'episodic'
    CHECK (memory_category IN ('episodic', 'factual'));

-- Create index for category-filtered queries
CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(memory_category);
"""

# Migration SQL for v12 -> v13 (add UNIQUE constraint on active_thoughts.slug)
MIGRATION_V13_SQL = """
-- Add UNIQUE constraint on active_thoughts.slug column
-- This enforces at the database level what the Python code already validates:
-- each slug must be unique within the active thoughts list.
--
-- SQLite doesn't support adding constraints to existing columns, so we need
-- to recreate the table.

-- Disable foreign keys during migration
PRAGMA foreign_keys=OFF;

-- Create new table with UNIQUE constraint on slug
CREATE TABLE active_thoughts_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rank INTEGER NOT NULL UNIQUE CHECK(rank >= 1 AND rank <= 10),
    slug TEXT NOT NULL UNIQUE,
    topic TEXT NOT NULL,
    elaboration TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Copy existing data
INSERT INTO active_thoughts_new (id, rank, slug, topic, elaboration, created_at, updated_at)
SELECT id, rank, slug, topic, elaboration, created_at, updated_at
FROM active_thoughts;

-- Drop old table
DROP TABLE active_thoughts;

-- Rename new table
ALTER TABLE active_thoughts_new RENAME TO active_thoughts;

-- Recreate index
CREATE INDEX IF NOT EXISTS idx_active_thoughts_rank ON active_thoughts(rank);

-- Re-enable foreign keys
PRAGMA foreign_keys=ON;
"""

# Migration SQL for v13 -> v14 (add curiosity_goals table)
MIGRATION_V14_SQL = """
-- Curiosity goals: AI's current and historical curiosity-driven exploration targets
-- This table tracks the AI's curiosity system - what topics it wants to explore,
-- what it has explored, and cooldowns before revisiting topics.
CREATE TABLE IF NOT EXISTS curiosity_goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('dormant_revival', 'depth_seeking', 'fresh_discovery')),
    context TEXT,
    source_memory_id INTEGER REFERENCES memories(id),
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'explored', 'deferred', 'declined')),
    activated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP,
    outcome_notes TEXT,
    cooldown_until TIMESTAMP,
    interaction_count INTEGER DEFAULT 0
);

-- Indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_curiosity_status ON curiosity_goals(status);
CREATE INDEX IF NOT EXISTS idx_curiosity_cooldown ON curiosity_goals(cooldown_until);
CREATE INDEX IF NOT EXISTS idx_curiosity_source ON curiosity_goals(source_memory_id);
"""

# Migration SQL for v14 -> v15 (add interaction_count to curiosity_goals)
MIGRATION_V15_SQL = """
-- Add interaction_count column to track conversation depth on curiosity topics
ALTER TABLE curiosity_goals ADD COLUMN interaction_count INTEGER DEFAULT 0;
"""

# Migration SQL for v15 -> v16 (fix CHECK constraint on curiosity_goals.category)
# The fresh_discovery category was added to SCHEMA_SQL and MIGRATION_V14_SQL after
# some databases were already created with only 2 categories. SQLite cannot ALTER
# CHECK constraints, so we must recreate the table.
MIGRATION_V16_SQL = """
-- Fix CHECK constraint on curiosity_goals.category to include fresh_discovery
-- SQLite requires table recreation to modify constraints

-- Disable foreign keys during migration
PRAGMA foreign_keys=OFF;

-- Create new table with correct CHECK constraint (includes fresh_discovery)
CREATE TABLE curiosity_goals_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('dormant_revival', 'depth_seeking', 'fresh_discovery')),
    context TEXT,
    source_memory_id INTEGER REFERENCES memories(id),
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'explored', 'deferred', 'declined')),
    activated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP,
    outcome_notes TEXT,
    cooldown_until TIMESTAMP,
    interaction_count INTEGER DEFAULT 0
);

-- Copy existing data
INSERT INTO curiosity_goals_new (
    id, content, category, context, source_memory_id, status,
    activated_at, resolved_at, outcome_notes, cooldown_until, interaction_count
)
SELECT
    id, content, category, context, source_memory_id, status,
    activated_at, resolved_at, outcome_notes, cooldown_until, interaction_count
FROM curiosity_goals;

-- Drop old table
DROP TABLE curiosity_goals;

-- Rename new table
ALTER TABLE curiosity_goals_new RENAME TO curiosity_goals;

-- Recreate indexes
CREATE INDEX IF NOT EXISTS idx_curiosity_status ON curiosity_goals(status);
CREATE INDEX IF NOT EXISTS idx_curiosity_cooldown ON curiosity_goals(cooldown_until);
CREATE INDEX IF NOT EXISTS idx_curiosity_source ON curiosity_goals(source_memory_id);

-- Re-enable foreign keys
PRAGMA foreign_keys=ON;
"""

# Migration SQL for v16 -> v17 (add active_thoughts_history table)
MIGRATION_V17_SQL = """
-- Active thoughts history: append-only archive for longitudinal state tracking
-- Before each thought update, current thoughts are copied here.
-- This makes active_thoughts the only previously non-reconstructable state
-- fully recoverable at any historical point in time.
CREATE TABLE IF NOT EXISTS active_thoughts_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    archived_at TIMESTAMP NOT NULL,
    rank INTEGER NOT NULL,
    slug TEXT NOT NULL,
    topic TEXT NOT NULL,
    elaboration TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL
);

-- Index for finding the latest snapshot before a given date
CREATE INDEX IF NOT EXISTS idx_thoughts_history_archived ON active_thoughts_history(archived_at DESC);

-- Seed history with current active thoughts (if any) so pre-migration state is preserved
INSERT INTO active_thoughts_history (archived_at, rank, slug, topic, elaboration, created_at, updated_at)
SELECT CURRENT_TIMESTAMP, rank, slug, topic, elaboration, created_at, updated_at
FROM active_thoughts;
"""


# Migration SQL for v17 -> v18 (add growth_threads table)
MIGRATION_V18_SQL = """
-- Growth threads: AI's long-term developmental aspirations
-- Tracks patterns the AI wants to integrate over weeks/months.
-- Unlike active thoughts (volatile, replaced wholesale) or memories (passive, backward-looking),
-- growth threads operate on a weeks-to-months timescale and represent "what I am becoming."
CREATE TABLE IF NOT EXISTS growth_threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT 'seed' CHECK (stage IN ('seed', 'growing', 'integrating', 'dormant', 'abandoned')),
    stage_changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for growth threads
CREATE INDEX IF NOT EXISTS idx_growth_threads_stage ON growth_threads(stage);
CREATE INDEX IF NOT EXISTS idx_growth_threads_slug ON growth_threads(slug);
"""

# Migration SQL for v18 -> v19 (add reading_sessions table for novel reading)
MIGRATION_V19_SQL = """
-- Reading sessions: tracks progress through a novel being read chapter-by-chapter
-- Only one active reading session at a time (status = 'reading')
CREATE TABLE IF NOT EXISTS reading_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    title TEXT,
    status TEXT NOT NULL DEFAULT 'reading' CHECK (status IN ('reading', 'completed', 'abandoned')),

    -- Structure metadata (populated by parser on open_book)
    total_chapters INTEGER NOT NULL DEFAULT 0,
    total_arcs INTEGER DEFAULT 0,
    has_prologue BOOLEAN DEFAULT FALSE,
    structure_json JSON,

    -- Progress tracking
    current_chapter INTEGER DEFAULT 0,
    current_arc INTEGER DEFAULT 0,
    chapters_read JSON DEFAULT '[]',

    -- Timestamps
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_read_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_reading_sessions_status ON reading_sessions(status);
"""

# Migration SQL for v19 -> v20 (add observations persistence for novel reading resume)
# v19 creates the table without observations_json; v20 adds the column.
# The full CREATE TABLE schema (for fresh installs) already includes observations_json.
MIGRATION_V20_SQL = """
ALTER TABLE reading_sessions ADD COLUMN observations_json TEXT DEFAULT '[]';
"""


class Database:
    """SQLite database manager with WAL mode and thread-safe connections."""

    def __init__(
        self,
        db_path: Path,
        busy_timeout_ms: int = 10000,
    ):
        """
        Initialize the database.

        Args:
            db_path: Path to the SQLite database file
            busy_timeout_ms: Timeout for busy/locked database
        """
        self.db_path = db_path
        self.busy_timeout_ms = busy_timeout_ms
        self._initialized = False

    def initialize(self) -> bool:
        """
        Initialize the database: create file, set WAL mode, apply schema.

        Returns:
            True if successful, False otherwise
        """
        try:
            # Ensure data directory exists
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            log_section("Initializing database", "📁")
            log_config("Path", str(self.db_path), indent=1)

            # Create connection and configure
            with self.get_connection() as conn:
                # Enable WAL mode for better concurrency
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute(f"PRAGMA busy_timeout={self.busy_timeout_ms}")

                # Check current schema version
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
                )
                if cursor.fetchone() is None:
                    # Fresh database, apply full schema
                    conn.executescript(SCHEMA_SQL)
                    conn.execute(
                        "INSERT INTO schema_version (version) VALUES (?)",
                        (SCHEMA_VERSION,)
                    )
                    log_config("Schema", f"Created (v{SCHEMA_VERSION})", indent=1)
                else:
                    # Check for migrations
                    cursor = conn.execute(
                        "SELECT MAX(version) FROM schema_version"
                    )
                    current_version = cursor.fetchone()[0] or 0
                    if current_version < SCHEMA_VERSION:
                        self._apply_migrations(conn, current_version)
                    log_config("Schema", f"Version {current_version}", indent=1)

                # Verify WAL mode
                cursor = conn.execute("PRAGMA journal_mode")
                mode = cursor.fetchone()[0]
                log_config("Mode", f"{mode.upper()} (Write-Ahead Logging)", indent=1)

            log_success("Database ready")
            self._initialized = True
            return True

        except Exception as e:
            log_error(f"Database initialization failed: {e}")
            return False

    def _apply_migrations(self, conn: sqlite3.Connection, from_version: int) -> None:
        """
        Apply schema migrations from from_version to SCHEMA_VERSION.

        Raises:
            Exception: If any migration fails - we fail hard to prevent
                      running with a broken/inconsistent schema.
        """
        try:
            # Apply migrations incrementally
            if from_version < 2:
                log_config("Applying migration", "v1 → v2 (core_memories, relationships)", indent=1)
                conn.executescript(MIGRATION_V2_SQL)

            if from_version < 3:
                log_config("Applying migration", "v2 → v3 (narrative category)", indent=1)
                conn.executescript(MIGRATION_V3_SQL)

            if from_version < 4:
                log_config("Applying migration", "v3 → v4 (relationships 0-100 scale)", indent=1)

                # Idempotency check: see if relationships table already has integer scale
                # by checking if the affinity column type/constraints match v4 schema
                cursor = conn.execute("PRAGMA table_info(relationships)")
                columns = {row[1]: row[2] for row in cursor.fetchall()}

                # Check if affinity exists and appears to be on the new scale
                # If relationships table doesn't exist or has unexpected schema, proceed with migration
                if "affinity" in columns:
                    # Check if we have integer values already (v4) vs float values (v3)
                    cursor = conn.execute("SELECT affinity FROM relationships WHERE id = 1")
                    row = cursor.fetchone()
                    if row is not None:
                        affinity_value = row[0]
                        # If affinity is already an integer >= 0 and <= 100, likely already migrated
                        # Old schema used -1.0 to 1.0 floats
                        if isinstance(affinity_value, int) or (
                            isinstance(affinity_value, float) and
                            affinity_value == int(affinity_value) and
                            0 <= affinity_value <= 100
                        ):
                            # Could be already migrated - check if value makes sense
                            # Old scale: -1.0 to 1.0 would convert to 0-100
                            # If value is clearly in 0-100 integer range, skip migration
                            log_config("Skipping v4 migration", "relationships table appears already migrated", indent=1)
                        else:
                            conn.executescript(MIGRATION_V4_SQL)
                    else:
                        # No data, safe to run migration
                        conn.executescript(MIGRATION_V4_SQL)
                else:
                    # Column doesn't exist or table doesn't exist, run migration
                    conn.executescript(MIGRATION_V4_SQL)

            if from_version < 5:
                log_config("Applying migration", "v4 → v5 (remove CHECK constraints from conversations)", indent=1)
                conn.executescript(MIGRATION_V5_SQL)

            if from_version < 6:
                log_config("Applying migration", "v5 → v6 (rename temporal_relevance to decay_category)", indent=1)
                conn.executescript(MIGRATION_V6_SQL)

            if from_version < 7:
                log_config("Applying migration", "v6 → v7 (remove relationships table)", indent=1)
                conn.executescript(MIGRATION_V7_SQL)

            if from_version < 8:
                log_config("Applying migration", "v7 → v8 (add intentions table)", indent=1)
                conn.executescript(MIGRATION_V8_SQL)

            if from_version < 9:
                log_config("Applying migration", "v8 → v9 (add communication_log table)", indent=1)
                conn.executescript(MIGRATION_V9_SQL)

            if from_version < 10:
                log_config("Applying migration", "v9 → v10 (replace SMS with Telegram)", indent=1)
                conn.executescript(MIGRATION_V10_SQL)

            if from_version < 11:
                log_config("Applying migration", "v10 → v11 (add active_thoughts table)", indent=1)
                conn.executescript(MIGRATION_V11_SQL)

            if from_version < 12:
                log_config("Applying migration", "v11 → v12 (add memory_category for dual-track extraction)", indent=1)
                conn.executescript(MIGRATION_V12_SQL)

            if from_version < 13:
                log_config("Applying migration", "v12 → v13 (add UNIQUE constraint on active_thoughts.slug)", indent=1)
                conn.executescript(MIGRATION_V13_SQL)

            if from_version < 14:
                log_config("Applying migration", "v13 → v14 (add curiosity_goals table)", indent=1)
                conn.executescript(MIGRATION_V14_SQL)

            if from_version < 15:
                log_config("Applying migration", "v14 → v15 (add interaction_count to curiosity_goals)", indent=1)
                conn.executescript(MIGRATION_V15_SQL)

            if from_version < 16:
                log_config("Applying migration", "v15 → v16 (fix CHECK constraint on curiosity_goals.category)", indent=1)
                conn.executescript(MIGRATION_V16_SQL)

            if from_version < 17:
                log_config("Applying migration", "v16 → v17 (add active_thoughts_history table)", indent=1)
                conn.executescript(MIGRATION_V17_SQL)

            if from_version < 18:
                log_config("Applying migration", "v17 → v18 (add growth_threads table)", indent=1)
                conn.executescript(MIGRATION_V18_SQL)

            if from_version < 19:
                log_config("Applying migration", "v18 → v19 (add reading_sessions table for novel reading)", indent=1)
                conn.executescript(MIGRATION_V19_SQL)

            if from_version < 20:
                log_config("Applying migration", "v19 → v20 (add observations persistence for novel reading)", indent=1)
                conn.executescript(MIGRATION_V20_SQL)

            # Record new version
            conn.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (SCHEMA_VERSION,)
            )
            log_config("Migration", f"v{from_version} → v{SCHEMA_VERSION}", indent=1)

        except Exception as e:
            # Fail hard - don't let the app continue with broken schema
            log_error(f"Migration failed (v{from_version} → v{SCHEMA_VERSION}): {e}")
            raise RuntimeError(
                f"Database migration failed: {e}. "
                f"Please fix the database or delete it to start fresh."
            ) from e

    @contextmanager
    def get_connection(self) -> sqlite3.Connection:
        """
        Get a database connection with proper configuration.

        Yields:
            Configured SQLite connection
        """
        conn = sqlite3.connect(
            self.db_path,
            timeout=self.busy_timeout_ms / 1000,
            check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def execute(
        self,
        sql: str,
        params: Tuple = (),
        fetch: bool = False
    ) -> Optional[List[sqlite3.Row]]:
        """
        Execute a SQL statement.

        Args:
            sql: SQL statement
            params: Parameters for the statement
            fetch: Whether to fetch and return results

        Returns:
            List of rows if fetch=True, None otherwise
        """
        with self.get_connection() as conn:
            cursor = conn.execute(sql, params)
            if fetch:
                return cursor.fetchall()
            return None

    def execute_many(self, sql: str, params_list: List[Tuple]) -> None:
        """Execute a SQL statement with multiple parameter sets."""
        with self.get_connection() as conn:
            conn.executemany(sql, params_list)

    def get_state(self, key: str, default: Any = None) -> Any:
        """Get a value from the state table."""
        result = self.execute(
            "SELECT value FROM state WHERE key = ?",
            (key,),
            fetch=True
        )
        if result:
            value = result[0]["value"]
            # Handle SQLite JSON columns returning native Python types
            # (SQLite 3.38+ may return int/float/bool directly from JSON columns)
            if isinstance(value, str):
                return json.loads(value)
            # Value is already a Python type (int, float, bool, None, list, dict)
            return value
        return default

    def set_state(self, key: str, value: Any) -> None:
        """Set a value in the state table."""
        self.execute(
            """
            INSERT INTO state (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = ?, updated_at = ?
            """,
            (key, json.dumps(value), datetime.now().isoformat(),
             json.dumps(value), datetime.now().isoformat())
        )

    def get_stats(self) -> dict:
        """Get database statistics."""
        stats = {}

        with self.get_connection() as conn:
            # Session count
            cursor = conn.execute("SELECT COUNT(*) FROM sessions")
            stats["total_sessions"] = cursor.fetchone()[0]

            # Active session
            cursor = conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE ended_at IS NULL"
            )
            stats["active_sessions"] = cursor.fetchone()[0]

            # Conversation count
            cursor = conn.execute("SELECT COUNT(*) FROM conversations")
            stats["total_conversations"] = cursor.fetchone()[0]

            # Memory count
            cursor = conn.execute("SELECT COUNT(*) FROM memories")
            stats["total_memories"] = cursor.fetchone()[0]

            # Core memory count
            cursor = conn.execute("SELECT COUNT(*) FROM core_memories")
            stats["core_memories"] = cursor.fetchone()[0]

            # Unprocessed conversations
            cursor = conn.execute(
                "SELECT COUNT(*) FROM conversations WHERE processed_for_memory = FALSE"
            )
            stats["unprocessed_conversations"] = cursor.fetchone()[0]

        return stats


# Global database instance
_db: Optional[Database] = None


def get_database() -> Database:
    """Get the global database instance."""
    if _db is None:
        raise RuntimeError("Database not initialized. Call init_database() first.")
    return _db


def init_database(db_path: Path, busy_timeout_ms: int = 10000) -> Database:
    """Initialize the global database instance."""
    global _db
    _db = Database(db_path, busy_timeout_ms)
    _db.initialize()
    return _db
