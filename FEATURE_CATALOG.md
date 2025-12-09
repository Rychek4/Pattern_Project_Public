# Pattern Project - Feature Catalog

A comprehensive list of features for evaluation: what's working, what isn't, what's useful, what's awesome, and what's missing.

---

## 1. MEMORY SYSTEM

### 1.1 Conversation Memory
- Stores all chat turns with timestamps and metadata
- Tracks input type (text, voice, image)
- Records time gaps between messages

### 1.2 Semantic Memory Search
- Vector embeddings for similarity search (all-MiniLM-L6-v2 model)
- Multi-factor scoring:
  - 50% semantic similarity
  - 35% freshness (with decay half-life)
  - 15% access recency
- Memory types: fact, preference, event, reflection, observation
- Decay categories: permanent, standard (30-day), ephemeral (7-day)

### 1.3 Automated Memory Extraction
- Two-phase extraction process:
  1. Topic segmentation (identifies distinct conversation topics)
  2. Memory synthesis (creates consolidated memories per topic)
- Triggers after 10 unprocessed conversation turns
- Assigns importance scores and memory types automatically
- Prevents duplicate memories

### 1.4 Core Memories
- Permanent foundational knowledge (never decays)
- Categories: identity, relationship, preference, fact, narrative
- Auto-promotion from regular memories when highly relevant
- Manual addition via `/addcore` command

---

## 2. LLM INTEGRATION

### 2.1 Multi-Provider Routing
- Primary: Anthropic Claude (Opus/Sonnet) for conversation
- Secondary: Local KoboldCpp (Llama-3) for extraction tasks
- Automatic fallback on provider failure

### 2.2 Web Search Integration
- Anthropic's native web search capability
- Daily budget: 30 searches/day
- Per-request limit: 3 searches
- Citation tracking from search results

---

## 3. AGENCY & AUTONOMY

### 3.1 System Pulse Timer
- Sends periodic prompts during idle periods (default: 10 minutes)
- Encourages autonomous AI suggestions/actions
- Resets on user message
- Can be paused/resumed

### 3.2 Reminder/Intention System
- AI-created reminders with natural language time parsing
  - "in 2 hours", "tomorrow morning", "tonight at 8pm"
- Intention types: reminder, goal
- Trigger types: time-based, next_session
- Lifecycle: pending → triggered → completed/dismissed
- Priority levels (1-10)
- Background scheduler (checks every 30 seconds)

### 3.3 Visual Capture (Optional)
- Screenshot capture
- Webcam frame capture
- Gemini 2.5 Flash for image interpretation
- Configurable capture interval
- Currently disabled by default

### 3.4 Proactive Agency (Legacy)
- AI-initiated conversations based on idle time
- Status: DISABLED (replaced by System Pulse)

---

## 4. COMMAND SYSTEM

### 4.1 AI-Executable Commands
Commands the AI can embed in responses:

| Command | Purpose | Status |
|---------|---------|--------|
| `[[SEARCH: query]]` | AI-initiated memory recall | Active |
| `[[REMIND: when \| what \| context]]` | Create reminders | Active |
| `[[COMPLETE: id \| outcome]]` | Mark intention done | Active |
| `[[DISMISS: id]]` | Cancel intention | Active |
| `[[LIST_INTENTIONS]]` | Show pending reminders | Active |
| `[[SEND_SMS: message]]` | Send text message | Active (enabled) |
| `[[SEND_EMAIL: to \| subject \| body]]` | Send email | Active (disabled) |
| `[[WRITE_FILE: name \| content]]` | Create/update file | Active |
| `[[READ_FILE: name]]` | Read file content | Active |
| `[[LIST_FILES]]` | List stored files | Active |
| `[[DELETE_FILE: name]]` | Delete file | Active |

### 4.2 File Storage
- Sandboxed directory for AI-created files
- Allowed extensions: .txt, .md, .json, .csv
- 100KB max file size
- Security: no path traversal, filename sanitization

---

## 5. COMMUNICATION GATEWAYS

### 5.1 SMS Gateway
- Uses carrier email-to-SMS (AT&T txt.att.net)
- Single whitelisted recipient
- 160 character limit
- Rate limited: 10/hour
- Status: Enabled

### 5.2 Email Gateway
- Gmail SMTP with app password
- Recipient whitelist
- Rate limited: 20/hour
- Status: Disabled by default

---

## 6. USER INTERFACES

### 6.1 CLI Interface
Rich terminal chat with slash commands:

| Command | Purpose |
|---------|---------|
| `/help` | Show help |
| `/quit`, `/exit` | Exit app |
| `/new` | Start new session |
| `/end` | End session |
| `/stats` | Show statistics |
| `/memories` | List memories |
| `/search <query>` | Search memories |
| `/extract` | Force extraction |
| `/pause` / `/resume` | Control pulse timer |
| `/core` | Show core memories |
| `/addcore <text>` | Add core memory |
| `/pulse` | Manual pulse trigger |

### 6.2 HTTP API
REST endpoints for external integrations:
- `/health` - Health check
- `/chat` - Send message
- `/memories/search` - Search memories
- `/stats` - System statistics
- `/session/new`, `/session/end` - Session control
- `/extract` - Trigger extraction

### 6.3 GUI Interface
- PyQt5-based graphical interface
- Status: Present but requires PyQt5 dependency

### 6.4 Dev Window
- Debug interface showing internal operations
- Shows prompt assembly, command execution, memory scores
- Launch with `--dev` flag

---

## 7. CONTEXT & PROMPT BUILDING

### 7.1 Pluggable Context Sources
| Source | Purpose |
|--------|---------|
| Conversation | Last 15 exchanges |
| Core Memory | Permanent identity/preferences |
| Semantic Memory | Top 3 relevant retrieved memories |
| Temporal | Session duration, time gaps |
| Intention | Pending/triggered reminders |
| AI Commands | Documentation for available commands |
| System Pulse | Pulse prompt when timer fires |
| Visual | Screenshot/webcam descriptions |
| Dev Mode | Debug info when --dev used |

---

## 8. INFRASTRUCTURE

### 8.1 Database
- SQLite with WAL mode for concurrency
- Schema versioning (currently v9)
- Busy timeout handling

### 8.2 Concurrency Management
- Named locks for different resources
- Semaphore for LLM requests (max 3 concurrent)
- Exponential backoff retry logic
- Lock contention statistics

### 8.3 Temporal Tracking
- Session lifecycle (start/end times, duration)
- Turn-to-turn timing
- Idle warnings

### 8.4 Background Services
| Service | Frequency | Purpose |
|---------|-----------|---------|
| Memory Extractor | On threshold | Extract memories from conversations |
| System Pulse | 10 min idle | Encourage autonomous action |
| Reminder Scheduler | 30 seconds | Check and fire reminders |
| Visual Capture | 30 seconds | Capture and interpret images |
| Health Monitor | 30 seconds | System health checks |

---

## 9. LOGGING & DEBUGGING

### 9.1 Logging System
- Rich console formatting
- File logging with diagnostics
- Prompt/API request logging (JSONL)

### 9.2 Prompt Logger
- Records full prompts sent to LLM
- Token counts and timing
- Useful for debugging context issues

---

## QUICK REFERENCE: Feature Status

| Feature | Enabled | Notes |
|---------|---------|-------|
| Memory extraction | ✅ Yes | Automatic |
| Semantic search | ✅ Yes | Using embeddings |
| Core memories | ✅ Yes | Manual + auto-promotion |
| System pulse | ✅ Yes | 10 min default |
| Reminders | ✅ Yes | NLP time parsing |
| Web search | ✅ Yes | 30/day budget |
| SMS sending | ✅ Yes | AT&T gateway |
| Email sending | ❌ No | Disabled by default |
| Visual capture | ❌ No | Disabled by default |
| Proactive agency | ❌ No | Replaced by pulse |
| GUI | ⚠️ Partial | Needs PyQt5 |
| HTTP API | ⚠️ Config | Enable in config |

---

## QUESTIONS FOR EVALUATION

1. **Memory System**: Is the extraction working well? Are the right things being remembered?

2. **Semantic Search**: Does the AI recall relevant memories when needed?

3. **System Pulse**: Is 10 minutes the right interval? Are the autonomous suggestions useful?

4. **Reminders**: Are time-based reminders triggering correctly? Is the NLP parsing good?

5. **SMS/Email**: Have you used communication features? Any issues?

6. **Commands**: Which AI commands do you use? Which are unnecessary?

7. **Context Building**: Is the AI getting too much or too little context?

8. **Web Search**: Is 30/day sufficient? Is search being used appropriately?

9. **Performance**: Any lag or slowness issues?

10. **What's Missing?**: What capabilities would make this more useful?
