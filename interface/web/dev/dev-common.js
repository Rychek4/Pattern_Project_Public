/**
 * Pattern Project - Dev Tools Shared JavaScript
 *
 * Provides WebSocket connection to /ws/dev with auto-reconnect,
 * event subscription, and shared utilities for all dev tool pages.
 */

const DevConnection = (() => {
    let ws = null;
    let reconnectTimer = null;
    let listeners = {};
    let statusDot = null;

    function _getWsUrl() {
        const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
        return `${proto}//${location.host}/ws/dev`;
    }

    function _setConnected(connected) {
        if (!statusDot) statusDot = document.querySelector('.status-dot');
        if (statusDot) {
            statusDot.classList.toggle('connected', connected);
        }
    }

    function connect() {
        if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
            return;
        }

        ws = new WebSocket(_getWsUrl());

        ws.onopen = () => {
            _setConnected(true);
            if (reconnectTimer) {
                clearTimeout(reconnectTimer);
                reconnectTimer = null;
            }
        };

        ws.onclose = () => {
            _setConnected(false);
            _scheduleReconnect();
        };

        ws.onerror = () => {
            _setConnected(false);
        };

        ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                const type = msg.type;
                if (type && listeners[type]) {
                    listeners[type].forEach(fn => {
                        try { fn(msg); } catch (e) { console.error('Listener error:', e); }
                    });
                }
            } catch (e) {
                console.error('Failed to parse dev WS message:', e);
            }
        };
    }

    function _scheduleReconnect() {
        if (reconnectTimer) return;
        reconnectTimer = setTimeout(() => {
            reconnectTimer = null;
            connect();
        }, 2000);
    }

    function on(type, callback) {
        if (!listeners[type]) listeners[type] = [];
        listeners[type].push(callback);
    }

    // Auto-connect on load
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', connect);
    } else {
        connect();
    }

    return { connect, on };
})();


// =========================================================================
// Shared utilities
// =========================================================================

const DevUtils = {
    /** Format a timestamp string for display. */
    formatTime(ts) {
        if (!ts || ts === '(initial load)') return ts || '';
        return ts;
    },

    /** Truncate text to maxLen characters. */
    truncate(text, maxLen = 200) {
        if (!text) return '';
        const s = String(text);
        return s.length > maxLen ? s.substring(0, maxLen) + '...' : s;
    },

    /** Create a badge element. */
    badge(text, className = 'badge-dim') {
        const el = document.createElement('span');
        el.className = `badge ${className}`;
        el.textContent = text;
        return el;
    },

    /** Create a collapsible section. Returns {toggle, body} elements. */
    collapsible(label, content) {
        const wrapper = document.createElement('div');

        const toggle = document.createElement('div');
        toggle.className = 'collapsible-toggle';
        toggle.textContent = `▶ ${label}`;

        const body = document.createElement('div');
        body.className = 'collapsible-body';
        if (typeof content === 'string') {
            const pre = document.createElement('pre');
            pre.className = 'content-block';
            pre.textContent = content;
            body.appendChild(pre);
        } else if (content instanceof HTMLElement) {
            body.appendChild(content);
        }

        toggle.addEventListener('click', () => {
            const open = body.classList.toggle('open');
            toggle.textContent = `${open ? '▼' : '▶'} ${label}`;
        });

        wrapper.appendChild(toggle);
        wrapper.appendChild(body);
        return wrapper;
    },

    /** Scroll an element to the bottom if user hasn't scrolled up. */
    autoScroll(el) {
        if (!el) return;
        const atBottom = el.scrollTop >= el.scrollHeight - el.clientHeight - 40;
        if (atBottom) {
            requestAnimationFrame(() => { el.scrollTop = el.scrollHeight; });
        }
    },

    /** Safely stringify a value for display. */
    stringify(val) {
        if (val === null || val === undefined) return '';
        if (typeof val === 'string') return val;
        try {
            return JSON.stringify(val, null, 2);
        } catch {
            return String(val);
        }
    },

    /** Escape HTML entities. */
    escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
};
