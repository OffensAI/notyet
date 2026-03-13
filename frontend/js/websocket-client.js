/**
 * WebSocketClient
 * 
 * Manages WebSocket connection to the backend server.
 * Handles connection, reconnection with exponential backoff, and message routing.
 * 
 * Requirements: 13.4, 13.5, 15.1, 15.5
 */

class WebSocketClient {
    constructor() {
        this.websocket = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.baseDelay = 1000; // 1 second
        this.maxDelay = 30000; // 30 seconds
        this.isConnecting = false;
        this.shouldReconnect = true;
        this.messageHandlers = new Map();
        this.connectionStateHandlers = [];
    }

    /**
     * Connect to WebSocket server
     * @param {string} url - WebSocket URL (default: ws://localhost:8000/ws)
     */
    connect(url = null) {
        if (this.isConnecting || (this.websocket && this.websocket.readyState === WebSocket.OPEN)) {
            return;
        }

        this.isConnecting = true;

        // Determine WebSocket URL
        const wsUrl = url || this.getWebSocketUrl();

        try {
            this.websocket = new WebSocket(wsUrl);

            // Connection opened
            this.websocket.addEventListener('open', () => {
                console.log('WebSocket connected');
                this.isConnecting = false;
                this.reconnectAttempts = 0;
                this.notifyConnectionState('connected');
            });

            // Message received
            this.websocket.addEventListener('message', (event) => {
                this.handleMessage(event.data);
            });

            // Connection closed
            this.websocket.addEventListener('close', (event) => {
                console.log('WebSocket disconnected', event.code, event.reason);
                this.isConnecting = false;
                this.notifyConnectionState('disconnected');

                // Attempt reconnection if not intentionally closed
                if (this.shouldReconnect) {
                    this.reconnect();
                }
            });

            // Connection error
            this.websocket.addEventListener('error', (error) => {
                console.error('WebSocket error:', error);
                this.isConnecting = false;
                this.notifyConnectionState('error', error);
            });

        } catch (error) {
            console.error('Failed to create WebSocket:', error);
            this.isConnecting = false;
            this.notifyConnectionState('error', error);
            
            if (this.shouldReconnect) {
                this.reconnect();
            }
        }
    }

    /**
     * Disconnect from WebSocket server
     */
    disconnect() {
        this.shouldReconnect = false;
        
        if (this.websocket) {
            this.websocket.close();
            this.websocket = null;
        }
    }

    /**
     * Reconnect with exponential backoff
     */
    reconnect() {
        if (this.reconnectAttempts >= this.maxReconnectAttempts) {
            console.error('Max reconnection attempts reached');
            this.notifyConnectionState('max_reconnect_attempts');
            return;
        }

        // Calculate delay with exponential backoff
        const delay = Math.min(
            this.baseDelay * Math.pow(2, this.reconnectAttempts),
            this.maxDelay
        );

        console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts + 1}/${this.maxReconnectAttempts})`);
        this.notifyConnectionState('reconnecting', { attempt: this.reconnectAttempts + 1, delay });

        setTimeout(() => {
            this.reconnectAttempts++;
            this.connect();
        }, delay);
    }

    /**
     * Handle incoming WebSocket message
     * @param {string} data - Raw message data
     */
    handleMessage(data) {
        try {
            const message = JSON.parse(data);
            
            // Route message to registered handlers
            const messageType = message.type;
            if (this.messageHandlers.has(messageType)) {
                const handlers = this.messageHandlers.get(messageType);
                handlers.forEach(handler => {
                    try {
                        handler(message.payload, message);
                    } catch (error) {
                        console.error(`Error in message handler for ${messageType}:`, error);
                    }
                });
            }

            // Also call wildcard handlers
            if (this.messageHandlers.has('*')) {
                const handlers = this.messageHandlers.get('*');
                handlers.forEach(handler => {
                    try {
                        handler(message.payload, message);
                    } catch (error) {
                        console.error('Error in wildcard message handler:', error);
                    }
                });
            }

        } catch (error) {
            console.error('Failed to parse WebSocket message:', error, data);
        }
    }

    /**
     * Register a message handler for a specific message type
     * @param {string} messageType - Message type to handle (or '*' for all messages)
     * @param {Function} handler - Handler function (payload, fullMessage) => void
     */
    on(messageType, handler) {
        if (!this.messageHandlers.has(messageType)) {
            this.messageHandlers.set(messageType, []);
        }
        this.messageHandlers.get(messageType).push(handler);
    }

    /**
     * Unregister a message handler
     * @param {string} messageType - Message type
     * @param {Function} handler - Handler function to remove
     */
    off(messageType, handler) {
        if (this.messageHandlers.has(messageType)) {
            const handlers = this.messageHandlers.get(messageType);
            const index = handlers.indexOf(handler);
            if (index > -1) {
                handlers.splice(index, 1);
            }
        }
    }

    /**
     * Register a connection state change handler
     * @param {Function} handler - Handler function (state, data) => void
     */
    onConnectionStateChange(handler) {
        this.connectionStateHandlers.push(handler);
    }

    /**
     * Notify connection state change handlers
     * @param {string} state - Connection state (connected, disconnected, reconnecting, error, max_reconnect_attempts)
     * @param {*} data - Additional data
     */
    notifyConnectionState(state, data = null) {
        this.connectionStateHandlers.forEach(handler => {
            try {
                handler(state, data);
            } catch (error) {
                console.error('Error in connection state handler:', error);
            }
        });
    }

    /**
     * Send a message to the server
     * @param {Object} message - Message object to send
     */
    send(message) {
        if (this.websocket && this.websocket.readyState === WebSocket.OPEN) {
            try {
                this.websocket.send(JSON.stringify(message));
            } catch (error) {
                console.error('Failed to send WebSocket message:', error);
            }
        } else {
            console.warn('WebSocket is not connected. Cannot send message.');
        }
    }

    /**
     * Get WebSocket URL based on current page location
     * @returns {string} WebSocket URL
     */
    getWebSocketUrl() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const host = window.location.host;
        return `${protocol}//${host}/ws`;
    }

    /**
     * Check if WebSocket is connected
     * @returns {boolean} True if connected
     */
    isConnected() {
        return this.websocket && this.websocket.readyState === WebSocket.OPEN;
    }
}

export default WebSocketClient;
