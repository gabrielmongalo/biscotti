/**
 * biscotti — Alpine.js UI application
 * ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 * Reactive prompt playground powered by Alpine.js.
 * No build step required.
 */

// ================================================================
// API helper
// ================================================================
const BASE = window.location.pathname.replace(/\/+$/, '');

async function api(path, method = 'GET', body = null) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body) opts.body = JSON.stringify(body);
  const res = await fetch(BASE + path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

// Auto-load most recent eval run after history loads
async function autoLoadLatestEval() {
  const s = Alpine.store('app');
  if (s.evalResult || !s.evalHistory.length || !s.currentAgent) return;
  try {
    const data = await api(`/api/agents/${encodeURIComponent(s.currentAgent)}/evals/${s.evalHistory[0].id}`);
    s.evalResult = data;
    s.evalResultsOpen = true;
    setTimeout(() => { if (typeof lucide !== 'undefined') lucide.createIcons(); }, 50);
  } catch { /* ignore */ }
}

// ================================================================
// Utilities
// ================================================================
function escHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function formatDate(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
    });
  } catch { return iso; }
}

function estimateTokens(text) {
  if (!text || !text.trim()) return 0;
  return Math.ceil(text.length / 4);
}

function formatCost(cost) {
  if (cost === null || cost === undefined) return '\u2014';
  if (cost < 0.001) return '<$0.001';
  if (cost < 0.01) return '$' + cost.toFixed(4);
  return '$' + cost.toFixed(3);
}

function scoreColor(score) {
  if (score >= 3.5) return 'var(--green)';
  if (score >= 2.5) return 'var(--amber)';
  return 'var(--red)';
}

// ================================================================
// Toast (global, lightweight)
// ================================================================
function showToast(msg, type = 'info') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'show ' + type;
  setTimeout(() => el.className = '', 2800);
}

// ================================================================
// Main Alpine store
// ================================================================
document.addEventListener('alpine:init', () => {

  Alpine.store('app', {
    // --- Agents ---
    agents: [],
    currentAgent: null,

    // --- Versions ---
    versions: [],
    currentVersionId: null,
    currentVersion: null,
    originalPrompt: '',
    prompt: '',

    // --- UI state ---
    sidebarCollapsed: false,
    activeView: 'playground',
    _agentDropdownOpen: false,
    _agentSearch: '',
    isDirty: false,
    diffActive: false,
    theme: localStorage.getItem('biscotti-theme') || 'dark',
    compareTarget: null,
    _expandedVersion: null,
    _expandedEvalCase: null,
    _evalConfigOpen: true,

    // --- Test cases ---
    testCases: [],
    selectedTestCase: '',
    tcDropdownOpen: false,
    tcSaving: false,
    tcName: '',

    // --- Test run ---
    userMessage: '',
    varValues: {},
    running: false,
    runElapsed: 0,
    _runTimer: null,
    output: '',
    outputState: 'empty', // 'empty' | 'success' | 'error'
    metrics: null,
    runHistory: [],
    runHistoryOpen: false,

    // --- Model settings ---
    settingsOpen: true,
    modelInput: '',
    modelPlaceholder: 'default (auto)',
    modelDropdownOpen: false,
    availableModels: [],
    highlightedModelIdx: -1,
    temperature: 1.0,
    reasoningEffort: null,

    // --- Inline save ---
    _savingInline: false,
    saveNotes: '',
    _bannerDismissed: false,

    // --- Confirm modal ---
    confirmOpen: false,
    confirmMsg: '',
    confirmDestructive: false,
    _confirmResolve: null,

    // --- Evals ---
    judgeConfigOpen: false,
    providerStatus: {},
    judgeModel: 'anthropic:claude-sonnet-4-6',
    judgeModelDropdownOpen: false,
    judgeModelHighlightIdx: -1,
    judgeCriteria: '',
    _savedJudgeModel: '',
    _savedJudgeCriteria: '',
    criteriaOpenIdx: -1,
    evalRunning: false,
    evalGenerating: false,
    evalTestCasesOpen: true,
    evalResultsOpen: true,
    evalHistoryOpen: false,
    evalResult: null,
    evalHistory: [],
    evalAddTcOpen: false,
    evalAddTcName: '',
    evalAddTcMsg: '',
    evalAddTcVars: {},

    // --- Coach (review mode) ---
    coachResult: null,
    coachLoading: false,
    coachError: null,
    coachPanelOpen: false,
    coachModel: '',
    coachModelDropdownOpen: false,
    coachModelHighlightIdx: -1,
    coachReviewMode: false,
    coachSuggestions: [],
    coachExpandedIdx: -1,
    coachPromptSnapshot: '',
    coachPromptEditorOpen: false,
    coachCustomPrompt: '',
    coachDefaultPrompt: `You are an expert prompt engineer. Your job is to review an AI agent's system prompt and suggest specific, actionable improvements.

Your suggestions must be:
- Specific: include the exact text to add, replace, or remove
- Actionable: each suggestion should be independently implementable
- Prioritized: list the highest-impact change first
- Practical: focus on clarity, structure, constraint specificity, and output formatting

When eval results are provided, ground suggestions in the specific failures.
When reviewing without eval results, focus on best practices:
  - Clear role definition
  - Explicit output format instructions
  - Well-defined constraints and edge cases
  - Effective use of examples (few-shot)
  - Variable placeholder usage

Do not rewrite the prompt's core purpose or domain.
Always provide a complete revised_prompt with all suggestions applied.`,

    // --- API Key Modal ---
    keyModalOpen: false,
    keyModalProvider: 'anthropic',
    keyModalValue: '',
    keyModalCallback: null,
    keyModalProviderDropdownOpen: false,

    // --- Computed ---
    get evalSettingsDirty() {
      return this.judgeModel !== this._savedJudgeModel || this.judgeCriteria !== this._savedJudgeCriteria;
    },
    get variables() {
      return [...new Set([...this.prompt.matchAll(/\{\{(\w+)\}\}/g)].map(m => m[1]))];
    },
    get promptTokens() { return estimateTokens(this.prompt); },
    get msgTokens() { return estimateTokens(this.userMessage); },
    get connectedProviders() {
      return Object.entries(this.providerStatus).filter(([, ok]) => ok).map(([id]) => id);
    },
    get disconnectedProviders() {
      return Object.entries(this.providerStatus).filter(([, ok]) => !ok).map(([id]) => id);
    },
    get judgeModelOptions() {
      const models = {
        anthropic: ['anthropic:claude-sonnet-4-6', 'anthropic:claude-opus-4-6', 'anthropic:claude-haiku-4-5'],
        openai: ['openai:gpt-4o', 'openai:gpt-4o-mini', 'openai:gpt-4.1', 'openai:gpt-4.1-mini', 'openai:o3', 'openai:o3-mini'],
      };
      const connected = this.connectedProviders;
      let all = [];
      for (const p of connected) {
        if (models[p]) all = all.concat(models[p]);
      }
      if (!all.length) all = models.anthropic.concat(models.openai);
      const q = (this.judgeModel || '').toLowerCase();
      return all.filter(m => !q || m.toLowerCase().includes(q));
    },
    get judgeModelGrouped() {
      const groups = {};
      for (const m of this.judgeModelOptions) {
        const provider = m.split(':')[0] || 'other';
        if (!groups[provider]) groups[provider] = [];
        groups[provider].push(m);
      }
      return groups;
    },
    get coachModelOptions() {
      const models = {
        anthropic: ['anthropic:claude-sonnet-4-6', 'anthropic:claude-opus-4-6', 'anthropic:claude-haiku-4-5'],
        openai: ['openai:gpt-4o', 'openai:gpt-4o-mini', 'openai:gpt-4.1', 'openai:gpt-4.1-mini', 'openai:o3', 'openai:o3-mini'],
      };
      const connected = this.connectedProviders;
      let all = [];
      for (const p of connected) {
        if (models[p]) all = all.concat(models[p]);
      }
      if (!all.length) all = models.anthropic.concat(models.openai);
      const q = (this.coachModel || '').toLowerCase();
      return all.filter(m => !q || m.toLowerCase().includes(q));
    },
    get coachModelGrouped() {
      const groups = {};
      for (const m of this.coachModelOptions) {
        const provider = m.split(':')[0] || 'other';
        if (!groups[provider]) groups[provider] = [];
        groups[provider].push(m);
      }
      return groups;
    },
    get formattedCriteria() {
      if (!this.judgeCriteria) return '';
      return this.judgeCriteria.split('\n').map(line => {
        line = escHtml(line);
        // "- Name (weight X): Description" → 3 grid cells
        const match = line.match(/^-\s+(.+?)\s*\(weight\s+([\d.]+)\)\s*:\s*(.+)$/);
        if (match) {
          return `<span class="criteria-item-name">${match[1]}</span><span class="criteria-item-weight">${match[2]}x</span><span class="criteria-item-desc">${match[3]}</span>`;
        }
        // "- Name: Description" (no weight) → 3 grid cells, empty weight
        const match2 = line.match(/^-\s+(.+?):\s*(.+)$/);
        if (match2) {
          return `<span class="criteria-item-name">${match2[1]}</span><span class="criteria-item-weight"></span><span class="criteria-item-desc">${match2[2]}</span>`;
        }
        // Plain line — spans all columns
        if (line.trim()) return `<div class="criteria-plain">${line}</div>`;
        return '';
      }).filter(Boolean).join('');
    },
    get parsedCriteria() {
      if (!this.judgeCriteria) return [];
      return this.judgeCriteria.split('\n').map(line => {
        const m1 = line.match(/^-\s+(.*?)\s*\(weight\s+([\d.]+)\)\s*:\s*(.*)$/);
        if (m1) return { name: m1[1] || '', weight: m1[2], description: m1[3] || '' };
        const m2 = line.match(/^-\s+(.*?):\s*(.*)$/);
        if (m2) return { name: m2[1] || '', weight: '1.0', description: m2[2] || '' };
        return null;
      }).filter(Boolean);
    },

    serializeCriteria(criteria) {
      return criteria.map(c => {
        const w = parseFloat(c.weight) || 1.0;
        return `- ${c.name} (weight ${w.toFixed(1)}): ${c.description}`;
      }).join('\n');
    },

    toggleCriterion(idx) {
      this.criteriaOpenIdx = this.criteriaOpenIdx === idx ? -1 : idx;
      setTimeout(() => { if (typeof lucide !== 'undefined') lucide.createIcons(); }, 0);
    },

    updateCriterion(idx, field, value) {
      const items = this.parsedCriteria;
      if (!items[idx]) return;
      items[idx][field] = value;
      this.judgeCriteria = this.serializeCriteria(items);
    },

    addCriterion() {
      const items = this.parsedCriteria;
      items.push({ name: 'New Criterion', weight: '1.0', description: 'Describe what to evaluate' });
      this.judgeCriteria = this.serializeCriteria(items);
      this.criteriaOpenIdx = items.length - 1;
      setTimeout(() => {
        if (typeof lucide !== 'undefined') lucide.createIcons();
        const rows = document.querySelectorAll('.criterion-row');
        if (rows.length) rows[rows.length - 1].scrollIntoView({ behavior: 'smooth', block: 'center' });
      }, 50);
    },

    removeCriterion(idx) {
      const items = this.parsedCriteria;
      items.splice(idx, 1);
      this.judgeCriteria = this.serializeCriteria(items);
      this.criteriaOpenIdx = -1;
    },

    // --- Init ---
    async init() {
      // Apply saved theme
      if (this.theme !== 'dark') {
        document.documentElement.setAttribute('data-theme', this.theme);
      }
      try {
        this.agents = await api('/api/agents');
      } catch {
        return;
      }
      if (this.agents.length) {
        await this.selectAgent(this.agents[0].name);
      }
      // Initialize Lucide icons after DOM update
      setTimeout(() => { if (typeof lucide !== 'undefined') lucide.createIcons(); }, 0);
    },

    // --- View switching ---
    switchView(view) {
      this.activeView = view;
      if (view === 'evals') {
        this.loadEvalSettings();
        this.loadEvalHistory().then(() => autoLoadLatestEval());
      } else if (view === 'versions') {
        this.loadVersions();
      }
      setTimeout(() => { if (typeof lucide !== 'undefined') lucide.createIcons(); }, 0);
    },

    // --- Agent selection ---
    async selectAgent(name) {
      if (this.isDirty) {
        const ok = await this.showConfirm('You have unsaved changes. Discard?', true);
        if (!ok) return;
      }
      this.currentAgent = name;
      try {
        await Promise.all([
          this.loadVersions(),
          this.loadTestCases(),
          this.loadModels(),
          this.loadRunHistory(),
        ]);
      } catch (e) {
        this.showToast('Failed to load agent: ' + e.message, true);
        return;
      }

      const cur = this.versions.find(v => v.status === 'current');
      if (cur) {
        this.loadVersion(cur);
      } else if (this.versions.length) {
        this.loadVersion(this.versions[0]);
      } else {
        const meta = await api(`/api/agents/${encodeURIComponent(name)}`);
        this.prompt = meta.default_system_prompt || '';
        this.originalPrompt = this.prompt;
      }
      this.isDirty = false;
      this.output = '';
      this.outputState = 'empty';
      this.metrics = null;
      this.selectedTestCase = '';
      // Always load settings (provider status + coach model needed globally)
      this.loadEvalSettings();
      if (this.activeView === 'evals') {
        this.loadEvalHistory().then(() => autoLoadLatestEval());
      }
      setTimeout(() => { if (typeof lucide !== 'undefined') lucide.createIcons(); }, 0);
    },

    // --- Versions ---
    async loadVersions() {
      this.versions = await api(`/api/agents/${encodeURIComponent(this.currentAgent)}/versions`);
    },

    loadVersion(pv) {
      this.currentVersionId = pv.id;
      this.currentVersion = pv;
      this.prompt = pv.system_prompt;
      this.originalPrompt = pv.system_prompt;
      this.isDirty = false;
    },

    saveVersion() {
      if (!this.prompt.trim()) { showToast('Prompt cannot be empty', 'error'); return; }
      this._savingInline = true;
    },

    async confirmSaveVersion() {
      const notes = this.saveNotes.trim();
      try {
        const pv = await api(`/api/agents/${encodeURIComponent(this.currentAgent)}/versions`, 'POST', {
          agent_name: this.currentAgent,
          system_prompt: this.prompt.trim(),
          notes,
          created_by: 'user',
        });
        await this.loadVersions();
        const saved = this.versions.find(v => v.id === pv.id);
        if (saved) this.loadVersion(saved);
        this._savingInline = false;
        this.saveNotes = '';
        // Auto-dismiss remaining coach suggestions on save
        if (this.coachReviewMode) this.exitReviewMode();
        showToast(`Saved as v${pv.version}`, 'success');
      } catch (e) {
        showToast('Failed to save: ' + e.message, 'error');
      }
    },

    async promoteVersion(id = null) {
      const targetId = id || this.currentVersionId;
      if (!targetId) return;
      if (!id) {
        if (!await this.showConfirm('Set this version as current? The previous current version will be archived.')) return;
      } else {
        if (!await this.showConfirm('Set this version as current?')) return;
      }
      await api(`/api/agents/${encodeURIComponent(this.currentAgent)}/versions/${targetId}/promote`, 'POST');
      await this.loadVersions();
      if (!id && this.currentVersion) this.currentVersion.status = 'current';
      showToast('Set as current', 'success');
    },

    async deleteVersion(id) {
      if (!await this.showConfirm('Delete this version? This cannot be undone.', true)) return;
      try {
        await api(`/api/agents/${encodeURIComponent(this.currentAgent)}/versions/${id}`, 'DELETE');
        await this.loadVersions();
        if (this.currentVersionId === id && this.versions.length) {
          this.loadVersion(this.versions[0]);
        }
        showToast('Version deleted', 'success');
      } catch (e) {
        showToast(e.message || 'Failed to delete', 'error');
      }
    },

    discardChanges() {
      this.prompt = this.originalPrompt;
      this.isDirty = false;
      this.diffActive = false;
    },

    compareVersion(v) {
      this.compareTarget = v;
    },

    startCompare(v) {
      this.compareTarget = v;
    },

    get versionDiffLines() {
      if (!this.compareTarget || !this.currentVersion) return [];
      const oldLines = (this.currentVersion.system_prompt || '').split('\n');
      const newLines = (this.compareTarget.system_prompt || '').split('\n');
      const result = [];
      const maxLen = Math.max(oldLines.length, newLines.length);
      // Simple line-by-line comparison (shows changes clearly for adjacent versions)
      for (let i = 0; i < maxLen; i++) {
        const oldL = i < oldLines.length ? oldLines[i] : null;
        const newL = i < newLines.length ? newLines[i] : null;
        if (oldL === newL) {
          result.push({ type: 'same', text: oldL });
        } else {
          if (oldL != null) result.push({ type: 'remove', text: oldL });
          if (newL != null) result.push({ type: 'add', text: newL });
        }
      }
      return result;
    },

    onPromptInput() {
      this.isDirty = this.prompt !== this.originalPrompt;
      if (!this.isDirty) this.diffActive = false;
    },

    // --- Test cases ---
    async loadTestCases() {
      this.testCases = await api(`/api/agents/${encodeURIComponent(this.currentAgent)}/test-cases`);
    },

    selectTestCase(name) {
      this.selectedTestCase = name;
      this.tcDropdownOpen = false;
      if (name) {
        const tc = this.testCases.find(t => t.name === name);
        if (tc) {
          this.userMessage = tc.user_message;
          const vals = {};
          this.variables.forEach(v => { vals[v] = (tc.variable_values || {})[v] || ''; });
          this.varValues = vals;
        }
      }
    },

    startSaveTestCase() {
      this.tcSaving = true;
      this.tcName = '';
    },

    async confirmSaveTestCase() {
      if (!this.tcName.trim()) { showToast('Give it a name', 'error'); return; }
      await api(`/api/agents/${encodeURIComponent(this.currentAgent)}/test-cases`, 'POST', {
        agent_name: this.currentAgent,
        name: this.tcName.trim(),
        user_message: this.userMessage,
        variable_values: { ...this.varValues },
      });
      this.tcSaving = false;
      await this.loadTestCases();
      showToast('Test case saved', 'success');
    },

    async deleteTestCase() {
      if (!this.selectedTestCase) return;
      await this.deleteTestCaseByName(this.selectedTestCase);
      this.selectedTestCase = '';
    },

    async deleteTestCaseByName(name) {
      if (!await this.showConfirm(`Delete test case "${name}"?`, true)) return;
      await api(`/api/agents/${encodeURIComponent(this.currentAgent)}/test-cases/${encodeURIComponent(name)}`, 'DELETE');
      if (this.selectedTestCase === name) this.selectedTestCase = '';
      await this.loadTestCases();
      showToast('Test case deleted', 'success');
    },

    async saveEvalTestCase() {
      const name = this.evalAddTcName.trim();
      const msg = this.evalAddTcMsg.trim();
      if (!name || !msg) return;
      try {
        await api(`/api/agents/${encodeURIComponent(this.currentAgent)}/test-cases`, 'POST', {
          agent_name: this.currentAgent, name, user_message: msg, variable_values: { ...this.evalAddTcVars },
        });
        this.evalAddTcName = '';
        this.evalAddTcMsg = '';
        this.evalAddTcVars = {};
        this.evalAddTcOpen = false;
        await this.loadTestCases();
        showToast('Test case added', 'success');
      } catch (e) {
        showToast('Failed: ' + e.message, 'error');
      }
    },

    // --- Models ---
    async loadModels() {
      try {
        const data = await api(`/api/agents/${encodeURIComponent(this.currentAgent)}/models`);
        this.availableModels = data.all || [];
        this.modelPlaceholder = data.detected ? data.detected + ' (detected)' : 'default (auto)';
      } catch {
        this.availableModels = [];
      }
    },

    get filteredModels() {
      const q = (this.modelInput || '').toLowerCase().trim();
      return this.availableModels.filter(m => !q || m.toLowerCase().includes(q));
    },

    get groupedModels() {
      const groups = {};
      for (const m of this.filteredModels) {
        let provider = 'other';
        if (m.startsWith('gpt-') || m.startsWith('o3') || m.startsWith('o4')) provider = 'openai';
        else if (m.startsWith('claude-')) provider = 'anthropic';
        else if (m.startsWith('gemini-')) provider = 'google';
        if (!groups[provider]) groups[provider] = [];
        groups[provider].push(m);
      }
      return groups;
    },

    selectModel(name) {
      this.modelInput = name;
      this.modelDropdownOpen = false;
      this.highlightedModelIdx = -1;
    },

    stepTemp(delta) {
      let val = Math.round((parseFloat(this.temperature || 0) + delta) * 10) / 10;
      this.temperature = Math.max(0, Math.min(2, val));
    },

    setEffort(level) {
      this.reasoningEffort = level;
    },

    // --- Run test ---
    async runTest() {
      if (!this.userMessage.trim()) { showToast('Enter a user message first', 'error'); return; }
      this.running = true;
      this.runElapsed = 0;
      this._runTimer = setInterval(() => { this.runElapsed += 0.1; }, 100);
      this.output = '';
      this.outputState = 'empty';
      this.metrics = null;

      try {
        const body = {
          agent_name: this.currentAgent,
          prompt_version_id: this.currentVersionId || null,
          user_message: this.userMessage,
          variable_values: { ...this.varValues },
        };
        if (this.modelInput) body.model = this.modelInput;
        if (this.temperature !== null) body.temperature = this.temperature;
        if (this.reasoningEffort) body.reasoning_effort = this.reasoningEffort;

        const result = await api('/api/run', 'POST', body);

        if (result.outcome === 'error') {
          this.outputState = 'error';
          this.output = result.error_message || 'An error occurred.';
        } else {
          this.outputState = 'success';
          this.output = result.output;
        }

        const inTok = result.input_tokens || 0;
        const outTok = result.output_tokens || 0;
        this.metrics = {
          latency: result.latency_ms,
          totalTokens: inTok + outTok,
          inTokens: inTok,
          outTokens: outTok,
          model: result.model_used && result.model_used !== 'unknown' ? result.model_used : null,
          cost: result.estimated_cost,
        };
      } catch (e) {
        this.outputState = 'error';
        this.output = 'Request failed: ' + e.message;
      } finally {
        clearInterval(this._runTimer);
        this._runTimer = null;
        this.running = false;
        this.loadRunHistory();
      }
    },

    async loadRunHistory() {
      if (!this.currentAgent) return;
      try {
        this.runHistory = await api(`/api/agents/${encodeURIComponent(this.currentAgent)}/runs?limit=20`);
      } catch { /* ignore */ }
    },

    // --- Confirm modal ---
    showConfirm(msg, destructive = false) {
      if (this._confirmResolve) this._confirmResolve(false);
      this.confirmMsg = msg;
      this.confirmDestructive = destructive;
      this.confirmOpen = true;
      return new Promise(r => { this._confirmResolve = r; });
    },

    resolveConfirm(val) {
      this.confirmOpen = false;
      if (this._confirmResolve) { this._confirmResolve(val); this._confirmResolve = null; }
    },

    // --- Evals ---
    async loadEvalSettings() {
      if (!this.currentAgent) return;
      try {
        const s = await api(`/api/agents/${encodeURIComponent(this.currentAgent)}/settings`);
        this.judgeModel = s.judge_model || 'anthropic:claude-sonnet-4-6';
        this.judgeCriteria = s.judge_criteria || '';
        this._savedJudgeModel = this.judgeModel;
        this._savedJudgeCriteria = this.judgeCriteria;
        this.coachModel = s.coach_model || '';
        this.providerStatus = await api('/api/settings/status');
      } catch { /* ignore on first load */ }
    },

    selectJudgeModel(name) {
      this.judgeModel = name;
      this.judgeModelDropdownOpen = false;
      this.judgeModelHighlightIdx = -1;
    },

    selectCoachModel(name) {
      this.coachModel = name;
      this.coachModelDropdownOpen = false;
      this.coachModelHighlightIdx = -1;
      // Persist to backend
      if (this.currentAgent) {
        api(`/api/agents/${encodeURIComponent(this.currentAgent)}/settings`, 'PUT', {
          coach_model: name,
        }).catch(() => {});
      }
    },

    // --- API Key Modal ---
    extractProvider(modelStr) {
      if (!modelStr) return '';
      return modelStr.split(':')[0] || '';
    },

    async requireKey(provider, callback) {
      // Ensure provider status is loaded
      if (!Object.keys(this.providerStatus).length) {
        try { this.providerStatus = await api('/api/settings/status'); } catch {}
      }
      if (this.providerStatus[provider]) {
        callback();
        return;
      }
      this.keyModalProvider = provider;
      this.keyModalValue = '';
      this.keyModalCallback = callback;
      this.keyModalOpen = true;
    },

    async openKeyManager() {
      // Ensure provider status is loaded
      if (!Object.keys(this.providerStatus).length) {
        try { this.providerStatus = await api('/api/settings/status'); } catch {}
      }
      this.keyModalProvider = this.disconnectedProviders.length ? this.disconnectedProviders[0] : 'anthropic';
      this.keyModalValue = '';
      this.keyModalCallback = null;
      this.keyModalOpen = true;
    },

    async submitModalKey() {
      const key = (this.keyModalValue || '').trim();
      if (!key) { showToast('Enter an API key', 'error'); return; }
      try {
        await api('/api/settings/api-key', 'POST', { provider: this.keyModalProvider, key });
        this.keyModalValue = '';
        const label = this.keyModalProvider.charAt(0).toUpperCase() + this.keyModalProvider.slice(1);
        showToast(`${label} key saved`, 'success');
        await this.loadEvalSettings();
        this.keyModalOpen = false;
        if (this.keyModalCallback) {
          const cb = this.keyModalCallback;
          this.keyModalCallback = null;
          cb();
        }
      } catch (e) {
        showToast('Failed: ' + e.message, 'error');
      }
    },

    closeKeyModal() {
      this.keyModalOpen = false;
      this.keyModalCallback = null;
      this.keyModalValue = '';
    },

    async disconnectProvider(provider) {
      if (!await this.showConfirm(`Disconnect ${provider.charAt(0).toUpperCase() + provider.slice(1)}? The API key will be removed from memory.`, true)) return;
      try {
        await api(`/api/settings/api-key/${encodeURIComponent(provider)}`, 'DELETE');
        showToast(`${provider.charAt(0).toUpperCase() + provider.slice(1)} disconnected`, 'success');
        await this.loadEvalSettings();
      } catch (e) {
        showToast('Failed: ' + e.message, 'error');
      }
    },

    async saveEvalSettings(silent = false) {
      if (!this.currentAgent) return;
      try {
        await api(`/api/agents/${encodeURIComponent(this.currentAgent)}/settings`, 'PUT', {
          judge_model: this.judgeModel,
          judge_criteria: this.judgeCriteria,
        });
        this._savedJudgeModel = this.judgeModel;
        this._savedJudgeCriteria = this.judgeCriteria;
        if (!silent) showToast('Settings saved', 'success');
      } catch (e) {
        showToast('Failed to save: ' + e.message, 'error');
      }
    },

    async generateJudge() {
      if (!this.currentAgent) return;
      this.evalGenerating = true;
      try {
        await this.saveEvalSettings(true);
        const result = await api(`/api/agents/${encodeURIComponent(this.currentAgent)}/generate-judge`, 'POST');
        this.judgeCriteria = result.criteria;
        showToast('Judge criteria generated', 'success');
      } catch (e) {
        showToast('Failed: ' + e.message, 'error');
      } finally {
        this.evalGenerating = false;
      }
    },

    async runEval() {
      if (!this.currentAgent) return;
      if (!this.judgeCriteria.trim()) { showToast('Set judge criteria first', 'error'); return; }
      const provider = this.extractProvider(this.judgeModel);
      this.requireKey(provider, () => this._doRunEval());
    },

    async _doRunEval() {
      this.evalRunning = true;
      try {
        await this.saveEvalSettings(true);
        const result = await api(`/api/agents/${encodeURIComponent(this.currentAgent)}/eval`, 'POST', {
          prompt_version_id: this.currentVersionId || null,
        });
        this.evalResult = result;
        this._evalConfigOpen = false;
        this.coachResult = null;
        await this.loadEvalHistory();
        showToast('Eval complete', 'success');
      } catch (e) {
        showToast('Eval failed: ' + e.message, 'error');
      } finally {
        this.evalRunning = false;
      }
    },

    async loadEvalHistory() {
      if (!this.currentAgent) return;
      try {
        this.evalHistory = await api(`/api/agents/${encodeURIComponent(this.currentAgent)}/evals`);
      } catch { /* ignore */ }
    },

    async loadEvalRun(evalId) {
      if (!this.currentAgent) return;
      this.coachResult = null;
      this.coachError = null;
      try {
        this.evalResult = await api(`/api/agents/${encodeURIComponent(this.currentAgent)}/evals/${evalId}`);
        this.evalResultsOpen = true;
      } catch (e) {
        showToast('Failed to load eval: ' + e.message, 'error');
      }
    },

    // --- Coach ---
    async runCoach() {
      if (!this.currentAgent || !this.prompt.trim()) return;
      const model = this.coachModel || this.judgeModel;
      if (!model) {
        showToast('Select a model first', 'error');
        return;
      }
      const provider = this.extractProvider(model);
      this.requireKey(provider, () => this._doRunCoach());
    },

    async _doRunCoach() {
      this.coachLoading = true;
      this.coachError = null;
      this.coachPanelOpen = true;
      try {
        const body = { prompt: this.prompt };
        if (this.coachModel) body.coach_model = this.coachModel;
        if (this.coachCustomPrompt.trim()) body.coach_system_prompt = this.coachCustomPrompt.trim();
        if (this.evalResult?.id) body.eval_id = this.evalResult.id;
        this.coachResult = await api(`/api/agents/${encodeURIComponent(this.currentAgent)}/coach`, 'POST', body);
        this.coachPanelOpen = false;
        this.enterReviewMode();
      } catch (e) {
        this.coachError = e.message || 'Coach analysis failed';
        showToast('Coach failed: ' + e.message, 'error');
      } finally {
        this.coachLoading = false;
      }
    },

    // Find line position for a suggestion's search_text/location_hint in the prompt
    _findSuggestionLines(s) {
      const promptLines = this.prompt.split('\n');
      let lineStart = -1, lineEnd = -1;

      if (s.search_text) {
        // 1. Exact match
        const searchIdx = this.prompt.indexOf(s.search_text);
        if (searchIdx >= 0) {
          lineStart = this.prompt.slice(0, searchIdx).split('\n').length - 1;
          lineEnd = lineStart + s.search_text.split('\n').length - 1;
          return { lineStart, lineEnd };
        }
        // 2. Normalized match (collapse whitespace)
        const normSearch = s.search_text.replace(/\s+/g, ' ').trim();
        const normPrompt = this.prompt.replace(/\s+/g, ' ').trim();
        const normIdx = normPrompt.indexOf(normSearch);
        if (normIdx >= 0) {
          // Map back: count newlines in original prompt up to the approximate char position
          const approxOrigIdx = Math.min(normIdx, this.prompt.length - 1);
          // Find the first line that contains the start of the normalized match
          let charCount = 0;
          for (let i = 0; i < promptLines.length; i++) {
            charCount += promptLines[i].length + 1; // +1 for newline
            if (charCount > normIdx) {
              lineStart = i;
              break;
            }
          }
          if (lineStart >= 0) {
            lineEnd = Math.min(lineStart + s.search_text.split('\n').length - 1, promptLines.length - 1);
            return { lineStart, lineEnd };
          }
        }
        // 3. Line-by-line fuzzy: find the first line of search_text in the prompt
        const searchLines = s.search_text.split('\n').map(l => l.trim()).filter(Boolean);
        if (searchLines.length > 0) {
          const firstLine = searchLines[0];
          for (let i = 0; i < promptLines.length; i++) {
            const trimmed = promptLines[i].trim();
            if (trimmed && (trimmed.includes(firstLine) || firstLine.includes(trimmed))) {
              lineStart = i;
              lineEnd = Math.min(i + searchLines.length - 1, promptLines.length - 1);
              return { lineStart, lineEnd };
            }
          }
        }
      }

      // 4. location_hint fallback
      if (s.location_hint) {
        const hintIdx = this.prompt.indexOf(s.location_hint);
        if (hintIdx >= 0) {
          lineStart = this.prompt.slice(0, hintIdx).split('\n').length - 1;
          return { lineStart, lineEnd: lineStart };
        }
        // Try partial match on location_hint
        for (let i = 0; i < promptLines.length; i++) {
          if (promptLines[i].trim().includes(s.location_hint.trim())) {
            return { lineStart: i, lineEnd: i };
          }
        }
      }

      // 5. Last resort: place at end
      return { lineStart: promptLines.length - 1, lineEnd: promptLines.length - 1 };
    },

    enterReviewMode() {
      if (!this.coachResult?.suggestions?.length) return;
      this.coachPromptSnapshot = this.prompt;
      const totalLines = this.prompt.split('\n').length;
      this.coachSuggestions = this.coachResult.suggestions.map((s, idx) => {
        const { lineStart, lineEnd } = this._findSuggestionLines(s);
        const matched = !(lineStart === totalLines - 1 && lineEnd === totalLines - 1 && !s.search_text?.includes(this.prompt.split('\n')[totalLines - 1]?.trim()));
        return { ...s, idx, lineStart, lineEnd, matched, status: 'pending' };
      });
      // Spread unmatched suggestions evenly across the prompt instead of dumping at end
      const unmatched = this.coachSuggestions.filter(s => !s.matched);
      if (unmatched.length > 0) {
        const step = Math.max(1, Math.floor(totalLines / (unmatched.length + 1)));
        unmatched.forEach((s, i) => {
          s.lineStart = Math.min((i + 1) * step, totalLines - 1);
          s.lineEnd = s.lineStart;
        });
      }
      // De-duplicate: ensure each suggestion has a unique lineStart so badges don't stack
      const usedStarts = new Set();
      for (const s of this.coachSuggestions) {
        while (usedStarts.has(s.lineStart) && s.lineStart < totalLines - 1) {
          s.lineStart++;
          s.lineEnd = Math.max(s.lineEnd, s.lineStart);
        }
        // Also try going upward if stuck at the bottom
        while (usedStarts.has(s.lineStart) && s.lineStart > 0) {
          s.lineStart--;
        }
        usedStarts.add(s.lineStart);
      }
      this.coachReviewMode = true;
      this.coachExpandedIdx = -1;
      setTimeout(() => lucide.createIcons(), 50);
    },

    get reviewLines() {
      if (!this.coachReviewMode) return [];
      const lines = this.prompt.split('\n');
      return lines.map((text, i) => {
        const suggestions = this.coachSuggestions.filter(
          s => s.status === 'pending' && i >= s.lineStart && i <= s.lineEnd
        );
        // Suggestions that START on this line (for showing badges)
        const startsHere = this.coachSuggestions.filter(
          s => s.status === 'pending' && s.lineStart === i
        );
        const action = suggestions.length > 0 ? suggestions[0].action : null;
        return {
          text, num: i + 1, lineIdx: i, action,
          suggestionIdx: suggestions.length > 0 ? suggestions[0].idx : -1,
          badgeCount: startsHere.length,
        };
      });
    },

    get pendingSuggestions() {
      return this.coachSuggestions.filter(s => s.status === 'pending');
    },

    toggleReviewComment(idx) {
      if (this.coachExpandedIdx === idx) {
        // If collapsing, try to show next suggestion on same line
        const s = this.coachSuggestions[idx];
        if (s) {
          const siblings = this.coachSuggestions.filter(
            sib => sib.status === 'pending' && sib.lineEnd === s.lineEnd && sib.idx !== idx
          );
          if (siblings.length > 0) {
            this.coachExpandedIdx = siblings[0].idx;
            setTimeout(() => lucide.createIcons(), 50);
            return;
          }
        }
        this.coachExpandedIdx = -1;
      } else {
        this.coachExpandedIdx = idx;
      }
      setTimeout(() => lucide.createIcons(), 50);
    },

    acceptSuggestion(idx) {
      const s = this.coachSuggestions[idx];
      if (!s || s.status !== 'pending') return;
      if (s.action === 'delete' && s.search_text) {
        this.prompt = this.prompt.replace(s.search_text, '');
      } else if (s.action === 'replace' && s.search_text && s.suggested_text) {
        this.prompt = this.prompt.replace(s.search_text, s.suggested_text);
      } else if (s.action === 'insert' && s.suggested_text) {
        if (s.search_text) {
          const pos = this.prompt.indexOf(s.search_text);
          if (pos >= 0) {
            const end = pos + s.search_text.length;
            this.prompt = this.prompt.slice(0, end) + '\n' + s.suggested_text + this.prompt.slice(end);
          } else {
            this.prompt += '\n' + s.suggested_text;
          }
        } else {
          this.prompt += '\n' + s.suggested_text;
        }
      }
      s.status = 'accepted';
      this.isDirty = this.prompt !== this.originalPrompt;
      this.recalcLinePositions();
      this.checkReviewComplete();
      setTimeout(() => lucide.createIcons(), 50);
    },

    dismissSuggestion(idx) {
      const s = this.coachSuggestions[idx];
      if (s) s.status = 'dismissed';
      this.checkReviewComplete();
    },

    acceptAllSuggestions() {
      const pending = this.coachSuggestions.filter(s => s.status === 'pending');
      for (const s of pending) this.acceptSuggestion(s.idx);
    },

    dismissAllSuggestions() {
      this.coachSuggestions.forEach(s => { if (s.status === 'pending') s.status = 'dismissed'; });
      this.exitReviewMode();
    },

    recalcLinePositions() {
      const totalLines = this.prompt.split('\n').length;
      const pending = this.coachSuggestions.filter(s => s.status === 'pending');
      // Re-find positions
      for (const s of pending) {
        const { lineStart, lineEnd } = this._findSuggestionLines(s);
        s.lineStart = lineStart;
        s.lineEnd = lineEnd;
      }
      // De-duplicate: ensure unique lineStarts
      const usedStarts = new Set();
      for (const s of pending) {
        while (usedStarts.has(s.lineStart) && s.lineStart < totalLines - 1) {
          s.lineStart++;
          s.lineEnd = Math.max(s.lineEnd, s.lineStart);
        }
        while (usedStarts.has(s.lineStart) && s.lineStart > 0) {
          s.lineStart--;
        }
        usedStarts.add(s.lineStart);
      }
    },

    checkReviewComplete() {
      if (this.pendingSuggestions.length === 0) {
        this.exitReviewMode();
      }
    },

    exitReviewMode() {
      this.coachReviewMode = false;
      this.coachSuggestions = [];
      this.coachExpandedIdx = -1;
      this.coachResult = null;
    },

    async rerunCoach() {
      // Exit review, re-analyze with current (possibly modified) prompt
      this.exitReviewMode();
      this.coachPanelOpen = true;
      await this.runCoach();
    },

    async rerunSuggestion(idx) {
      const s = this.coachSuggestions[idx];
      if (!s || s.status !== 'pending') return;
      const model = this.coachModel || this.judgeModel;
      if (!model) return;
      this.coachLoading = true;
      try {
        const section = s.search_text || s.location_hint || '';
        const body = {
          prompt: this.prompt,
          coach_model: model,
          focus_section: section,
        };
        if (this.evalResult?.id) body.eval_id = this.evalResult.id;
        const result = await api(`/api/agents/${encodeURIComponent(this.currentAgent)}/coach`, 'POST', body);
        // Replace this suggestion with the first one from the new result
        if (result.suggestions?.length > 0) {
          const newS = result.suggestions[0];
          s.action = newS.action;
          s.title = newS.title;
          s.description = newS.description;
          s.search_text = newS.search_text || s.search_text;
          s.suggested_text = newS.suggested_text || '';
          s.location_hint = newS.location_hint || '';
          this.recalcLinePositions();
          showToast('Suggestion refreshed', 'success');
        }
      } catch (e) {
        showToast('Re-run failed: ' + e.message, 'error');
      } finally {
        this.coachLoading = false;
        setTimeout(() => lucide.createIcons(), 50);
      }
    },

    // --- Theme ---
    toggleTheme() {
      this.theme = this.theme === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', this.theme);
      localStorage.setItem('biscotti-theme', this.theme);
    },

    // --- Diff ---
    get diffLines() {
      if (!this.diffActive) return [];
      const oldLines = this.originalPrompt.split('\n');
      const newLines = this.prompt.split('\n');
      const lines = [];
      const maxLen = Math.max(oldLines.length, newLines.length);
      for (let i = 0; i < maxLen; i++) {
        const o = oldLines[i], n = newLines[i];
        if (o === n) {
          if (o !== undefined) lines.push({ type: 'ctx', text: o });
        } else {
          if (o !== undefined) lines.push({ type: 'removed', text: o });
          if (n !== undefined) lines.push({ type: 'added', text: n });
        }
      }
      return lines;
    },

    // --- Clipboard ---
    async copyToClipboard(text, event) {
      if (!text) return;
      await navigator.clipboard.writeText(text);
      const btn = event.currentTarget;
      btn.classList.add('copied');
      setTimeout(() => btn.classList.remove('copied'), 1200);
    },
  });
});

// ================================================================
// Keyboard shortcuts (global)
// ================================================================
document.addEventListener('keydown', (e) => {
  const store = Alpine.store('app');
  if (!store) return;

  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
    e.preventDefault();
    if (store.activeView === 'playground') store.runTest();
    else if (store.activeView === 'evals') store.runEval();
  }
  if (e.key === 'Escape') {
    store.tcSaving = false;
    store._savingInline = false;
    store.resolveConfirm(false);
    if (store.compareTarget) { store.compareTarget = null; return; }
    if (store.keyModalOpen) store.closeKeyModal();
    if (store.coachResult) { store.coachResult = null; store.coachPanelOpen = false; }
  }
});
