# Feature Evaluation: Pattern Project UI Ideas

*Evaluated against the current codebase architecture on 2026-02-05*

## Current Architecture Context

- **Stack**: Python 3 / PyQt5 GUI / SQLite (WAL) / Anthropic Claude API
- **UI**: PyQt5 with QTextBrowser (HTML rendering), custom theme system, QPropertyAnimation
- **Memory**: Semantic vector search (sentence-transformers, 384-dim), dual-track episodic+factual, decay categories (permanent/standard/ephemeral)
- **Agency**: System pulse (configurable timer), proactive triggers, curiosity engine, growth threads, active thoughts (ranked 1-10)
- **Data flow**: Ephemeral context windows -- prompt rebuilt from scratch each turn from ~12 prioritized context sources. Memory lives in SQLite, not context.
- **Existing visualizations**: Dev window with memory scoring tabs, toast notifications with fade animations, streaming indicators, status bar with operation types, command palette

---

## 1. Reasoning Trees

**Concept**: Show a simplified tree diagram of reasoning paths the AI explores, making backtracking and pruning visible.

### Complexity: High

- Claude's extended thinking is a single text blob (`thinking` content block), not structured tree data. Extracting tree structure requires either:
  - **(a)** Parsing thinking text with NLP/heuristics to infer structure -- fragile, inaccurate
  - **(b)** Secondary API call to have Claude annotate its own thinking into tree form -- expensive
  - **(c)** Waiting for Anthropic to expose structured reasoning data -- not currently available
- PyQt5 has no built-in tree/graph visualization. Options: QPainter/QGraphicsScene (substantial), or QWebEngineView with D3.js (dependency addition)
- Existing `dev_window.py` (1295 lines) shows thinking text as raw output, no structural parsing

### Token Usage: Significant

- Option (b) doubles token cost per response
- Extended thinking already costs 10,000+ tokens per response
- No clean path to structured data from current API

### User Impact: Medium

- Visually compelling, but Claude's thinking isn't truly tree-structured -- it's a stream of considerations. Forcing it into a tree risks misrepresenting the reasoning
- "Delightful failure" argument is valid only if the tree is accurate

### Verdict

**Defer.** The bottleneck is data, not UI. Without structured reasoning output from the API, you're either guessing at structure or paying double tokens. **Prototype alternative**: collapsible sections in existing thinking text, based on paragraph boundaries. Achievable within the current `MarkdownRenderer` in `gui_components.py`.

---

## 2. Confidence Heatmaps

**Concept**: Subtle visual gradients on AI response text -- solid for high confidence, shimmer/underlay for hallucination-prone segments.

### Complexity: High (full) / Low (heuristic)

- Claude's API does not expose per-token confidence scores or logprobs
- Options:
  - **(a)** Secondary evaluation pass ("rate your confidence in each claim") -- expensive, self-assessment unreliable
  - **(b)** Heuristic hedging detection (regex for "I think," "probably," "might") -- cheap, crude but useful
  - **(c)** Cross-reference claims against memory/known facts -- requires entity extraction pipeline
- Rendering: QTextBrowser supports `<span>` background-color. Full CSS shimmer needs QWebEngineView (QTextBrowser is CSS 2.1 subset)

### Token Usage

- Option (a): Doubles token cost
- Option (b): Zero
- Option (c): Moderate (entity extraction via smaller model)

### User Impact: High (if accurate) / Medium (heuristic)

- Genuinely useful for helping users know when to double-check
- Inaccurate confidence signals are actively harmful (false sense of security)
- Hedging-language detection is imperfect but surfaces the AI's own uncertainty signals at zero cost

### Verdict

**Start with heuristic hedging detection.** Regex-based scanning of response text for uncertainty markers, rendered as subtle background tints in HTML. Zero token cost, implementable in `gui_components.py` `MarkdownRenderer`. Accept imperfection. Full confidence heatmap requires API-level changes from Anthropic.

---

## 3. Gaze/Focus Simulation

**Concept**: Visual cues indicating what the AI is currently processing -- glow around window being scraped, file being analyzed.

### Complexity: Medium (in-app) / Very High (cross-window)

- Existing `StatusManager` already tracks: `STATUS_THINKING`, `STATUS_TOOLS`, `STATUS_SEARCHING`
- Dev window shows tool execution details in real-time via signals
- Cross-window effects (glowing around other windows) requires X11/Wayland compositing -- fragile, intrusive on Linux
- In-app "focus panel": enhanced status with context (file paths, URLs, search queries). Reuses existing signal infrastructure: `emit_command_executed()`, `emit_memory_recall()`

### Token Usage: None

Purely UI feature consuming existing signals.

### User Impact: Medium-Low

- In-app focus indication is useful but incremental over existing status bar
- Cross-window effects are technically fragile on Linux
- Strongest version: persistent sidebar showing real-time feed of operations -- a compact, always-visible mini dev window

### Verdict

**Low-hanging fruit as enhanced status panel.** Collapsible right panel in main GUI showing live activity feed. Reuses dev window signals. Touches `gui.py` (layout) with existing signal infrastructure. Skip cross-window effects.

---

## 4. Ambient Presence Indicators (Enhanced)

**Concept**: Visual state not tied to active conversation -- animations/color shifts reflecting processing state, digesting, curious, reflecting, idle-but-present.

### Complexity: Low-Medium

- Infrastructure already exists:
  - `system_pulse.py`: idle/active cycle with configurable intervals
  - `proactive.py`: trigger states (IDLE, REFLECTION, CURIOSITY, GREETING, REMINDER)
  - `active_thoughts/manager.py`: ranked topics (1-10) with elaboration
  - `growth_threads/manager.py`: stages (seed/growing/integrating/dormant/abandoned)
  - `curiosity/engine.py`: current goal, exploration state
- Current UI reduces all this to a countdown timer
- State machine mapping: IDLE → DIGESTING (post-extraction) → CURIOUS (curiosity active) → REFLECTING (pulse fired) → PRESENT (available, no process)
- QPropertyAnimation already used for toast notifications; smooth color transitions are proven in codebase

### Token Usage: None

All state data already exists in memory. Purely UI-side.

### User Impact: High

- Most philosophically aligned feature for this project
- Transforms experience from "tool waiting for input" to "entity with inner life"
- Key insight: no need to fabricate mood -- genuine internal state already exists (active thoughts, growth threads, curiosity goals, triggered intentions)
- These are real signals, not theater

### Verdict

**Highest priority. Best ratio of impact to effort.** Define a state enum mapping existing backend states to visual modes. Add ambient indicator widget (colored orb, gradient bar, or animated element) with smooth transitions via QPropertyAnimation. Data sources: `system_pulse.py`, `proactive.py`, `active_thoughts/manager.py`, `curiosity/engine.py`. Touch points: new widget class in `gui_components.py`, state mapping logic, integration in `gui.py` header/sidebar.

---

## 5. Proactive Surfacing

**Concept**: Gentle visual artifacts surfacing connections -- cards saying "This connects to three weeks ago," timeline of conversation clusters and recurring themes.

### Complexity: Medium-High

- Partially existing backend:
  - Memory search with temporal metadata (`created_at`, decay categories)
  - Session tracking with timestamps and turn counts
  - Curiosity engine identifies dormant (>7 days) and fresh (<48h) memories
  - Intentions system has "next session" triggers
  - Warmth cache already boosts recently-accessed memories
- Missing pieces:
  - **Cross-session theme detection**: No mechanism clusters conversations by topic across sessions. Needs periodic embedding-based clustering (sentence-transformers already loaded)
  - **Connection detection**: When message arrives, check if highly-relevant memory results are temporally distant (>2 weeks). Lightweight addition to `vector_store.py` search
  - **Card UI**: Clarification dialog in `gui.py` already implements styled card pattern. Adaptable
  - **Timeline visualization**: Requires QGraphicsScene or embedded web view. More complex

### Token Usage: Low-Medium

- Connection detection: minimal -- vector search already happening, just add temporal-distance filter
- Theme clustering: local compute (sentence-transformers), no API cost
- Generating "This connects to..." text: small API call or templated

### User Impact: Very High

- Most transformative feature on the list
- Leverages existing memory architecture's greatest strength (semantic search with temporal metadata) and makes it *visible* rather than hidden in prompt assembly
- The "sticky note" metaphor: non-intrusive cards when relevance + temporal distance exceed threshold

### Verdict

**High priority, phased approach.**

**Phase 1**: During memory recall (every turn in `semantic_memory.py`), flag results with high relevance but >14 days age. Surface as subtle card below response. Changes to: `vector_store.py` (add temporal distance to returns), `builder.py` (emit signal with flagged connections), `gui.py` (render connection card).

**Phase 2**: Background clustering for theme timeline. Larger effort, use HDBSCAN or k-means on memory embeddings. Periodic batch job.

---

## 6. Spatial/Visual Memory (Constellation Map)

**Concept**: Secondary panel showing graph/web of memory relationships -- nodes for themes, edges for connections, clickable to see conversation fragments.

### Complexity: Very High

- 384-dimensional embeddings exist for every memory. 2D visualization requires dimensionality reduction (UMAP, t-SNE, PCA) -- compute-intensive for large memory sets
- Interactive graph in PyQt5: QGraphicsScene can work but building zoomable, pannable, force-directed graph with clickable nodes is essentially a custom graph visualization library. Alternative: QWebEngineView with D3.js/Sigma.js/Cytoscape.js
- Real-time updates: re-running UMAP on every new memory is expensive; incremental approaches exist but complex
- Data supports it: each memory has `source_conversation_ids` (JSON), `memory_category`, `importance`, and `embedding`

### Token Usage: None (local compute only)

CPU cost for UMAP/t-SNE on hundreds of memories is non-trivial (seconds to minutes).

### User Impact: Very High (if well-executed) / Medium (if poorly executed)

- Beautiful, responsive constellation map would be revelatory -- seeing intellectual territory topology
- Laggy or cluttered graph is worse than nothing
- Execution quality is the determining factor

### Verdict

**High impact, highest risk.** Recommended approach: QWebEngineView embedding D3.js force-directed graph. Pre-compute 2D positions using UMAP in background thread (concurrency infrastructure in `concurrency/locks.py` supports this). Update positions periodically, not per-insertion. Store 2D coordinates alongside embeddings in database. MVP as standalone window (like `dev_window.py`) rather than integrated panel.

---

## 7. Canvas/Whiteboard Mode

**Concept**: Shared visual space for spatial concept arrangement, diagrams, sketches -- especially for pattern philosophy work.

### Complexity: Very High (full whiteboard) / Low-Medium (Mermaid diagrams)

- Full whiteboard needs:
  - Infinite canvas with pan/zoom (QGraphicsScene supports this)
  - Shape primitives, drag-and-drop, connections
  - AI tools to read/write canvas (new tool definitions in `definitions.py`)
  - Serialization/persistence, undo/redo
- AI integration is hardest part: tools for "place node at position," "draw connection," "read canvas state"
- Simpler alternative: Mermaid.js diagram rendering. Markdown renderer already handles code blocks; adding mermaid rendering is a known pattern. AI can already generate mermaid syntax

### Token Usage: Low-Medium

- Canvas state in context: 500-2000 tokens per turn for complex canvas
- Mermaid approach: diagram code is compact (50-200 tokens typically)

### User Impact: High (for pattern work)

- Pattern interference and relational philosophy work is inherently spatial
- But development cost is enormous for custom whiteboard vs. frequency of use
- Mermaid covers 80% of the diagramming need at 20% of the effort

### Verdict

**Start with Mermaid diagram rendering as 80/20 solution.** Add mermaid.js support via QWebEngineView or embedded JS in QTextBrowser. AI already generates mermaid syntax; just render it. Gets you flowcharts, mind maps, sequence diagrams, and relationship graphs with minimal implementation. Full whiteboard: consider integrating existing tool (Excalidraw, tldraw) via IPC rather than building from scratch.

---

## Comparative Summary

| Feature | Complexity | Token Cost | User Impact | Priority |
|---------|-----------|------------|-------------|----------|
| **Ambient Presence** | Low-Med | None | High | **1st** |
| **Proactive Surfacing** | Medium | Low | Very High | **2nd** |
| **Gaze/Focus Panel** | Low-Med | None | Medium | **3rd** |
| **Confidence Heuristics** | Low-Med | None | Medium | **4th** |
| **Canvas (Mermaid)** | Low-Med | Low | High (niche) | **5th** |
| **Spatial Memory Map** | Very High | None (CPU) | Very High | **6th** |
| **Reasoning Trees** | High | Significant | Medium | **7th** |

## Recommended Implementation Order

### Tier 1 -- Build Now
High impact, leverages existing architecture directly.

1. **Ambient Presence Indicators**: Map existing internal state (pulse, curiosity, thoughts, growth) to visual output. Data exists; needs rendering.
2. **Proactive Surfacing (Phase 1)**: Add temporal-distance flagging to memory recall. Surface "connection cards" for old-but-relevant memories.

### Tier 2 -- Build Next
Moderate effort, meaningful improvement.

3. **Gaze/Focus Panel**: Compact always-visible activity feed using existing dev window signals.
4. **Confidence Heuristics**: Regex-based hedging detection with subtle HTML tinting.
5. **Mermaid Diagrams**: Lightweight canvas substitute with disproportionate value.

### Tier 3 -- Build When Ready
High effort, high reward, high risk.

6. **Spatial Memory Map**: UMAP + D3.js constellation with background compute.
7. **Reasoning Trees**: Defer until API support or prototype with collapsible thinking sections.

---

## Key Insight

**The backend is ahead of the frontend.** The memory architecture, agency systems, and internal state tracking are sophisticated. The highest-value work is making that richness visible to the user, not adding new backend capabilities. The ambient presence and proactive surfacing features directly address this gap.
