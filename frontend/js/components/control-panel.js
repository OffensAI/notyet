/**
 * ControlPanel Web Component
 *
 * Configuration input and tool control interface.
 */

class ControlPanel extends HTMLElement {
    constructor() {
        super();
        this.toolStatus = 'stopped';
    }

    connectedCallback() {
        this.render();
        this.restoreConfig();
        this.attachEventListeners();
        // Fetch live tool status to set button states correctly on page load
        this.fetchToolStatus();
    }

    async fetchToolStatus() {
        try {
            const res = await fetch('/api/health');
            if (!res.ok) return;
            const data = await res.json();
            const status = data.tool_status || 'stopped';
            this.updateToolStatus(status);
            // Restore config from server if available, otherwise from localStorage
            if (data.current_config) {
                this.setConfig(data.current_config);
                this.saveConfig();
            }
            this.dispatchEvent(new CustomEvent('tool-status-fetched', {
                bubbles: true,
                detail: { status }
            }));
        } catch (e) {
            // Server not reachable, keep default stopped state
        }
    }

    render() {
        this.innerHTML = `
            <form id="config-form">
                <div class="form-group">
                    <label class="form-label" for="aws-profile">AWS Profile <span class="required">*</span></label>
                    <input type="text" id="aws-profile" name="aws_profile" class="form-input" placeholder="Enter AWS profile name" required />
                    <div id="aws-profile-error" class="form-error"></div>
                </div>

                <div class="form-group">
                    <label class="form-label" for="output-profile">Output Profile <span class="required">*</span></label>
                    <input type="text" id="output-profile" name="output_profile" class="form-input" placeholder="Enter output profile name" required />
                    <div id="output-profile-error" class="form-error"></div>
                </div>

                <div class="form-group">
                    <div class="checkbox-row">
                        <input type="checkbox" id="exit-on-access-denied" name="exit_on_access_denied" class="form-checkbox" />
                        <label for="exit-on-access-denied" class="checkbox-label">Exit on Access Denied</label>
                    </div>
                    <div class="checkbox-row" style="margin-top: 0.375rem;">
                        <input type="checkbox" id="debug" name="debug" class="form-checkbox" />
                        <label for="debug" class="checkbox-label">Debug Mode</label>
                    </div>
                </div>

                <div class="btn-row" style="margin-top: 0.75rem; padding-top: 0.5rem; border-top: 1px solid var(--border-default);">
                    <button type="submit" id="start-btn" class="btn btn-start">Start</button>
                    <button type="button" id="stop-btn" class="btn btn-stop" disabled>Stop</button>
                    <button type="button" id="restart-btn" class="btn btn-restart" disabled>Restart</button>
                </div>

                <div id="form-error" class="form-error" style="margin-top: 0.5rem; padding: 0.5rem; background: rgba(255,0,68,0.1); border: 1px solid var(--accent-red); border-radius: 0.25rem;"></div>
            </form>
        `;
    }

    attachEventListeners() {
        const form = this.querySelector('#config-form');
        const stopBtn = this.querySelector('#stop-btn');
        const restartBtn = this.querySelector('#restart-btn');

        form.addEventListener('submit', (e) => {
            e.preventDefault();
            this.startTool();
        });

        stopBtn.addEventListener('click', () => this.stopTool());
        restartBtn.addEventListener('click', () => this.restartTool());

        // Persist config on input change
        this.querySelector('#aws-profile').addEventListener('input', () => this.saveConfig());
        this.querySelector('#output-profile').addEventListener('input', () => this.saveConfig());
        this.querySelector('#exit-on-access-denied').addEventListener('change', () => this.saveConfig());
        this.querySelector('#debug').addEventListener('change', () => this.saveConfig());
    }

    saveConfig() {
        const config = this.getConfig();
        localStorage.setItem('notyet-config', JSON.stringify(config));
    }

    restoreConfig() {
        try {
            const saved = localStorage.getItem('notyet-config');
            if (saved) {
                this.setConfig(JSON.parse(saved));
            }
        } catch (e) {
            // Ignore corrupt data
        }
    }

    validateConfig() {
        const errors = {};
        let valid = true;
        this.clearErrors();

        const awsProfile = this.querySelector('#aws-profile').value.trim();
        const outputProfile = this.querySelector('#output-profile').value.trim();

        if (!awsProfile) {
            errors.aws_profile = 'AWS profile is required';
            valid = false;
            this.showFieldError('aws-profile', errors.aws_profile);
        }

        if (!outputProfile) {
            errors.output_profile = 'Output profile is required';
            valid = false;
            this.showFieldError('output-profile', errors.output_profile);
        }

        return { valid, errors };
    }

    getConfig() {
        return {
            aws_profile: this.querySelector('#aws-profile').value.trim(),
            output_profile: this.querySelector('#output-profile').value.trim(),
            exit_on_access_denied: this.querySelector('#exit-on-access-denied').checked,
            debug: this.querySelector('#debug').checked
        };
    }

    setConfig(config) {
        if (config.aws_profile) this.querySelector('#aws-profile').value = config.aws_profile;
        if (config.output_profile) this.querySelector('#output-profile').value = config.output_profile;
        this.querySelector('#exit-on-access-denied').checked = config.exit_on_access_denied || false;
        this.querySelector('#debug').checked = config.debug || false;
    }

    async startTool() {
        const validation = this.validateConfig();
        if (!validation.valid) {
            this.showFormError('Please fix the errors above.');
            return;
        }

        const config = this.getConfig();

        try {
            const response = await fetch('/api/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config)
            });

            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Failed to start tool');

            this.updateToolStatus('running');
            this.dispatchEvent(new CustomEvent('tool-started', {
                bubbles: true,
                detail: { session_id: data.session_id, status: data.status }
            }));
            this.clearFormError();
        } catch (error) {
            this.showFormError(`Failed to start: ${error.message}`);
        }
    }

    async stopTool() {
        try {
            const response = await fetch('/api/stop', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Failed to stop tool');

            this.updateToolStatus('stopped');
            this.dispatchEvent(new CustomEvent('tool-stopped', {
                bubbles: true,
                detail: { session_id: data.session_id, status: data.status }
            }));
            this.clearFormError();
        } catch (error) {
            this.showFormError(`Failed to stop: ${error.message}`);
        }
    }

    async restartTool() {
        try {
            const response = await fetch('/api/restart', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            const data = await response.json();
            if (!response.ok) throw new Error(data.error || 'Failed to restart tool');

            this.updateToolStatus('running');
            this.dispatchEvent(new CustomEvent('tool-restarted', {
                bubbles: true,
                detail: { session_id: data.session_id, status: data.status }
            }));
            this.clearFormError();
        } catch (error) {
            this.showFormError(`Failed to restart: ${error.message}`);
        }
    }

    updateToolStatus(status) {
        this.toolStatus = status;
        const startBtn = this.querySelector('#start-btn');
        const stopBtn = this.querySelector('#stop-btn');
        const restartBtn = this.querySelector('#restart-btn');

        if (!startBtn || !stopBtn || !restartBtn) return;

        if (status === 'running') {
            startBtn.disabled = true;
            stopBtn.disabled = false;
            restartBtn.disabled = false;
        } else {
            startBtn.disabled = false;
            stopBtn.disabled = true;
            restartBtn.disabled = true;
        }
    }

    showFieldError(fieldId, message) {
        const field = this.querySelector(`#${fieldId}`);
        const errorDiv = this.querySelector(`#${fieldId}-error`);
        if (field) field.classList.add('error');
        if (errorDiv) {
            errorDiv.textContent = message;
            errorDiv.classList.add('visible');
        }
    }

    showFormError(message) {
        const errorDiv = this.querySelector('#form-error');
        if (errorDiv) {
            errorDiv.textContent = message;
            errorDiv.classList.add('visible');
        }
    }

    clearErrors() {
        this.querySelectorAll('.form-input').forEach(f => f.classList.remove('error'));
        this.querySelectorAll('.form-error').forEach(e => {
            e.textContent = '';
            e.classList.remove('visible');
        });
    }

    clearFormError() {
        const errorDiv = this.querySelector('#form-error');
        if (errorDiv) {
            errorDiv.textContent = '';
            errorDiv.classList.remove('visible');
        }
    }
}

customElements.define('control-panel', ControlPanel);
export default ControlPanel;
