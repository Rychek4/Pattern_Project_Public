# Plan: Add Process Panel to Web UI

## Overview

Port the PyQt5 process panel (`interface/process_panel.py`) to the web UI. The process panel is a real-time sidebar that visualizes the AI's internal processing pipeline — message receipt, prompt assembly, streaming, tool calls, continuation rounds, memory extraction, and system activity.

---

## Architecture

The web UI already receives most pipeline events over WebSocket. The process panel will be a new left sidebar (collapsible) with a dedicated JavaScript module that subscribes to these events and renders them as a vertical node tree — matching the PyQt5 panel's visual structure: **message groups → round groups → individual nodes**.

### Files to create/modify

| File | Action | Purpose |
|------|--------|---------|
| `interface/web/js/process.js` | **Create** | New JS module — state management, event handling, DOM rendering |
| `interface/web/index.html` | **Edit** | Add process panel sidebar HTML + load `process.js` |
| `interface/web/css/style.css` | **Edit** | Add process panel styles (dark/light themes) |
| `interface/web_server.py` | **Edit** | Forward 2-3 additional engine events not currently sent to WS |

No new backend dependencies. No changes to the engine or event system.

---

## Step 1: Extend WebSocket Event Bridge (Python)

Currently, `_engine_event_to_ws()` in `web_server.py` skips a few events that the process panel needs. Add forwarding for:

- **`PROMPT_ASSEMBLED`** → `{"type": "prompt_assembled"}` — signals prompt has been built
- **`MEMORIES_INJECTED`** → `{"type": "memories_injected"}` — signals memory recall complete

These already exist as `EngineEventType` values and are already emitted by the engine — they're just filtered out in the WebSocket bridge today.

### Events already available (no backend changes needed)

| WebSocket message | Process panel use |
|---|---|
| `processing_started` | Start new message group (with source: user/pulse/reminder/telegram/retry) |
| `stream_start` | "Thinking..." active node |
| `stream_chunk` | Live token count update on streaming node |
| `stream_complete` | Mark stream node as "Responded" with token stats |
| `tool_invoked` | Tool node (purple dot) with tool name + detail |
| `processing_complete` | Terminal "Settled" node, mark all active nodes complete |
| `processing_error` | Error node (red dot) |
| `pulse_fired` | Start new message group (origin: isaac) |
| `reminder_fired` | Start new message group (origin: isaac) |
| `telegram_received` | Start new message group (origin: user) |
| `retry_scheduled` | Retry node |

### Continuation rounds

The PyQt5 panel tracks continuation rounds (multi-round tool use). In the web, we can infer this: when a `stream_start` arrives *after* a `tool_invoked` within the same processing group, that's a new round. No new backend event needed — the JS module tracks round state locally.

---

## Step 2: HTML Structure

Add a `<aside>` element before `#chat-container` with a toggle button:

```
<aside id="process-panel" class="process-panel">
    <div class="process-panel-header">
        <span>Isaac</span>
        <button id="process-panel-toggle" title="Toggle process panel">◀</button>
    </div>
    <div id="process-panel-content" class="process-panel-content">
        <!-- Nodes rendered here by process.js -->
    </div>
</aside>
```

The main layout becomes: `[process-panel] [chat-container]` using CSS flexbox on the body (or a wrapper).

A small toggle button in the header (or on the panel edge) collapses/expands the panel. State persisted in `localStorage`.

---

## Step 3: JavaScript Module — `process.js`

Follows the existing IIFE pattern (`const Process = (() => { ... })()`). Key internals:

### State
- `messageGroups[]` — array of message processing groups
- `currentGroup` — active message group being built
- `currentRound` — current round number within the group
- `streamingNode` — reference to the active streaming node (for live updates)
- `tokenCount` — running token count for the streaming node

### Event → Node Mapping

| WS Event | Panel Behavior |
|----------|----------------|
| `processing_started` | Start new message group. Origin from `source` field (user→blue, pulse/reminder→purple, system→green) |
| `prompt_assembled` | Add "Gathering thoughts" node |
| `memories_injected` | Add "Recalling past conversations" node |
| `stream_start` | If round > 1: start new round group + "Thinking further..." node. Else: start round 1 + "Thinking..." active node |
| `stream_chunk` | Increment token counter on streaming node detail |
| `stream_complete` | Mark streaming node as "Responded" with token info |
| `tool_invoked` | Add tool node inside current round (purple dot, shows tool name) |
| `processing_complete` | Add "Settled" terminal node, mark all active as complete |
| `processing_error` | Add error node (red dot), mark all active as complete |
| `pulse_fired` | Start new message group (origin: isaac), "Checking in" node |
| `reminder_fired` | Start new message group (origin: isaac), "Remembered something" node |
| `telegram_received` | Start new message group (origin: user), "Telegram received" node |
| `retry_scheduled` | Add "Retry scheduled" node |

### DOM Rendering

Each node is a small DOM element:
```
<div class="process-node">
    <span class="process-dot" style="color: {dotColor}">●</span>
    <span class="process-label">{label}</span>
    <span class="process-time">{HH:MM:SS}</span>
    <div class="process-detail">{detail text}</div>  <!-- optional -->
</div>
```

Round groups wrap nodes:
```
<div class="process-round">
    <div class="process-round-header">Round 2</div>
    <!-- nodes -->
</div>
```

Message groups wrap rounds and have a colored left border:
```
<div class="process-message-group" data-origin="user|isaac|system">
    <!-- round groups and standalone nodes -->
</div>
```

Separators between message groups: a thin `<hr>`.

### Auto-scroll
Mirror the existing chat auto-scroll pattern: track whether user has scrolled up from bottom; if at bottom, auto-scroll on new content.

### Registration
Register handlers via `Connection.on(type, handler)` for each relevant event type.

---

## Step 4: CSS Styling

### Panel layout
- Fixed width: `240px` (matches PyQt5)
- Full height between header and status bar
- Scrollable content area
- Collapsible with smooth transition (`width: 0` + `overflow: hidden`)

### Color scheme (using CSS variables for theme support)
Add new CSS variables for the process panel:

```css
/* Dark theme */
--process-bg: #1e1e2e;
--process-border: #334;
--process-dot-active: #d4a574;      /* amber */
--process-dot-complete: #7a7770;    /* muted */
--process-dot-tool: #c4a7e7;        /* purple */
--process-dot-error: #e07a6b;       /* red */
--process-dot-system: #5bb98c;      /* green */
--process-dot-delegation: #6bb5e0;  /* blue */
--process-round-bg: #252540;
--process-round-border: #3a3a50;
--process-border-user: #6bb5e0;     /* blue left bar */
--process-border-isaac: #c4a7e7;    /* purple left bar */
--process-border-system: #5bb98c;   /* green left bar */
```

Light theme counterparts as well.

### Typography
- Node labels: 0.82rem, primary text color
- Timestamps: 0.7rem, dim text
- Details: 0.75rem, secondary text
- Round headers: 0.7rem, dim text

### Mobile
- Panel hidden by default on screens < 768px
- Toggle button still accessible in header area

---

## Step 5: Integration & Polish

- **Load order**: `process.js` loaded after `connection.js` but before `app.js` in `index.html`
- **Panel toggle state**: Persist in `localStorage` under `pattern-process-panel`
- **Panel toggle**: Small button in the header-left area (next to "Pattern" title) or on the panel edge
- **Animations**: Fade-in on new nodes (matches existing `fadeIn` keyframe), smooth collapse/expand

---

## What This Does NOT Include

- **Delegation events**: The engine doesn't currently emit delegation-specific events (DELEGATION_START/TOOL/COMPLETE) — those are PyQt-only via the separate ProcessEventBus. We can add these later when the delegation system evolves.
- **Curiosity events**: Same — these are PyQt ProcessEventBus events, not engine events. Future addition.
- **Memory extraction events**: Not currently an EngineEventType. Can be added later.

These can all be added incrementally by adding new EngineEventType values and forwarding them through the WS bridge.

---

## Summary

| Component | Effort | Risk |
|-----------|--------|------|
| WS bridge additions (2 events) | Small | Low — just forwarding existing events |
| HTML sidebar structure | Small | Low — additive |
| CSS styling + themes | Medium | Low — isolated, uses existing variable pattern |
| `process.js` module | Medium | Low — follows established patterns, read-only display |
| Layout adjustment (flex) | Small | Medium — need to verify no regressions on existing layout |

Total: ~4 files touched, 1 new file created. The process panel is entirely additive — no changes to existing functionality.
