/**
 * DefenderPanel Web Component
 *
 * Dedicated panel for tracking defender actions with red styling.
 */

class DefenderPanel extends HTMLElement {
    constructor() {
        super();
        this.actions = [];
    }

    connectedCallback() {
        this.render();
    }

    render() {
        this.innerHTML = `
            <div style="display: flex; flex-direction: column; height: 100%; min-height: 0;">
                <div class="event-count-row">
                    <span class="count-badge count-badge-red" id="defender-count">0</span>
                    <span class="event-count-label">actions detected</span>
                </div>
                <div id="defender-actions-list" class="events-scroll" role="log" aria-live="polite">
                    <div class="empty-state">No defender actions detected yet.</div>
                </div>
            </div>
        `;
    }

    addAction(event) {
        this.actions.unshift(event);
        this.updateCount();
        this.renderActions();
    }

    renderActions() {
        const list = this.querySelector('#defender-actions-list');
        if (this.actions.length === 0) {
            list.innerHTML = '<div class="empty-state">No defender actions detected yet.</div>';
            return;
        }
        list.innerHTML = this.actions.map(a => this.renderEntry(a)).join('');
    }

    renderEntry(event) {
        const ts = this.formatTimestamp(event.timestamp);
        const action = event.action || 'Unknown action';
        const details = this.formatDetails(event.details);
        return `<div class="event-card event-card-red">
            <div class="event-card-time">${ts}</div>
            <div class="event-card-action event-card-action-red">${this.escapeHtml(action)}</div>
            ${details ? `<div class="event-card-details">${this.escapeHtml(details)}</div>` : ''}
        </div>`;
    }

    formatTimestamp(ts) {
        try { return new Date(ts).toISOString(); }
        catch { return ts || ''; }
    }

    formatDetails(details) {
        if (!details) return '';
        if (typeof details === 'string') return details;
        try { return JSON.stringify(details); }
        catch { return String(details); }
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    updateCount() {
        const badge = this.querySelector('#defender-count');
        if (badge) badge.textContent = this.actions.length;
    }

    clear() {
        this.actions = [];
        this.updateCount();
        this.renderActions();
    }

    loadActions(actions) {
        this.actions = actions || [];
        this.updateCount();
        this.renderActions();
    }
}

customElements.define('defender-panel', DefenderPanel);
export default DefenderPanel;
