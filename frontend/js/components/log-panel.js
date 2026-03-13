/**
 * LogPanel Web Component
 *
 * Real-time log display with filtering and search.
 */

class LogPanel extends HTMLElement {
    constructor() {
        super();
        this.logs = [];
        this.filteredLogs = [];
        this.autoScroll = true;
        this.searchTerm = '';
        this.activeFilters = new Set();
        this.maxLogEvents = 1000;
    }

    connectedCallback() {
        this.render();
        this.attachEventListeners();
    }

    render() {
        this.innerHTML = `
            <div style="display: flex; flex-direction: column; height: 100%; min-height: 0;">
                <div class="log-controls">
                    <div class="log-controls-row">
                        <span class="section-label" style="margin-bottom: 0;">Search:</span>
                        <input type="text" id="log-search" class="form-input" style="flex: 1; min-height: 1.75rem; padding: 0.25rem 0.5rem; font-size: 0.75rem;" placeholder="Search logs..." />
                    </div>
                    <div class="log-controls-row">
                        <span class="section-label" style="margin-bottom: 0;">Filter:</span>
                        <button class="filter-btn" data-filter="DEFENDER_ACTION">Defender</button>
                        <button class="filter-btn" data-filter="ATTACKER_RESPONSE">Attacker</button>
                        <button class="filter-btn" data-filter="INFO">Info</button>
                        <button class="filter-btn" data-filter="ERROR">Errors</button>
                        <button class="filter-btn" data-filter="HEALTH_CHECK">Health</button>
                        <button id="clear-filters-btn" class="btn btn-blue" style="padding: 0.25rem 0.5rem; min-height: auto; font-size: 0.65rem;">Clear</button>
                    </div>
                    <div class="checkbox-row">
                        <input type="checkbox" id="autoscroll-toggle" class="form-checkbox" checked />
                        <label for="autoscroll-toggle" class="checkbox-label" style="font-size: 0.75rem;">Auto-scroll</label>
                    </div>
                </div>

                <div id="log-container" class="log-container" role="log" aria-live="polite">
                    <div class="empty-state">No log events yet. Start the tool to see events.</div>
                </div>

                <div class="log-stats">
                    <span id="log-count">0 events</span>
                    <span id="filtered-count" style="display: none;"></span>
                </div>
            </div>
        `;
    }

    attachEventListeners() {
        const searchInput = this.querySelector('#log-search');
        const autoScrollToggle = this.querySelector('#autoscroll-toggle');
        const filterButtons = this.querySelectorAll('.filter-btn');
        const clearFiltersBtn = this.querySelector('#clear-filters-btn');
        const logContainer = this.querySelector('#log-container');

        let searchTimeout;
        searchInput.addEventListener('input', (e) => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                this.searchTerm = e.target.value.toLowerCase().trim();
                this.filterLogs();
            }, 300);
        });

        autoScrollToggle.addEventListener('change', (e) => {
            this.autoScroll = e.target.checked;
            if (this.autoScroll) this.scrollToBottom();
        });

        filterButtons.forEach(btn => {
            btn.addEventListener('click', () => {
                const filterType = btn.getAttribute('data-filter');
                if (this.activeFilters.has(filterType)) {
                    this.activeFilters.delete(filterType);
                    btn.classList.remove('active');
                } else {
                    this.activeFilters.add(filterType);
                    btn.classList.add('active');
                }
                this.filterLogs();
            });
        });

        clearFiltersBtn.addEventListener('click', () => {
            this.activeFilters.clear();
            this.searchTerm = '';
            searchInput.value = '';
            this.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            this.filterLogs();
        });

        logContainer.addEventListener('scroll', () => {
            if (!this.autoScroll) return;
            const isAtBottom = logContainer.scrollHeight - logContainer.scrollTop <= logContainer.clientHeight + 50;
            if (!isAtBottom) {
                this.autoScroll = false;
                autoScrollToggle.checked = false;
            }
        });
    }

    appendLog(event) {
        this.logs.push(event);
        if (this.logs.length > this.maxLogEvents) this.logs.shift();
        this.filterLogs();
        if (this.autoScroll) this.scrollToBottom();
        this.updateStats();
    }

    filterLogs() {
        let filtered = [...this.logs];
        if (this.activeFilters.size > 0) {
            filtered = filtered.filter(e => this.activeFilters.has(e.event_type));
        }
        if (this.searchTerm) {
            filtered = filtered.filter(e => this.getSearchableText(e).toLowerCase().includes(this.searchTerm));
        }
        this.filteredLogs = filtered;
        this.renderLogs();
        this.updateStats();
    }

    getSearchableText(event) {
        const parts = [event.event_type || '', event.action || '', event.timestamp || ''];
        if (event.details) {
            parts.push(typeof event.details === 'string' ? event.details : JSON.stringify(event.details));
        }
        if (event.raw_line) parts.push(event.raw_line);
        return parts.join(' ');
    }

    renderLogs() {
        const container = this.querySelector('#log-container');
        if (this.filteredLogs.length === 0) {
            container.innerHTML = this.logs.length === 0
                ? '<div class="empty-state">No log events yet. Start the tool to see events.</div>'
                : '<div class="empty-state">No events match the current filters.</div>';
            return;
        }
        container.innerHTML = this.filteredLogs.map(e => this.renderLogEntry(e)).join('');
    }

    renderLogEntry(event) {
        const timestamp = this.formatTimestamp(event.timestamp);
        const eventType = event.event_type || 'UNKNOWN';
        const action = event.action || '';
        const details = this.formatDetails(event.details);

        let typeClass = 'log-type-muted';
        if (eventType === 'DEFENDER_ACTION') typeClass = 'log-type-red';
        else if (eventType === 'ATTACKER_RESPONSE') typeClass = 'log-type-green';
        else if (eventType === 'ERROR') typeClass = 'log-type-red';
        else if (eventType === 'INFO') typeClass = 'log-type-cyan';
        else if (eventType === 'HEALTH_CHECK') typeClass = 'log-type-yellow';

        let logText = action;
        if (details) logText += logText ? ` - ${details}` : details;
        if (event.raw_line && !logText) logText = event.raw_line;

        const displayText = this.searchTerm
            ? this.highlightSearchMatches(logText)
            : this.escapeHtml(logText);

        const time = timestamp.split('T')[1]?.split('.')[0] || timestamp;

        return `<div class="log-entry">
            <span class="log-timestamp">${time}</span>
            <span class="log-type ${typeClass}">[${eventType}]</span>
            <span class="log-text">${displayText}</span>
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

    highlightSearchMatches(text) {
        if (!this.searchTerm || !text) return this.escapeHtml(text);
        const escaped = this.escapeHtml(text);
        const term = this.escapeHtml(this.searchTerm);
        const regex = new RegExp(`(${term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi');
        return escaped.replace(regex, '<mark class="search-match">$1</mark>');
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    scrollToBottom() {
        const c = this.querySelector('#log-container');
        if (c) c.scrollTop = c.scrollHeight;
    }

    updateStats() {
        const logCount = this.querySelector('#log-count');
        const filteredCount = this.querySelector('#filtered-count');
        logCount.textContent = `${this.logs.length} event${this.logs.length !== 1 ? 's' : ''}`;
        if (this.activeFilters.size > 0 || this.searchTerm) {
            filteredCount.textContent = `(showing ${this.filteredLogs.length})`;
            filteredCount.style.display = 'inline';
        } else {
            filteredCount.style.display = 'none';
        }
    }

    clearLogs() {
        this.logs = [];
        this.filteredLogs = [];
        this.renderLogs();
        this.updateStats();
    }

    loadLogs(logs) {
        this.logs = (logs || []).slice(-this.maxLogEvents);
        this.filterLogs();
        if (this.autoScroll) this.scrollToBottom();
    }
}

customElements.define('log-panel', LogPanel);
export default LogPanel;
