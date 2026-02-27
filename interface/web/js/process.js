/**
 * Pattern Project - Process Panel
 *
 * Real-time sidebar showing the AI's internal processing pipeline.
 * Mirrors the PyQt5 ProcessPanel: message groups, round groups, and
 * individual step nodes with colored status dots.
 *
 * Subscribes to WebSocket events via Connection.on() and renders
 * DOM nodes into the #process-panel-content container.
 */

const Process = (() => {
    // =====================================================================
    // Constants
    // =====================================================================
    const COLORS = {
        active:     '#d4a574',  // amber  — something is happening
        complete:   '#7a7770',  // muted  — finished
        tool:       '#c4a7e7',  // purple — tool invocation
        error:      '#e07a6b',  // red    — error
        system:     '#5bb98c',  // green  — system events
        delegation: '#6bb5e0',  // blue   — delegation events
    };

    const DOT = '\u25CF';  // ●

    // =====================================================================
    // State
    // =====================================================================
    let currentGroup = null;    // current message group DOM element
    let currentRound = 0;       // current round number (0 = none)
    let currentRoundEl = null;  // current round group DOM element
    let streamingNode = null;   // reference to the active streaming node
    let activeNodes = [];       // nodes with amber dot (still in progress)
    let hasContent = false;     // whether any content exists yet
    let streamCompleted = false;// whether stream_complete fired in this group
    let charCount = 0;          // accumulated stream chars for token estimate
    let panelCollapsed = false; // toggle state

    // =====================================================================
    // DOM references
    // =====================================================================
    function _content()    { return document.getElementById('process-panel-content'); }
    function _panel()      { return document.getElementById('process-panel'); }
    function _toggle()     { return document.getElementById('process-panel-toggle'); }
    function _expandBtn()  { return document.getElementById('process-panel-expand'); }

    // =====================================================================
    // Time formatting
    // =====================================================================
    function _timeStr() {
        const d = new Date();
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    }

    // =====================================================================
    // Auto-scroll
    // =====================================================================
    let userScrolledUp = false;

    function _initScroll() {
        const el = _content();
        if (!el) return;
        el.addEventListener('scroll', () => {
            userScrolledUp = el.scrollTop < el.scrollHeight - el.clientHeight - 30;
        });
    }

    function _scrollToBottom() {
        if (userScrolledUp) return;
        const el = _content();
        if (el) el.scrollTop = el.scrollHeight;
    }

    // =====================================================================
    // DOM creation helpers
    // =====================================================================

    /**
     * Create a process node element.
     *   dotColor: hex color for the status dot
     *   label:    main label text
     *   detail:   optional secondary text
     *   isActive: if true, dot pulses amber
     */
    function _createNode(dotColor, label, detail) {
        const node = document.createElement('div');
        node.className = 'process-node';

        const dotSpan = document.createElement('span');
        dotSpan.className = 'process-dot';
        dotSpan.style.color = dotColor;
        dotSpan.textContent = DOT;

        const labelSpan = document.createElement('span');
        labelSpan.className = 'process-label';
        labelSpan.textContent = label;

        const timeSpan = document.createElement('span');
        timeSpan.className = 'process-time';
        timeSpan.textContent = _timeStr();

        node.appendChild(dotSpan);
        node.appendChild(labelSpan);
        node.appendChild(timeSpan);

        if (detail) {
            const detailDiv = document.createElement('div');
            detailDiv.className = 'process-detail';
            detailDiv.textContent = detail;
            node.appendChild(detailDiv);
        }

        return node;
    }

    /**
     * Create a round group container.
     */
    function _createRoundGroup(roundNum) {
        const group = document.createElement('div');
        group.className = 'process-round';

        const header = document.createElement('div');
        header.className = 'process-round-header';
        header.textContent = `Round ${roundNum}`;
        group.appendChild(header);

        return group;
    }

    /**
     * Create a message group container with origin-colored left border.
     */
    function _createMessageGroup(origin) {
        const group = document.createElement('div');
        group.className = 'process-message-group';
        group.setAttribute('data-origin', origin || 'user');
        return group;
    }

    /**
     * Create a separator between message groups.
     */
    function _createSeparator() {
        const sep = document.createElement('hr');
        sep.className = 'process-separator';
        return sep;
    }

    // =====================================================================
    // Node insertion
    // =====================================================================

    /**
     * Add a node to the current message group (standalone, outside rounds).
     */
    function _addNode(dotColor, label, detail) {
        const node = _createNode(dotColor, label, detail);
        if (currentGroup) {
            currentGroup.appendChild(node);
        } else {
            const c = _content();
            if (c) c.appendChild(node);
        }
        _scrollToBottom();
        return node;
    }

    /**
     * Add a node inside the current round group.
     * Falls back to message group if no round is active.
     */
    function _addNodeToRound(dotColor, label, detail) {
        const node = _createNode(dotColor, label, detail);
        if (currentRoundEl) {
            currentRoundEl.appendChild(node);
        } else if (currentGroup) {
            currentGroup.appendChild(node);
        } else {
            const c = _content();
            if (c) c.appendChild(node);
        }
        _scrollToBottom();
        return node;
    }

    /**
     * Start a new round group inside the current message group.
     */
    function _startRoundGroup(roundNum) {
        currentRoundEl = _createRoundGroup(roundNum);
        if (currentGroup) {
            currentGroup.appendChild(currentRoundEl);
        } else {
            const c = _content();
            if (c) c.appendChild(currentRoundEl);
        }
    }

    // =====================================================================
    // Active node management
    // =====================================================================

    function _markAllActiveComplete() {
        activeNodes.forEach(node => {
            const dot = node.querySelector('.process-dot');
            if (dot) dot.style.color = COLORS.complete;
            node.classList.remove('active');
        });
        activeNodes = [];
    }

    function _markNodeActive(node) {
        node.classList.add('active');
        const dot = node.querySelector('.process-dot');
        if (dot) dot.style.color = COLORS.active;
        activeNodes.push(node);
    }

    // =====================================================================
    // Update helpers (for streaming node)
    // =====================================================================

    function _updateNodeDetail(node, text) {
        if (!node) return;
        let detailEl = node.querySelector('.process-detail');
        if (detailEl) {
            detailEl.textContent = text;
        } else {
            detailEl = document.createElement('div');
            detailEl.className = 'process-detail';
            detailEl.textContent = text;
            node.appendChild(detailEl);
        }
    }

    function _updateNodeLabel(node, label) {
        if (!node) return;
        const labelEl = node.querySelector('.process-label');
        if (labelEl) labelEl.textContent = label;
    }

    function _updateNodeDot(node, color) {
        if (!node) return;
        const dot = node.querySelector('.process-dot');
        if (dot) dot.style.color = color;
    }

    // =====================================================================
    // Event handlers
    // =====================================================================

    /**
     * Start a new message group. Called on processing_started, pulse_fired,
     * reminder_fired, telegram_received.
     */
    function _startNewMessageGroup(origin) {
        // Add separator if there's existing content
        const c = _content();
        if (hasContent && c) {
            c.appendChild(_createSeparator());
        }

        // Reset round tracking
        currentRound = 0;
        currentRoundEl = null;
        streamingNode = null;
        streamCompleted = false;
        charCount = 0;
        _markAllActiveComplete();
        hasContent = true;

        // Create new message group
        currentGroup = _createMessageGroup(origin);
        if (c) c.appendChild(currentGroup);
    }

    /**
     * Determine message group origin from processing source.
     */
    function _originFromSource(source) {
        switch (source) {
            case 'pulse':
            case 'reminder':
                return 'isaac';
            case 'telegram':
            case 'user':
                return 'user';
            case 'retry':
                return 'system';
            default:
                return 'user';
        }
    }

    // --- processing_started ---
    function _onProcessingStarted(msg) {
        // Only create message groups for user and retry sources.
        // Pulse, reminder, and telegram have dedicated events
        // (pulse_fired, reminder_fired, telegram_received) that
        // create their own message groups — matching how the PyQt
        // GUI maps EngineEvents to ProcessEvents.
        if (msg.source === 'user') {
            _startNewMessageGroup('user');
            _addNode(COLORS.complete, 'You said something');
        } else if (msg.source === 'retry') {
            _startNewMessageGroup('system');
            _addNode(COLORS.system, 'Retrying');
        }
        // For pulse/reminder/telegram sources: do nothing here.
        // Their dedicated events will create the message group.
    }

    // --- prompt_assembled ---
    function _onPromptAssembled() {
        _addNode(COLORS.complete, 'Gathering thoughts');
    }

    // --- memories_injected ---
    function _onMemoriesInjected() {
        _addNode(COLORS.complete, 'Recalling past conversations');
    }

    // --- stream_start ---
    function _onStreamStart() {
        if (currentRound === 0) {
            // First round
            currentRound = 1;
            _startRoundGroup(1);
            const node = _addNodeToRound(COLORS.active, 'Thinking...');
            streamingNode = node;
            _markNodeActive(node);
        } else if (streamCompleted) {
            // Continuation — new round
            currentRound++;
            _startRoundGroup(currentRound);
            const node = _addNodeToRound(COLORS.active, 'Thinking further...');
            streamingNode = node;
            _markNodeActive(node);
        }
        streamCompleted = false;
        charCount = 0;
    }

    // --- stream_chunk ---
    function _onStreamChunk(msg) {
        if (!streamingNode) return;
        charCount += (msg.text || '').length;
        const approxTokens = Math.round(charCount / 4);
        _updateNodeDetail(streamingNode, `~${approxTokens} tokens`);
    }

    // --- stream_complete ---
    function _onStreamComplete(msg) {
        if (streamingNode) {
            _updateNodeLabel(streamingNode, 'Responded');
            _updateNodeDot(streamingNode, COLORS.complete);
            streamingNode.classList.remove('active');

            // Show token info if available
            const tokIn = msg.tokens_in || 0;
            const tokOut = msg.tokens_out || 0;
            if (tokIn || tokOut) {
                _updateNodeDetail(streamingNode, `${tokIn} in / ${tokOut} out`);
            }

            // Remove from active list
            const idx = activeNodes.indexOf(streamingNode);
            if (idx >= 0) activeNodes.splice(idx, 1);

            streamingNode = null;
        }
        streamCompleted = true;
    }

    // --- tool_invoked ---
    function _onToolInvoked(msg) {
        const toolName = msg.tool_name || 'unknown';
        const detail = msg.detail || '';
        _addNodeToRound(COLORS.tool, `Tool: ${toolName}`, detail);
    }

    // --- processing_complete ---
    function _onProcessingComplete() {
        currentRoundEl = null;

        let detail = '';
        if (currentRound > 1) {
            detail = `${currentRound} rounds`;
        }

        _markAllActiveComplete();
        _addNode(COLORS.system, 'Settled', detail);
    }

    // --- processing_error ---
    function _onProcessingError(msg) {
        _markAllActiveComplete();
        _addNode(COLORS.error, 'Something went wrong', msg.error || '');
    }

    // --- pulse_fired ---
    function _onPulseFired(msg) {
        _startNewMessageGroup('isaac');
        _addNode(COLORS.system, 'Checking in');
    }

    // --- reminder_fired ---
    function _onReminderFired() {
        _startNewMessageGroup('isaac');
        _addNode(COLORS.system, 'Remembered something he promised');
    }

    // --- telegram_received ---
    function _onTelegramReceived() {
        _startNewMessageGroup('user');
        _addNode(COLORS.complete, 'You sent a Telegram');
    }

    // --- retry_scheduled ---
    function _onRetryScheduled() {
        _addNode(COLORS.system, 'Retry scheduled');
    }

    // --- delegation_start ---
    function _onDelegationStart(msg) {
        _addNodeToRound(COLORS.delegation, 'Asking for help with a task', msg.detail || '');
    }

    // --- delegation_tool ---
    function _onDelegationTool(msg) {
        const detail = msg.detail || '';
        const toolName = detail.includes(':') ? detail.split(':')[0] : detail;
        const toolDetail = detail.includes(':') ? detail.split(':').slice(1).join(':').trim() : '';
        _addNodeToRound(COLORS.delegation, `Delegate: ${toolName}`, toolDetail);
    }

    // --- delegation_complete ---
    function _onDelegationComplete(msg) {
        _addNodeToRound(COLORS.delegation, 'Got the help he needed', msg.detail || '');
    }

    // --- curiosity_selected ---
    function _onCuriositySelected(msg) {
        _addNode(COLORS.system, 'Got curious about something', msg.detail || '');
    }

    // --- memory_extraction ---
    function _onMemoryExtraction(msg) {
        _addNode(COLORS.system, 'Reflecting on what to remember', msg.detail || '');
    }

    // =====================================================================
    // Panel toggle
    // =====================================================================

    function _initToggle() {
        const btn = _toggle();
        const expand = _expandBtn();

        // Restore saved state
        const saved = localStorage.getItem('pattern-process-panel');
        if (saved === 'collapsed') {
            _collapse();
        }

        if (btn) {
            btn.addEventListener('click', () => {
                if (panelCollapsed) {
                    _expand();
                } else {
                    _collapse();
                }
            });
        }

        if (expand) {
            expand.addEventListener('click', _expand);
        }
    }

    function _collapse() {
        const panel = _panel();
        const expand = _expandBtn();
        if (panel) panel.classList.add('collapsed');
        if (expand) expand.classList.remove('hidden');
        panelCollapsed = true;
        localStorage.setItem('pattern-process-panel', 'collapsed');
    }

    function _expand() {
        const panel = _panel();
        const expand = _expandBtn();
        if (panel) panel.classList.remove('collapsed');
        if (expand) expand.classList.add('hidden');
        panelCollapsed = false;
        localStorage.setItem('pattern-process-panel', 'expanded');
    }

    // =====================================================================
    // Registration
    // =====================================================================

    function init() {
        _initScroll();
        _initToggle();

        // Engine events (already forwarded by web_server)
        Connection.on('processing_started', _onProcessingStarted);
        Connection.on('prompt_assembled', _onPromptAssembled);
        Connection.on('memories_injected', _onMemoriesInjected);
        Connection.on('stream_start', _onStreamStart);
        Connection.on('stream_chunk', _onStreamChunk);
        Connection.on('stream_complete', _onStreamComplete);
        Connection.on('tool_invoked', _onToolInvoked);
        Connection.on('processing_complete', _onProcessingComplete);
        Connection.on('processing_error', _onProcessingError);
        Connection.on('pulse_fired', _onPulseFired);
        Connection.on('reminder_fired', _onReminderFired);
        Connection.on('telegram_received', _onTelegramReceived);
        Connection.on('retry_scheduled', _onRetryScheduled);

        // ProcessEventBus events (forwarded via callback bridge)
        Connection.on('delegation_start', _onDelegationStart);
        Connection.on('delegation_tool', _onDelegationTool);
        Connection.on('delegation_complete', _onDelegationComplete);
        Connection.on('curiosity_selected', _onCuriositySelected);
        Connection.on('memory_extraction', _onMemoryExtraction);
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    return { init };
})();
