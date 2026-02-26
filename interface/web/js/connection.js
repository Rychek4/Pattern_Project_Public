/**
 * Pattern Project - WebSocket Connection Manager
 *
 * Handles connect/reconnect/auth and dispatches incoming messages
 * to registered handlers.
 */

const Connection = (() => {
    let _ws = null;
    let _handlers = {};
    let _reconnectTimer = null;
    let _reconnectDelay = 1000;
    let _maxReconnectDelay = 30000;
    let _connected = false;
    let _intentionalClose = false;

    /**
     * Register a handler for a specific message type.
     * handler(data) is called when a message of that type arrives.
     */
    function on(type, handler) {
        if (!_handlers[type]) _handlers[type] = [];
        _handlers[type].push(handler);
    }

    /**
     * Dispatch a message to registered handlers.
     */
    function _dispatch(msg) {
        const type = msg.type;
        if (_handlers[type]) {
            _handlers[type].forEach(h => {
                try { h(msg); } catch (e) { console.error(`Handler error for ${type}:`, e); }
            });
        }
        // Also dispatch to wildcard handlers
        if (_handlers['*']) {
            _handlers['*'].forEach(h => {
                try { h(msg); } catch (e) { console.error('Wildcard handler error:', e); }
            });
        }
    }

    /**
     * Connect to the WebSocket server.
     */
    function connect() {
        if (_ws && (_ws.readyState === WebSocket.CONNECTING || _ws.readyState === WebSocket.OPEN)) {
            return;
        }

        _intentionalClose = false;
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${protocol}//${window.location.host}/ws`;

        _ws = new WebSocket(url);

        _ws.onopen = () => {
            _connected = true;
            _reconnectDelay = 1000;
            _dispatch({ type: '_connected' });
        };

        _ws.onclose = (e) => {
            _connected = false;
            _dispatch({ type: '_disconnected', code: e.code, reason: e.reason });

            if (e.code === 4001) {
                // Auth failure -- redirect to login
                window.location.href = '/auth/login';
                return;
            }

            if (!_intentionalClose) {
                _scheduleReconnect();
            }
        };

        _ws.onerror = () => {
            // onerror is always followed by onclose, so reconnect happens there
        };

        _ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                _dispatch(msg);
            } catch (e) {
                console.error('Failed to parse WebSocket message:', e);
            }
        };
    }

    function _scheduleReconnect() {
        if (_reconnectTimer) clearTimeout(_reconnectTimer);
        _reconnectTimer = setTimeout(() => {
            _reconnectTimer = null;
            connect();
        }, _reconnectDelay);
        _reconnectDelay = Math.min(_reconnectDelay * 1.5, _maxReconnectDelay);
    }

    /**
     * Send a JSON message to the server.
     */
    function send(data) {
        if (!_ws || _ws.readyState !== WebSocket.OPEN) {
            console.warn('WebSocket not connected, cannot send:', data);
            return false;
        }
        _ws.send(JSON.stringify(data));
        return true;
    }

    /**
     * Close the connection intentionally (e.g., on logout).
     */
    function close() {
        _intentionalClose = true;
        if (_ws) _ws.close();
    }

    function isConnected() {
        return _connected;
    }

    return { on, connect, send, close, isConnected };
})();
