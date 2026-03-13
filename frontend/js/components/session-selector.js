/**
 * SessionSelector Web Component
 *
 * Session selection, metadata display, and export functionality.
 */

class SessionSelector extends HTMLElement {
    constructor() {
        super();
        this.sessions = [];
        this.activeSessionId = null;
        this.selectedSessionId = null;
    }

    connectedCallback() {
        this.render();
        this.attachEventListeners();
        this.loadSessions();
    }

    render() {
        this.innerHTML = `
            <div>
                <div class="form-group">
                    <label class="form-label" for="session-dropdown">Select Session</label>
                    <select id="session-dropdown" class="form-select" aria-label="Select session to view">
                        <option value="">No sessions available</option>
                    </select>
                </div>

                <div id="session-metadata" class="session-meta" style="display: none;">
                    <div class="session-meta-row">
                        <span class="session-meta-label">Session ID:</span>
                        <span id="meta-id" class="session-meta-value" style="font-size: 0.6rem;"></span>
                    </div>
                    <div class="session-meta-row">
                        <span class="session-meta-label">Created:</span>
                        <span id="meta-time" class="session-meta-value"></span>
                    </div>
                    <div class="session-meta-row">
                        <span class="session-meta-label">Status:</span>
                        <span id="meta-status" class="session-meta-value"></span>
                    </div>
                    <div class="session-meta-row">
                        <span class="session-meta-label">Events:</span>
                        <span id="meta-logs" class="session-meta-value"></span>
                    </div>
                </div>

                <div class="btn-row" style="margin-top: 0.75rem;">
                    <button id="export-btn" class="btn btn-blue" disabled>Export</button>
                    <button id="refresh-btn" class="btn btn-ghost">Refresh</button>
                </div>

                <div id="session-error" class="form-error" style="margin-top: 0.5rem; padding: 0.375rem; background: rgba(255,0,68,0.1); border: 1px solid var(--accent-red); border-radius: 0.25rem;"></div>
            </div>
        `;
    }

    attachEventListeners() {
        this.querySelector('#session-dropdown').addEventListener('change', (e) => {
            if (e.target.value) this.selectSession(e.target.value);
            else this.clearMetadata();
        });
        this.querySelector('#export-btn').addEventListener('click', () => {
            if (this.selectedSessionId) this.exportSession(this.selectedSessionId);
        });
        this.querySelector('#refresh-btn').addEventListener('click', () => this.loadSessions());
    }

    async loadSessions() {
        try {
            const res = await fetch('/api/sessions');
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Failed to load');
            this.sessions = data.sessions || [];
            this.updateDropdown();
            this.clearError();
        } catch (error) {
            this.showError(`Failed to load sessions: ${error.message}`);
        }
    }

    updateDropdown() {
        const dd = this.querySelector('#session-dropdown');
        dd.innerHTML = '';

        if (this.sessions.length === 0) {
            dd.innerHTML = '<option value="">No sessions available</option>';
            return;
        }

        dd.innerHTML = '<option value="">Select a session...</option>';
        const sorted = [...this.sessions].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

        sorted.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s.id;
            const ts = new Date(s.timestamp).toLocaleString();
            const active = s.id === this.activeSessionId ? ' [ACTIVE]' : '';
            const status = s.status ? ` (${s.status})` : '';
            opt.textContent = `${ts}${active}${status}`;
            dd.appendChild(opt);
        });

        if (this.selectedSessionId) dd.value = this.selectedSessionId;
    }

    async selectSession(sessionId) {
        try {
            const res = await fetch(`/api/sessions/${sessionId}`);
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || 'Failed to load session');

            this.selectedSessionId = sessionId;
            this.displayMetadata(data);
            this.querySelector('#export-btn').disabled = false;

            this.dispatchEvent(new CustomEvent('session-selected', {
                bubbles: true,
                detail: { sessionId, sessionData: data }
            }));
            this.clearError();
        } catch (error) {
            this.showError(`Failed to load session: ${error.message}`);
        }
    }

    displayMetadata(data) {
        this.querySelector('#session-metadata').style.display = 'block';
        this.querySelector('#meta-id').textContent = data.id;
        this.querySelector('#meta-time').textContent = new Date(data.timestamp).toLocaleString();
        this.querySelector('#meta-status').textContent = data.status || 'unknown';
        this.querySelector('#meta-logs').textContent = data.logs ? data.logs.length : 0;
    }

    clearMetadata() {
        this.querySelector('#session-metadata').style.display = 'none';
        this.selectedSessionId = null;
        this.querySelector('#export-btn').disabled = true;
    }

    async exportSession(sessionId) {
        try {
            const res = await fetch(`/api/sessions/${sessionId}`);
            const data = await res.json();
            if (!res.ok) throw new Error('Failed to load session');

            const json = JSON.stringify(data, null, 2);
            const blob = new Blob([json], { type: 'application/json' });
            const ts = new Date(data.timestamp).toISOString().replace(/[:.]/g, '-').split('Z')[0];
            const filename = `session-${sessionId}-${ts}.json`;

            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(url);
        } catch (error) {
            this.showError(`Export failed: ${error.message}`);
        }
    }

    updateActiveSession(sessionId) {
        this.activeSessionId = sessionId;
        this.updateDropdown();
    }

    updateSessionStatus(sessionId, status) {
        const session = this.sessions.find(s => s.id === sessionId);
        if (session) {
            session.status = status;
            this.updateDropdown();
            // Update metadata display if this session is selected
            if (this.selectedSessionId === sessionId) {
                const metaStatus = this.querySelector('#meta-status');
                if (metaStatus) metaStatus.textContent = status;
            }
        }
    }

    showError(msg) {
        const el = this.querySelector('#session-error');
        if (el) { el.textContent = msg; el.classList.add('visible'); }
    }

    clearError() {
        const el = this.querySelector('#session-error');
        if (el) { el.textContent = ''; el.classList.remove('visible'); }
    }
}

customElements.define('session-selector', SessionSelector);
export default SessionSelector;
