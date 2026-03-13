/**
 * StatusPanel Web Component
 *
 * Real-time status display for tool and AWS access status.
 */

class StatusPanel extends HTMLElement {
    constructor() {
        super();
        this.toolStatus = 'stopped';
        this.accessStatus = 'unknown';
        this.bucketList = [];
        this.sessionId = null;
    }

    connectedCallback() {
        this.render();
    }

    render() {
        this.innerHTML = `
            <div>
                <div class="section-label">Tool Status</div>
                <div id="tool-status" class="status-row" role="status" aria-live="polite">
                    <span class="status-dot status-dot-gray"></span>
                    <span class="status-label status-label-gray">Stopped</span>
                </div>
                <div id="error-details" class="form-error" style="margin-top: 0.375rem; padding: 0.375rem; background: rgba(255,0,68,0.1); border: 1px solid var(--accent-red); border-radius: 0.25rem;"></div>

                <div class="section-label" style="margin-top: 0.75rem;">AWS Access Status</div>
                <div id="access-status" class="status-row" role="status" aria-live="polite">
                    <span class="status-dot status-dot-gray"></span>
                    <span class="status-label status-label-gray">Unknown</span>
                </div>

                <div id="bucket-list-container" style="display: none; margin-top: 0.5rem;">
                    <div class="section-label">S3 Buckets</div>
                    <ul id="bucket-list" style="list-style: none; padding: 0.375rem; background: var(--bg-input); border: 1px solid var(--border-default); border-radius: 0.25rem; max-height: 120px; overflow-y: auto;"></ul>
                </div>

                <div class="section-label" style="margin-top: 0.75rem;">Current Session</div>
                <div id="session-display" class="status-row" style="font-size: 0.7rem; font-family: 'Courier New', monospace; word-break: break-all;">
                    <span id="session-text" style="color: var(--text-muted);">No active session</span>
                </div>
            </div>
        `;
    }

    updateToolStatus(status, errorMessage = null) {
        this.toolStatus = status;
        const container = this.querySelector('#tool-status');
        const dot = container.querySelector('.status-dot');
        const label = container.querySelector('.status-label');
        const errorDiv = this.querySelector('#error-details');

        dot.className = 'status-dot';
        label.className = 'status-label';

        switch (status) {
            case 'stopped':
                dot.classList.add('status-dot-gray');
                label.classList.add('status-label-gray');
                label.textContent = 'Stopped';
                errorDiv.classList.remove('visible');
                break;
            case 'running':
                dot.classList.add('status-dot-green');
                label.classList.add('status-label-green');
                label.textContent = 'Running';
                errorDiv.classList.remove('visible');
                break;
            case 'error':
                dot.classList.add('status-dot-red');
                label.classList.add('status-label-red');
                label.textContent = 'Error';
                if (errorMessage) {
                    errorDiv.textContent = errorMessage;
                    errorDiv.classList.add('visible');
                }
                break;
        }

        this.dispatchEvent(new CustomEvent('status-changed', {
            bubbles: true,
            detail: { status, errorMessage }
        }));
    }

    updateAccessStatus(accessStatus, bucketList = []) {
        this.accessStatus = accessStatus;
        this.bucketList = bucketList;
        const container = this.querySelector('#access-status');
        const dot = container.querySelector('.status-dot');
        const label = container.querySelector('.status-label');
        const bucketContainer = this.querySelector('#bucket-list-container');

        dot.className = 'status-dot';
        label.className = 'status-label';

        switch (accessStatus) {
            case 'has_access':
                dot.classList.add('status-dot-green');
                label.classList.add('status-label-green');
                label.textContent = 'Still Has Access';
                if (bucketList.length > 0) {
                    bucketContainer.style.display = 'block';
                    this.renderBucketList(bucketList);
                } else {
                    bucketContainer.style.display = 'none';
                }
                break;
            case 'access_denied':
                dot.classList.add('status-dot-red');
                label.classList.add('status-label-red');
                label.textContent = 'Access Blocked';
                bucketContainer.style.display = 'none';
                break;
            default:
                dot.classList.add('status-dot-gray');
                label.classList.add('status-label-gray');
                label.textContent = 'Unknown';
                bucketContainer.style.display = 'none';
        }
    }

    renderBucketList(buckets) {
        const list = this.querySelector('#bucket-list');
        list.innerHTML = buckets.map(b =>
            `<li style="padding: 0.2rem 0.375rem; border-left: 2px solid var(--accent-green); margin-bottom: 0.125rem; font-size: 0.65rem; color: var(--accent-green); font-family: 'Courier New', monospace;">${this.escapeHtml(b)}</li>`
        ).join('');
    }

    updateSessionId(sessionId) {
        this.sessionId = sessionId;
        const text = this.querySelector('#session-text');
        const display = this.querySelector('#session-display');
        if (sessionId) {
            text.textContent = sessionId;
            text.style.color = 'var(--accent-cyan)';
            display.style.borderColor = 'rgba(0, 217, 255, 0.3)';
        } else {
            text.textContent = 'No active session';
            text.style.color = 'var(--text-muted)';
            display.style.borderColor = 'var(--border-default)';
        }
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    reset() {
        this.updateToolStatus('stopped');
        this.updateAccessStatus('unknown', []);
        this.updateSessionId(null);
    }
}

customElements.define('status-panel', StatusPanel);
export default StatusPanel;
