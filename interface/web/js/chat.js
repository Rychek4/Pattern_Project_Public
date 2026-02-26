/**
 * Pattern Project - Chat Renderer
 *
 * Handles message display, markdown rendering, and streaming text updates.
 */

const Chat = (() => {
    const _container = () => document.getElementById('messages');
    const _chatContainer = () => document.getElementById('chat-container');

    // Streaming state
    let _streamingEl = null;       // The .message-body element being streamed into
    let _streamingText = '';        // Accumulated raw text for re-rendering
    let _renderTimer = null;       // Debounce timer for streaming re-renders
    let _autoScroll = true;        // Whether to auto-scroll on new content

    // Configure marked
    marked.setOptions({
        breaks: true,
        gfm: true,
        highlight: function(code, lang) {
            if (lang && hljs.getLanguage(lang)) {
                try { return hljs.highlight(code, { language: lang }).value; }
                catch (e) { /* fall through */ }
            }
            return hljs.highlightAuto(code).value;
        }
    });

    /**
     * Check if the user is scrolled near the bottom.
     */
    function _isNearBottom() {
        const el = _chatContainer();
        return el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    }

    /**
     * Scroll to the bottom of the chat.
     */
    function scrollToBottom() {
        const el = _chatContainer();
        el.scrollTop = el.scrollHeight;
    }

    /**
     * Render markdown text to HTML.
     */
    function renderMarkdown(text) {
        if (!text) return '';
        try {
            return marked.parse(text);
        } catch (e) {
            console.error('Markdown render error:', e);
            return _escapeHtml(text);
        }
    }

    function _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * Format a timestamp for display.
     */
    function _formatTime(isoString) {
        if (!isoString) return '';
        try {
            const d = new Date(isoString);
            return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        } catch (e) {
            return '';
        }
    }

    /**
     * Create a message DOM element.
     */
    function _createMessageEl(role, html, timestamp) {
        const msg = document.createElement('div');
        msg.className = `message ${role}`;

        const header = document.createElement('div');
        header.className = 'message-header';

        const sender = document.createElement('span');
        sender.className = 'message-sender';
        if (role === 'user') sender.textContent = 'You';
        else if (role === 'assistant') sender.textContent = 'Isaac';
        else if (role === 'system') sender.textContent = 'System';
        else if (role === 'tool') sender.textContent = 'Tool';
        else if (role === 'error') sender.textContent = 'Error';

        const ts = document.createElement('span');
        ts.className = 'message-timestamp';
        ts.textContent = _formatTime(timestamp) || _formatTime(new Date().toISOString());

        header.appendChild(sender);
        header.appendChild(ts);

        const body = document.createElement('div');
        body.className = 'message-body';
        body.innerHTML = html;

        msg.appendChild(header);
        msg.appendChild(body);

        return msg;
    }

    /**
     * Add a fully rendered message to the chat.
     */
    function addMessage(role, text, timestamp, isHtml) {
        const wasNearBottom = _isNearBottom();
        const html = isHtml ? text : renderMarkdown(text);
        const el = _createMessageEl(role, html, timestamp);
        _container().appendChild(el);
        if (wasNearBottom) scrollToBottom();
        return el;
    }

    /**
     * Add a system message (centered, styled differently).
     */
    function addSystemMessage(text, timestamp) {
        return addMessage('system', text, timestamp);
    }

    /**
     * Add a tool invocation indicator.
     */
    function addToolMessage(toolName, detail) {
        const text = detail ? `${toolName}: ${detail}` : toolName;
        return addMessage('tool', text);
    }

    /**
     * Begin streaming an assistant response.
     */
    function streamStart(timestamp) {
        _autoScroll = _isNearBottom();
        _streamingText = '';

        const el = _createMessageEl('assistant', '', timestamp);
        _container().appendChild(el);
        _streamingEl = el.querySelector('.message-body');

        if (_autoScroll) scrollToBottom();
    }

    /**
     * Append a text chunk to the streaming message.
     */
    function streamChunk(text) {
        if (!_streamingEl) return;

        _streamingText += text;

        // Debounced re-render: update at most every 80ms during streaming
        if (!_renderTimer) {
            _renderTimer = setTimeout(() => {
                _renderTimer = null;
                if (_streamingEl) {
                    _streamingEl.innerHTML = renderMarkdown(_streamingText);
                }
                if (_autoScroll) scrollToBottom();
            }, 80);
        }
    }

    /**
     * Finalize the streaming message with the complete text.
     */
    function streamComplete(fullText) {
        if (_renderTimer) {
            clearTimeout(_renderTimer);
            _renderTimer = null;
        }

        // Use the full text from the server (authoritative)
        const text = fullText || _streamingText;

        if (_streamingEl) {
            _streamingEl.innerHTML = renderMarkdown(text);
            // Apply syntax highlighting to code blocks
            _streamingEl.querySelectorAll('pre code').forEach(block => {
                hljs.highlightElement(block);
            });
        } else if (text) {
            // No streaming bubble was created (e.g., error before stream_start).
            // Fall back to adding as a regular message.
            addMessage('assistant', text);
        }

        _streamingEl = null;
        _streamingText = '';

        if (_autoScroll) scrollToBottom();
    }

    /**
     * Show a clarification request with clickable option buttons.
     * onSelect(option) is called when user clicks an option.
     */
    function showClarification(data, onSelect) {
        const question = data.question || 'Please choose an option:';
        const options = data.options || [];
        const context = data.context || '';

        let html = renderMarkdown(question);
        if (context) {
            html += `<p style="color:var(--text-secondary);font-size:0.85em">${_escapeHtml(context)}</p>`;
        }
        html += '<div class="clarification-options">';
        options.forEach((opt, i) => {
            html += `<button class="clarification-btn" data-option="${_escapeHtml(opt)}">${_escapeHtml(opt)}</button>`;
        });
        html += '</div>';

        const el = addMessage('assistant', html, null, true);

        // Attach click handlers
        el.querySelectorAll('.clarification-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const option = btn.getAttribute('data-option');
                // Disable all buttons after selection
                el.querySelectorAll('.clarification-btn').forEach(b => {
                    b.disabled = true;
                    b.style.opacity = '0.5';
                });
                btn.style.opacity = '1';
                btn.style.borderColor = 'var(--accent)';
                onSelect(option);
            });
        });
    }

    /**
     * Clear all messages.
     */
    function clear() {
        _container().innerHTML = '';
        _streamingEl = null;
        _streamingText = '';
    }

    // Track auto-scroll on user scroll
    document.addEventListener('DOMContentLoaded', () => {
        const cc = _chatContainer();
        if (cc) {
            cc.addEventListener('scroll', () => {
                _autoScroll = _isNearBottom();
            });
        }
    });

    return {
        addMessage,
        addSystemMessage,
        addToolMessage,
        streamStart,
        streamChunk,
        streamComplete,
        showClarification,
        scrollToBottom,
        clear,
        renderMarkdown,
    };
})();
