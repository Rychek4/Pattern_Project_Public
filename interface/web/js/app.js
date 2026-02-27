/**
 * Pattern Project - Main Application
 *
 * Wires WebSocket events to Chat display, manages UI state,
 * handles user input, settings, and theme switching.
 */

document.addEventListener('DOMContentLoaded', () => {
    // =====================================================================
    // DOM references
    // =====================================================================
    const chatInput = document.getElementById('chat-input');
    const sendBtn = document.getElementById('send-btn');
    const cancelBtn = document.getElementById('cancel-btn');
    const statusText = document.getElementById('status-text');
    const statusBar = document.getElementById('status-bar');
    const sessionTimer = document.getElementById('session-timer');
    const modelSelect = document.getElementById('model-select');
    const thinkingToggle = document.getElementById('thinking-toggle');
    const reflectiveInterval = document.getElementById('reflective-interval');
    const actionInterval = document.getElementById('action-interval');
    const pulseTypeSelect = document.getElementById('pulse-type-select');
    const pulseNowBtn = document.getElementById('pulse-now-btn');
    const pulseCountdown = document.getElementById('pulse-countdown');
    const themeToggle = document.getElementById('theme-toggle');
    const logoutBtn = document.getElementById('logout-btn');
    const imagePreview = document.getElementById('image-preview');
    const imagePreviewText = document.getElementById('image-preview-text');
    const imagePreviewClear = document.getElementById('image-preview-clear');

    // =====================================================================
    // State
    // =====================================================================
    let isProcessing = false;
    let sessionStart = Date.now();
    let pendingImage = null;   // base64 string (no prefix)
    let pulseState = { reflective: 0, action: 0, paused: false };
    let pulseCountdownTimer = null;
    let sessionTimerInterval = null;

    // =====================================================================
    // Theme
    // =====================================================================
    function initTheme() {
        const saved = localStorage.getItem('pattern-theme') || 'dark';
        document.documentElement.setAttribute('data-theme', saved);
        updateThemeIcon(saved);
        updateHljsTheme(saved);
    }

    function toggleTheme() {
        const current = document.documentElement.getAttribute('data-theme');
        const next = current === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem('pattern-theme', next);
        updateThemeIcon(next);
        updateHljsTheme(next);
    }

    function updateThemeIcon(theme) {
        themeToggle.textContent = theme === 'dark' ? '\u263E' : '\u2600';
    }

    function updateHljsTheme(theme) {
        const link = document.getElementById('hljs-theme');
        if (link) {
            link.href = theme === 'dark'
                ? 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css'
                : 'https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css';
        }
    }

    initTheme();

    // =====================================================================
    // Session timer
    // =====================================================================
    function updateSessionTimer() {
        const elapsed = Math.floor((Date.now() - sessionStart) / 1000);
        const h = Math.floor(elapsed / 3600);
        const m = Math.floor((elapsed % 3600) / 60);
        const s = elapsed % 60;
        if (h > 0) {
            sessionTimer.textContent = `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
        } else {
            sessionTimer.textContent = `${m}:${String(s).padStart(2, '0')}`;
        }
    }

    sessionTimerInterval = setInterval(updateSessionTimer, 1000);
    updateSessionTimer();

    // =====================================================================
    // Pulse countdown
    // =====================================================================
    function updatePulseCountdown() {
        if (!pulseState.reflective && !pulseState.action) {
            pulseCountdown.textContent = '';
            return;
        }

        // Decrement each second locally (server sends periodic updates)
        if (pulseState.reflective > 0) pulseState.reflective--;
        if (pulseState.action > 0) pulseState.action--;

        const fmtTime = (secs) => {
            if (secs <= 0) return '0:00';
            const m = Math.floor(secs / 60);
            const s = secs % 60;
            if (m >= 60) {
                const h = Math.floor(m / 60);
                const rm = m % 60;
                return `${h}:${String(rm).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
            }
            return `${m}:${String(s).padStart(2, '0')}`;
        };

        let text = `R: ${fmtTime(pulseState.reflective)} | A: ${fmtTime(pulseState.action)}`;
        if (pulseState.paused) text += ' (paused)';
        pulseCountdown.textContent = text;
    }

    pulseCountdownTimer = setInterval(updatePulseCountdown, 1000);

    // =====================================================================
    // Status helpers
    // =====================================================================
    function setStatus(text, type) {
        statusText.textContent = text;
        statusBar.className = type || '';
    }

    function setProcessing(processing) {
        isProcessing = processing;
        chatInput.disabled = processing;
        sendBtn.disabled = processing;
        pulseNowBtn.disabled = processing;

        if (processing) {
            sendBtn.classList.add('hidden');
            cancelBtn.classList.remove('hidden');
            setStatus('Isaac is thinking...', 'thinking');
        } else {
            cancelBtn.classList.add('hidden');
            sendBtn.classList.remove('hidden');
            setStatus('Ready', '');
            chatInput.focus();
        }
    }

    // =====================================================================
    // Input handling
    // =====================================================================

    // Auto-resize textarea
    chatInput.addEventListener('input', () => {
        chatInput.style.height = 'auto';
        chatInput.style.height = Math.min(chatInput.scrollHeight, 150) + 'px';
    });

    // Send on Enter (Shift+Enter for newline)
    chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    sendBtn.addEventListener('click', sendMessage);

    cancelBtn.addEventListener('click', () => {
        Connection.send({ type: 'cancel' });
    });

    function sendMessage() {
        const text = chatInput.value.trim();
        if (!text && !pendingImage) return;
        if (isProcessing) return;

        const msg = { type: 'chat', text: text };
        if (pendingImage) {
            msg.image = pendingImage;
        }

        Connection.send(msg);
        chatInput.value = '';
        chatInput.style.height = 'auto';
        clearPendingImage();
    }

    // =====================================================================
    // Image paste handling
    // =====================================================================
    chatInput.addEventListener('paste', (e) => {
        const items = e.clipboardData && e.clipboardData.items;
        if (!items) return;

        for (const item of items) {
            if (item.type.startsWith('image/')) {
                e.preventDefault();
                const file = item.getAsFile();
                if (file) readImageFile(file);
                return;
            }
        }
    });

    // Also support drag & drop
    chatInput.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'copy';
    });

    chatInput.addEventListener('drop', (e) => {
        const files = e.dataTransfer && e.dataTransfer.files;
        if (!files) return;

        for (const file of files) {
            if (file.type.startsWith('image/')) {
                e.preventDefault();
                readImageFile(file);
                return;
            }
        }
    });

    function readImageFile(file) {
        const reader = new FileReader();
        reader.onload = () => {
            // Strip the data:image/...;base64, prefix
            const base64 = reader.result.split(',')[1];
            pendingImage = base64;
            imagePreviewText.textContent = `Image attached (${(file.size / 1024).toFixed(0)} KB)`;
            imagePreview.classList.remove('hidden');
        };
        reader.readAsDataURL(file);
    }

    function clearPendingImage() {
        pendingImage = null;
        imagePreview.classList.add('hidden');
        imagePreviewText.textContent = '';
    }

    imagePreviewClear.addEventListener('click', clearPendingImage);

    // =====================================================================
    // Settings controls
    // =====================================================================
    modelSelect.addEventListener('change', () => {
        Connection.send({ type: 'set_model', model: modelSelect.value });
    });

    thinkingToggle.addEventListener('change', () => {
        Connection.send({ type: 'set_thinking', enabled: thinkingToggle.checked });
    });

    reflectiveInterval.addEventListener('change', () => {
        Connection.send({
            type: 'set_pulse_interval',
            pulse_type: 'reflective',
            interval_seconds: parseInt(reflectiveInterval.value),
        });
    });

    actionInterval.addEventListener('change', () => {
        Connection.send({
            type: 'set_pulse_interval',
            pulse_type: 'action',
            interval_seconds: parseInt(actionInterval.value),
        });
    });

    pulseNowBtn.addEventListener('click', () => {
        Connection.send({ type: 'pulse_now', pulse_type: pulseTypeSelect.value });
    });

    themeToggle.addEventListener('click', toggleTheme);

    logoutBtn.addEventListener('click', async () => {
        await fetch('/auth/logout', { method: 'POST' });
        Connection.close();
        window.location.href = '/auth/login';
    });

    // =====================================================================
    // WebSocket event handlers
    // =====================================================================

    // Connection lifecycle
    Connection.on('_connected', () => {
        setStatus('Connected', '');
        chatInput.disabled = false;
        sendBtn.disabled = false;
    });

    Connection.on('_disconnected', (msg) => {
        setStatus('Disconnected - reconnecting...', 'error');
        chatInput.disabled = true;
        sendBtn.disabled = true;
    });

    // State sync (sent on connect and on request)
    Connection.on('state', (msg) => {
        // Sync model
        if (msg.model) {
            modelSelect.value = msg.model;
            // If model not in dropdown, add it
            if (!modelSelect.querySelector(`option[value="${msg.model}"]`)) {
                const opt = document.createElement('option');
                opt.value = msg.model;
                opt.textContent = msg.model;
                modelSelect.appendChild(opt);
                modelSelect.value = msg.model;
            }
        }

        // Sync thinking toggle
        if (typeof msg.thinking_enabled === 'boolean') {
            thinkingToggle.checked = msg.thinking_enabled;
        }

        // Sync pulse intervals
        if (msg.pulse_intervals) {
            const rVal = String(Math.round(msg.pulse_intervals.reflective));
            const aVal = String(Math.round(msg.pulse_intervals.action));
            if (reflectiveInterval.querySelector(`option[value="${rVal}"]`)) {
                reflectiveInterval.value = rVal;
            }
            if (actionInterval.querySelector(`option[value="${aVal}"]`)) {
                actionInterval.value = aVal;
            }
        }

        // Sync pulse countdown
        if (msg.pulse_remaining) {
            pulseState.reflective = Math.round(msg.pulse_remaining.reflective || 0);
            pulseState.action = Math.round(msg.pulse_remaining.action || 0);
        }
        if (typeof msg.pulse_paused === 'boolean') {
            pulseState.paused = msg.pulse_paused;
        }

        // Sync processing state
        if (msg.is_processing) {
            setProcessing(true);
        }
    });

    // User message echo (show immediately)
    Connection.on('user_message', (msg) => {
        Chat.addMessage('user', msg.text, msg.timestamp);
        setProcessing(true);
    });

    // Streaming
    Connection.on('processing_started', (msg) => {
        setProcessing(true);
        if (msg.source === 'pulse') {
            pulseState.paused = true;
        }
    });

    Connection.on('stream_start', (msg) => {
        Chat.streamStart(msg.timestamp);
    });

    Connection.on('stream_chunk', (msg) => {
        Chat.streamChunk(msg.text);
    });

    Connection.on('stream_complete', (msg) => {
        // stream_complete fires after the initial LLM stream, but tool
        // continuation rounds may produce additional chunks.  The GUI
        // only finalizes the display on response_complete, so we do the
        // same here -- just store token info for now.
    });

    // Response complete - authoritative final text.
    // For user messages this finalizes the streaming bubble.
    // For pulse/reminder/telegram this adds a new message.
    Connection.on('response_complete', (msg) => {
        const source = msg.source || 'user';
        const text = msg.text || '';

        if (source === 'user') {
            Chat.streamComplete(text);
        } else if (source === 'pulse' || source === 'reminder') {
            Chat.addMessage('assistant', text);
        } else if (source === 'telegram') {
            Chat.addMessage('assistant', text);
        } else if (source === 'retry') {
            Chat.addMessage('assistant', text);
        }
    });

    Connection.on('processing_complete', () => {
        setProcessing(false);
        pulseState.paused = false;
        // Refresh state to get updated pulse countdowns
        Connection.send({ type: 'get_state' });
    });

    Connection.on('processing_error', (msg) => {
        const errorType = msg.error_type;
        let errorText;
        if (errorType === 'both_models_unavailable') {
            errorText = '\u26a0 Both models are currently unavailable. Will retry automatically in 20 minutes.';
        } else {
            errorText = `\u26a0 An error occurred: ${msg.error}. Please try again.`;
        }
        // If a streaming bubble is open, finalize it with the error.
        // Otherwise, add a new error message.
        Chat.streamComplete(errorText);
        setStatus(`Error: ${msg.error}`, 'error');
        setProcessing(false);
    });

    // Tool invocations
    Connection.on('tool_invoked', (msg) => {
        Chat.addToolMessage(msg.tool_name, msg.detail);
    });

    // Clarification
    Connection.on('clarification', (msg) => {
        Chat.showClarification(msg.data, (option) => {
            // Send the selected option as a chat message
            Connection.send({ type: 'chat', text: option });
        });
    });

    // Pulse events
    Connection.on('pulse_fired', (msg) => {
        const label = (msg.pulse_type || 'action').charAt(0).toUpperCase() + (msg.pulse_type || 'action').slice(1);
        Chat.addSystemMessage(`[${label} Pulse]`);
    });

    Connection.on('reminder_fired', () => {
        Chat.addSystemMessage('[Reminder Pulse]');
    });

    Connection.on('pulse_interval_changed', (msg) => {
        // Update the dropdown to reflect AI-initiated changes
        if (msg.pulse_type === 'reflective') {
            const val = String(msg.interval_seconds);
            if (reflectiveInterval.querySelector(`option[value="${val}"]`)) {
                reflectiveInterval.value = val;
            }
        } else if (msg.pulse_type === 'action') {
            const val = String(msg.interval_seconds);
            if (actionInterval.querySelector(`option[value="${val}"]`)) {
                actionInterval.value = val;
            }
        }
    });

    // Status updates
    Connection.on('status_update', (msg) => {
        setStatus(msg.text, msg.status_type);
    });

    // Notifications
    Connection.on('notification', (msg) => {
        // Show as a system message
        Chat.addSystemMessage(msg.message);
    });

    // Telegram
    Connection.on('telegram_received', (msg) => {
        const from = msg.from_user ? ` from ${msg.from_user}` : '';
        Chat.addMessage('user', `Telegram${from}: ${msg.text}`);
    });

    // Retry
    Connection.on('retry_scheduled', () => {
        Chat.addSystemMessage('[Retry scheduled - will try again in 20 minutes]');
    });

    Connection.on('retry_failed', () => {
        Chat.addSystemMessage('[Retry failed - models still unavailable]');
    });

    // =====================================================================
    // Boot
    // =====================================================================
    Connection.connect();
    chatInput.focus();
});
