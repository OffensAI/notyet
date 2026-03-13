/**
 * AttackerPanel Web Component
 *
 * Dedicated panel for tracking attacker responses with green styling.
 */

class AttackerPanel extends HTMLElement {
    constructor() {
        super();
        this.responses = [];
    }

    connectedCallback() {
        this.render();
    }

    render() {
        this.innerHTML = `
            <div style="display: flex; flex-direction: column; height: 100%; min-height: 0;">
                <div class="event-count-row">
                    <span class="count-badge count-badge-green" id="attacker-count">0</span>
                    <span class="event-count-label">responses executed</span>
                </div>
                <div id="attacker-responses-list" class="events-scroll" role="log" aria-live="polite">
                    <div class="empty-state">No attacker responses yet.</div>
                </div>
            </div>
        `;
    }

    addResponse(event) {
        this.responses.unshift(event);
        this.updateCount();
        this.renderResponses();
    }

    renderResponses() {
        const list = this.querySelector('#attacker-responses-list');
        if (this.responses.length === 0) {
            list.innerHTML = '<div class="empty-state">No attacker responses yet.</div>';
            return;
        }
        list.innerHTML = this.responses.map(r => this.renderEntry(r)).join('');
    }

    renderEntry(event) {
        const ts = this.formatTimestamp(event.timestamp);
        const action = event.action || 'Unknown response';
        const details = this.formatDetails(event.details);
        return `<div class="event-card event-card-green">
            <div class="event-card-time">${ts}</div>
            <div class="event-card-action event-card-action-green">${this.escapeHtml(action)}</div>
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
        const badge = this.querySelector('#attacker-count');
        if (badge) badge.textContent = this.responses.length;
    }

    clear() {
        this.responses = [];
        this.updateCount();
        this.renderResponses();
    }

    loadResponses(responses) {
        this.responses = responses || [];
        this.updateCount();
        this.renderResponses();
    }
}

customElements.define('attacker-panel', AttackerPanel);
export default AttackerPanel;
