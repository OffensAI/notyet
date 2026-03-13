/**
 * NotyetApp - Main Application Controller
 * 
 * Orchestrates all UI components and manages WebSocket communication.
 * Initializes components, establishes WebSocket connection, routes messages, and manages global state.
 * 
 * Requirements: 3.2, 3.3, 7.3, 13.5, 15.1, 15.2, 15.3, 15.4
 */

import WebSocketClient from '/static/js/websocket-client.js';

class NotyetApp {
    constructor() {
        this.websocket = null;
        this.components = {};
        this.currentSessionId = null;
    }

    /**
     * Initialize the application
     */
    async init() {
        console.log('Initializing Notyet Web UI...');

        // Get references to all components
        this.components = {
            controlPanel: document.querySelector('control-panel'),
            statusPanel: document.querySelector('status-panel'),
            logPanel: document.querySelector('log-panel'),
            defenderPanel: document.querySelector('defender-panel'),
            attackerPanel: document.querySelector('attacker-panel'),
            sessionSelector: document.querySelector('session-selector')
        };

        // Verify all components are present
        for (const [name, component] of Object.entries(this.components)) {
            if (!component) {
                console.error(`Component not found: ${name}`);
            }
        }

        // Set up event listeners for component events
        this.setupComponentEventListeners();

        // Initialize WebSocket connection
        this.connectWebSocket();

        // Fetch current tool status immediately (don't wait for WebSocket)
        await this.fetchCurrentStatus();

        // Load initial session list
        await this.loadSessions();

        console.log('Notyet Web UI initialized');
    }

    /**
     * Set up event listeners for component events
     */
    setupComponentEventListeners() {
        // Control panel events
        if (this.components.controlPanel) {
            this.components.controlPanel.addEventListener('tool-started', (e) => {
                this.handleToolStarted(e.detail);
            });

            this.components.controlPanel.addEventListener('tool-stopped', (e) => {
                this.handleToolStopped(e.detail);
            });

            this.components.controlPanel.addEventListener('tool-restarted', (e) => {
                this.handleToolRestarted(e.detail);
            });

            this.components.controlPanel.addEventListener('tool-status-fetched', (e) => {
                this.updateToolBanner(e.detail.status);
            });
        }

        // Session selector events
        if (this.components.sessionSelector) {
            this.components.sessionSelector.addEventListener('session-selected', (e) => {
                this.handleSessionSelected(e.detail);
            });
        }
    }

    /**
     * Connect to WebSocket server
     */
    connectWebSocket() {
        this.websocket = new WebSocketClient();

        // Register message handlers
        this.websocket.on('log_event', (payload) => {
            this.handleLogEvent(payload);
        });

        this.websocket.on('status_update', (payload) => {
            this.handleStatusUpdate(payload);
        });

        this.websocket.on('access_status_update', (payload) => {
            this.handleAccessStatusUpdate(payload);
        });

        this.websocket.on('session_state', (payload) => {
            this.handleSessionState(payload);
        });

        this.websocket.on('error', (payload) => {
            this.handleError(payload);
        });

        // Register connection state handler
        this.websocket.onConnectionStateChange((state, data) => {
            this.handleConnectionStateChange(state, data);
        });

        // Connect
        this.websocket.connect();
    }

    /**
     * Handle log event from WebSocket
     * @param {Object} payload - Log event payload
     */
    handleLogEvent(payload) {
        // Add to log panel
        if (this.components.logPanel) {
            this.components.logPanel.appendLog(payload);
        }

        // Route to specialized panels based on event type
        if (payload.event_type === 'DEFENDER_ACTION' && this.components.defenderPanel) {
            this.components.defenderPanel.addAction(payload);
        } else if (payload.event_type === 'ATTACKER_RESPONSE' && this.components.attackerPanel) {
            this.components.attackerPanel.addResponse(payload);
        }

        // Update access status if it's a health check event
        if (payload.event_type === 'HEALTH_CHECK') {
            this.updateAccessStatusFromHealthCheck(payload);
        }
    }

    /**
     * Handle status update from WebSocket
     * @param {Object} payload - Status update payload
     */
    handleStatusUpdate(payload) {
        const { status, session_id, error_message } = payload;

        // Update status panel
        if (this.components.statusPanel) {
            this.components.statusPanel.updateToolStatus(status, error_message);
        }

        // Update control panel button states
        if (this.components.controlPanel) {
            this.components.controlPanel.updateToolStatus(status);
        }

        // Update tool banner
        this.updateToolBanner(status, error_message);

        // Update current session ID
        if (session_id) {
            this.currentSessionId = session_id;
            if (this.components.statusPanel) {
                this.components.statusPanel.updateSessionId(session_id);
            }
        }

        // Update session selector with live status
        if (this.components.sessionSelector && session_id) {
            this.components.sessionSelector.updateSessionStatus(session_id, status);
        }

        // Reload session list if tool stopped
        if (status === 'stopped') {
            this.loadSessions();
        }
    }

    /**
     * Handle access status update from WebSocket
     * @param {Object} payload - Access status update payload
     */
    handleAccessStatusUpdate(payload) {
        const { access_status, bucket_list } = payload;

        // Update status panel
        if (this.components.statusPanel) {
            this.components.statusPanel.updateAccessStatus(access_status, bucket_list);
        }
    }

    /**
     * Handle session state from WebSocket (for reconnection)
     * @param {Object} payload - Session state payload
     */
    handleSessionState(payload) {
        const { session } = payload;

        if (!session) return;

        // Load session data into components
        this.loadSessionData(session);
    }

    /**
     * Handle error from WebSocket
     * @param {Object} payload - Error payload
     */
    handleError(payload) {
        const { message, details } = payload;
        console.error('WebSocket error:', message, details);

        // Show error notification
        this.showNotification(`Error: ${message}`, 'error');
    }

    /**
     * Handle connection state change
     * @param {string} state - Connection state
     * @param {*} data - Additional data
     */
    handleConnectionStateChange(state, data) {
        const indicator = document.getElementById('connection-status');
        const dot = indicator?.querySelector('.connection-dot');
        const text = indicator?.querySelector('.connection-text');

        switch (state) {
            case 'connected':
                console.log('WebSocket connected');
                if (dot) { dot.className = 'connection-dot connected'; }
                if (text) { text.textContent = 'Connected'; }
                // Fetch live tool status after connection is established
                this.fetchCurrentStatus();
                break;

            case 'disconnected':
                console.log('WebSocket disconnected');
                if (dot) { dot.className = 'connection-dot disconnected'; }
                if (text) { text.textContent = 'Disconnected'; }
                this.showNotification('Connection lost. Reconnecting...', 'warning');
                break;

            case 'reconnecting':
                console.log(`Reconnecting (attempt ${data.attempt})...`);
                if (dot) { dot.className = 'connection-dot'; }
                if (text) { text.textContent = `Reconnecting (${data.attempt})...`; }
                break;

            case 'error':
                console.error('WebSocket connection error:', data);
                if (dot) { dot.className = 'connection-dot disconnected'; }
                if (text) { text.textContent = 'Error'; }
                break;

            case 'max_reconnect_attempts':
                console.error('Max reconnection attempts reached');
                if (dot) { dot.className = 'connection-dot disconnected'; }
                if (text) { text.textContent = 'Connection lost'; }
                this.showNotification('Connection lost. Please refresh the page.', 'error', true);
                break;
        }
    }

    /**
     * Handle tool started event
     * @param {Object} detail - Event detail
     */
    handleToolStarted(detail) {
        const { session_id, status } = detail;

        this.currentSessionId = session_id;

        // Update status panel and control panel
        if (this.components.statusPanel) {
            this.components.statusPanel.updateToolStatus(status);
            this.components.statusPanel.updateSessionId(session_id);
        }
        if (this.components.controlPanel) {
            this.components.controlPanel.updateToolStatus(status);
        }

        // Clear previous logs and actions
        if (this.components.logPanel) {
            this.components.logPanel.clearLogs();
        }
        if (this.components.defenderPanel) {
            this.components.defenderPanel.clear();
        }
        if (this.components.attackerPanel) {
            this.components.attackerPanel.clear();
        }

        // Reload sessions and mark the new one as active
        if (this.components.sessionSelector) {
            this.components.sessionSelector.updateActiveSession(session_id);
            this.components.sessionSelector.loadSessions();
        }

        this.updateToolBanner('running');
        this.showNotification('Tool started successfully', 'success');
    }

    /**
     * Handle tool stopped event
     * @param {Object} detail - Event detail
     */
    handleToolStopped(detail) {
        const { status } = detail;

        // Update status panel and control panel
        if (this.components.statusPanel) {
            this.components.statusPanel.updateToolStatus(status);
        }
        if (this.components.controlPanel) {
            this.components.controlPanel.updateToolStatus(status);
        }

        // Update session status to stopped and reload list
        if (this.components.sessionSelector) {
            if (this.currentSessionId) {
                this.components.sessionSelector.updateSessionStatus(this.currentSessionId, 'stopped');
            }
            this.components.sessionSelector.loadSessions();
        }

        this.updateToolBanner('stopped');
        this.showNotification('Tool stopped', 'info');
    }

    /**
     * Handle tool restarted event
     * @param {Object} detail - Event detail
     */
    handleToolRestarted(detail) {
        const { session_id, status } = detail;

        this.currentSessionId = session_id;

        // Update status panel and control panel
        if (this.components.statusPanel) {
            this.components.statusPanel.updateToolStatus(status);
            this.components.statusPanel.updateSessionId(session_id);
        }
        if (this.components.controlPanel) {
            this.components.controlPanel.updateToolStatus(status);
        }

        // Clear previous logs and actions
        if (this.components.logPanel) {
            this.components.logPanel.clearLogs();
        }
        if (this.components.defenderPanel) {
            this.components.defenderPanel.clear();
        }
        if (this.components.attackerPanel) {
            this.components.attackerPanel.clear();
        }

        // Reload sessions and mark the new one as active
        if (this.components.sessionSelector) {
            this.components.sessionSelector.updateActiveSession(session_id);
            this.components.sessionSelector.loadSessions();
        }

        this.updateToolBanner('running');
        this.showNotification('Tool restarted', 'success');
    }

    /**
     * Handle session selected event
     * @param {Object} detail - Event detail
     */
    async handleSessionSelected(detail) {
        const { sessionId: session_id } = detail;

        try {
            const response = await fetch(`/api/sessions/${session_id}`);
            const session = await response.json();

            if (!response.ok) {
                throw new Error('Failed to load session');
            }

            this.loadSessionData(session);
            this.showNotification('Session loaded', 'info');

        } catch (error) {
            console.error('Failed to load session:', error);
            this.showNotification('Failed to load session', 'error');
        }
    }

    /**
     * Load session data into components
     * @param {Object} session - Session object
     */
    loadSessionData(session) {
        // Load logs
        if (this.components.logPanel && session.logs) {
            this.components.logPanel.loadLogs(session.logs);
        }

        // Load defender actions
        if (this.components.defenderPanel && session.logs) {
            const defenderActions = session.logs.filter(log => log.event_type === 'DEFENDER_ACTION');
            this.components.defenderPanel.loadActions(defenderActions);
        }

        // Load attacker responses
        if (this.components.attackerPanel && session.logs) {
            const attackerResponses = session.logs.filter(log => log.event_type === 'ATTACKER_RESPONSE');
            this.components.attackerPanel.loadResponses(attackerResponses);
        }

        // Update status panel (access status and session ID only — tool status
        // comes from /api/health and WebSocket status_update, not stored session data)
        if (this.components.statusPanel) {
            this.components.statusPanel.updateAccessStatus(session.access_status, session.bucket_list);
            this.components.statusPanel.updateSessionId(session.id);
        }
    }

    /**
     * Load sessions list
     */
    async loadSessions() {
        if (this.components.sessionSelector) {
            await this.components.sessionSelector.loadSessions();
        }
    }

    /**
     * Update access status from health check event
     * @param {Object} event - Health check event
     */
    updateAccessStatusFromHealthCheck(event) {
        if (!event.details) return;

        let accessStatus = 'unknown';
        let bucketList = [];

        // Check if health check was successful
        if (event.details.status === 'success' && event.details.buckets) {
            accessStatus = 'has_access';
            bucketList = event.details.buckets;
        } else if (event.details.status === 'error' || event.details.error) {
            accessStatus = 'access_denied';
        }

        // Update status panel
        if (this.components.statusPanel) {
            this.components.statusPanel.updateAccessStatus(accessStatus, bucketList);
        }
    }

    /**
     * Fetch current tool status from the server on init/refresh.
     */
    async fetchCurrentStatus() {
        try {
            const res = await fetch('/api/health');
            if (!res.ok) return;
            const data = await res.json();
            const status = data.tool_status || 'stopped';
            this.updateToolBanner(status);
            if (this.components.statusPanel) {
                this.components.statusPanel.updateToolStatus(status);
            }
            if (this.components.controlPanel) {
                this.components.controlPanel.updateToolStatus(status);
            }
        } catch (e) {
            console.error('Failed to fetch current status:', e);
        }
    }

    /**
     * Update the tool status banner at the top of the dashboard.
     */
    updateToolBanner(status, errorMessage = null) {
        const banner = document.getElementById('tool-banner');
        if (!banner) return;

        const text = banner.querySelector('.tool-banner-text');
        banner.className = 'tool-banner';

        switch (status) {
            case 'running':
                banner.classList.add('tool-banner-running');
                if (text) text.textContent = 'Tool Running';
                break;
            case 'error':
                banner.classList.add('tool-banner-error');
                if (text) text.textContent = errorMessage ? `Error: ${errorMessage}` : 'Tool Error';
                break;
            default:
                banner.classList.add('tool-banner-stopped');
                if (text) text.textContent = 'Tool Stopped';
                break;
        }
    }

    /**
     * Show notification to user
     * @param {string} message - Notification message
     * @param {string} type - Notification type (success, error, warning, info)
     * @param {boolean} persistent - Whether notification should persist
     */
    showNotification(message, type = 'info', persistent = false) {
        // Create notification element
        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;
        notification.textContent = message;
        notification.setAttribute('role', 'alert');
        notification.setAttribute('aria-live', 'polite');

        // Add to page
        let container = document.querySelector('.notification-container');
        if (!container) {
            container = document.createElement('div');
            container.className = 'notification-container';
            document.body.appendChild(container);
        }
        container.appendChild(notification);

        // Animate in
        setTimeout(() => {
            notification.classList.add('notification-visible');
        }, 10);

        // Auto-remove after 5 seconds (unless persistent)
        if (!persistent) {
            setTimeout(() => {
                notification.classList.remove('notification-visible');
                setTimeout(() => {
                    notification.remove();
                }, 300);
            }, 5000);
        }
    }
}

// Initialize app when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        const app = new NotyetApp();
        app.init();
    });
} else {
    const app = new NotyetApp();
    app.init();
}

export default NotyetApp;
