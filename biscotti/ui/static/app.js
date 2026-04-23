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

// ================================================================
// Utilities
// ================================================================
function escHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function highlightVars(s) {
  return escHtml(s || '').replace(/\{\{(\w+)\}\}/g, '<span class=\'var-token\'>{{$1}}</span>');
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

    // --- Agent metadata (PydanticAI) ---
    agentTools: [],
    agentOutputType: 'str',
    agentKnownVars: [],
    agentDefaultMessage: '',

    // --- Test run ---
    userMessage: '',
    varValues: {},
    running: false,
    runElapsed: 0,
    _runTimer: null,
    output: '',
    outputState: 'empty', // 'empty' | 'success' | 'error'
    outputOpen: true,
    metrics: null,
    runHistory: [],
    runHistoryOpen: false,

    // --- Section collapse state ---
    tcSectionOpen: true,
    toolsSectionOpen: true,

    // --- Model settings ---
    settingsOpen: false,
    modelInput: '',
    modelPlaceholder: 'default (auto)',
    availableModels: [],
    temperature: 1.0,
    reasoningEffort: null,

    // --- Inline save ---
    _savingInline: false,
    saveNotes: '',
    _bannerDismissed: sessionStorage.getItem('biscotti-banner-dismissed') === '1',

    // --- Confirm modal ---
    confirmOpen: false,
    confirmMsg: '',
    confirmDestructive: false,
    _confirmResolve: null,

    // --- Evals ---
    judgeConfigOpen: false,
    providerStatus: {},
    judgeModel: '',
    judgeCriteria: '',
    criteriaRows: [],
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
    keyModalAddingProvider: false,

    // Azure Foundry (multi-connection)
    azureConnections: [],        // [{name, endpoint, auth, api_version, deployments, discovered_at, discovery_error}]
    azureExpanded: {},           // {connectionName: bool} — UI expansion state per card
    azureAdding: false,          // is the "Add connection" form visible?
    // Add-form state
    azureForm: {
      name: '',
      endpoint: '',
      auth: 'key',
      key: '',
      api_version: '2024-10-21',
    },
    azureFormBusy: false,
    azureRefreshBusy: {},        // {connectionName: bool}

    // --- Bulk Run ---
    bulkSubView: 'new',
    bulkSelectedTests: [],
    bulkSelectedModels: [],
    bulkSelectedTemps: [],
    bulkReasoningEfforts: [],
    bulkIncludeEval: false,
    bulkJudgeModel: '',
    bulkConcurrency: 3,
    bulkAdvancedOpen: false,
    bulkRunning: false,
    bulkConfigExpanded: false,
    bulkResults: [],
    bulkCompleted: 0,
    bulkTotalRuns: 0,
    bulkCurrentId: null,
    bulkViewedRun: null,
    bulkHistory: [],
    bulkSortCol: null,
    bulkSortAsc: true,
    bulkExportOpen: false,
    bulkTempInput: '',
    _bulkEventSource: null,
    bulkConfigCollapsed: false,
    _bulkModelSearch: '',
    _bulkJudgeModelSearch: '',

    // --- Computed ---
    get evalSettingsDirty() {
      return this.judgeModel !== this._savedJudgeModel || this.serializeCriteria(this.criteriaRows) !== this._savedJudgeCriteria;
    },
    get variables() {
      // Only reflect what's live in the system prompt and user message.
      // Agent-declared/historical vars are tracked in agentKnownVars for
      // other uses but don't pollute the input list — if you delete
      // {{founded}} from the text, its input disappears.
      const fromPrompt = [...this.prompt.matchAll(/\{\{(\w+)\}\}/g)].map(m => m[1]);
      const fromMsg = [...(this.userMessage || '').matchAll(/\{\{(\w+)\}\}/g)].map(m => m[1]);
      return [...new Set([...fromPrompt, ...fromMsg])];
    },
    get promptTokens() { return estimateTokens(this.prompt); },
    get msgTokens() { return estimateTokens(this.userMessage); },
    get connectedProviders() {
      return Object.entries(this.providerStatus).filter(([, ok]) => ok).map(([id]) => id)
        .sort((a, b) => (this._PROVIDER_LABELS[a] || a).localeCompare(this._PROVIDER_LABELS[b] || b));
    },
    get disconnectedProviders() {
      return Object.entries(this.providerStatus).filter(([, ok]) => !ok).map(([id]) => id)
        .sort((a, b) => (this._PROVIDER_LABELS[a] || a).localeCompare(this._PROVIDER_LABELS[b] || b));
    },
    // Normalize a saved/external model string for display in a picker:
    //  1. Collapse redundant provider prefix (mirrors router.py::_canonical) so
    //     a historically-saved "anthropic:claude-haiku-4-5" matches the bare
    //     canonical "claude-haiku-4-5" surfaced in availableModels.
    //  2. If the result still isn't in availableModels (provider key was
    //     removed, model retired, etc.), return '' so the picker starts empty
    //     and the user must reselect from what's actually reachable.
    _canonicalModel(m) {
      if (!m) return '';
      if (m.startsWith('azure:')) {
        return this.availableModels.includes(m) ? m : '';
      }
      if (m.includes(':')) {
        const bare = m.slice(m.indexOf(':') + 1);
        if (bare && this.availableModels.includes(bare)) return bare;
      }
      return this.availableModels.includes(m) ? m : '';
    },
    // Shared filter helper for every model-picker dropdown. `query` is the
    // search string bound to the input; `excluded` is an optional list of
    // models to hide (used by Bulk Run to drop already-selected chips).
    _filterModelsByQuery(query, excluded = null) {
      const q = (query || '').toLowerCase().trim();
      return this.availableModels.filter(m =>
        (!excluded || !excluded.includes(m))
        && (!q || m.toLowerCase().includes(q))
      );
    },
    get judgeFilteredModels()     { return this._filterModelsByQuery(this.judgeModel); },
    get judgeGroupedModels()      { return this.groupModelsByProvider(this.judgeFilteredModels); },
    get coachFilteredModels()     { return this._filterModelsByQuery(this.coachModel); },
    get coachGroupedModels()      { return this.groupModelsByProvider(this.coachFilteredModels); },
    get bulkFilteredModels()      { return this._filterModelsByQuery(this._bulkModelSearch, this.bulkSelectedModels); },
    get bulkGroupedModels()       { return this.groupModelsByProvider(this.bulkFilteredModels); },
    get bulkJudgeFilteredModels() { return this._filterModelsByQuery(this._bulkJudgeModelSearch); },
    get bulkJudgeGroupedModels()  { return this.groupModelsByProvider(this.bulkJudgeFilteredModels); },
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
    loadCriteriaRows() {
      if (!this.judgeCriteria) {
        this.criteriaRows = [];
        return;
      }
      this.criteriaRows = this.judgeCriteria.split('\n').map(line => {
        const m1 = line.match(/^-\s+(.*?)\s*\(weight\s+([\d.]+)\)\s*:\s*(.*)$/);
        if (m1) return { name: m1[1] || '', weight: m1[2], description: m1[3] || '' };
        const m2 = line.match(/^-\s+(.*?):\s*(.*)$/);
        if (m2) return { name: m2[1] || '', weight: '', description: m2[2] || '' };
        return null;
      }).filter(Boolean);
    },

    serializeCriteria(criteria) {
      return criteria.map(c => {
        const name = (c.name || '').trim();
        const desc = (c.description || '').trim();
        const wRaw = String(c.weight || '').trim();
        if (wRaw !== '') {
          let w = parseFloat(wRaw);
          if (isNaN(w)) w = 1.0;
          w = Math.min(1, Math.max(0, w));
          return `- ${name} (weight ${w.toFixed(1)}): ${desc}`;
        }
        return `- ${name}: ${desc}`;
      }).join('\n');
    },

    toggleCriterion(idx) {
      this.criteriaOpenIdx = this.criteriaOpenIdx === idx ? -1 : idx;
      setTimeout(() => { if (typeof lucide !== 'undefined') lucide.createIcons(); }, 0);
    },

    addCriterion() {
      this.criteriaRows.push({ name: '', description: '', weight: '' });
      this.criteriaOpenIdx = this.criteriaRows.length - 1;
      setTimeout(() => {
        if (typeof lucide !== 'undefined') lucide.createIcons();
        const rows = document.querySelectorAll('.criterion-row');
        if (rows.length) rows[rows.length - 1].scrollIntoView({ behavior: 'smooth', block: 'center' });
      }, 50);
    },

    removeCriterion(idx) {
      this.criteriaRows.splice(idx, 1);
      this.criteriaOpenIdx = -1;
    },

    async saveCriteria() {
      this.judgeCriteria = this.serializeCriteria(this.criteriaRows);
      await this.saveEvalSettings();
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
        this.loadEvalHistory().then(() => {
          const s = Alpine.store('app');
          if (!s.evalHistory.length || !s.currentAgent) return;
          const latestId = s.evalHistory[0].id;
          if (s.evalResult && s.evalResult.id === latestId) return;
          api(`/api/agents/${encodeURIComponent(s.currentAgent)}/evals/${latestId}`)
            .then(data => {
              Alpine.store('app').evalResult = data;
              Alpine.store('app').evalResultsOpen = true;
              setTimeout(() => { if (typeof lucide !== 'undefined') lucide.createIcons(); }, 50);
            })
            .catch(() => {});
        });
      } else if (view === 'versions') {
        this.loadVersions();
      }
      if (view === 'bulk' && this.currentAgent) {
        this.loadTestCases();
        this.loadModels();
        this.loadBulkHistory();
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

      // Fetch agent detail for PydanticAI metadata (tools, output type)
      const detail = await api(`/api/agents/${encodeURIComponent(name)}`);
      this.agentTools = detail.tools || [];
      this.agentOutputType = (detail.output_type && detail.output_type.type) || 'str';
      this.agentDefaultMessage = detail.default_message || '';
      // Collect known variables: registered metadata + union across all test case templates
      const metaVars = detail.variables || [];
      const tcVars = [];
      for (const tc of this.testCases) {
        const found = [...(tc.user_message || '').matchAll(/\{\{(\w+)\}\}/g)].map(m => m[1]);
        tcVars.push(...found, ...Object.keys(tc.variable_values || {}));
      }
      this.agentKnownVars = [...new Set([...metaVars, ...tcVars])];

      const cur = this.versions.find(v => v.status === 'current');
      if (cur) {
        this.loadVersion(cur);
      } else if (this.versions.length) {
        this.loadVersion(this.versions[0]);
      } else {
        this.prompt = detail.default_system_prompt || '';
        this.originalPrompt = this.prompt;
      }
      this.isDirty = false;
      this.output = '';
      this.outputState = 'empty';
      this.metrics = null;
      // Auto-select first test case if one exists, otherwise Ad hoc
      // Note: agentDefaultMessage and agentKnownVars must be set before this call
      if (this.testCases.length) {
        this.selectTestCase(this.testCases[0].name);
      } else {
        this.selectTestCase('');
      }
      // Always load settings (provider status + coach model needed globally)
      this.loadEvalSettings();
      if (this.activeView === 'evals') {
        this.loadEvalHistory().then(() => {
          const s = Alpine.store('app');
          if (!s.evalHistory.length || !s.currentAgent) return;
          const latestId = s.evalHistory[0].id;
          if (s.evalResult && s.evalResult.id === latestId) return;
          api(`/api/agents/${encodeURIComponent(s.currentAgent)}/evals/${latestId}`)
            .then(data => {
              Alpine.store('app').evalResult = data;
              Alpine.store('app').evalResultsOpen = true;
              setTimeout(() => { if (typeof lucide !== 'undefined') lucide.createIcons(); }, 50);
            })
            .catch(() => {});
        });
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
          // Set userMessage first so `this.variables` picks up user-message vars
          const vals = {};
          this.variables.forEach(v => { vals[v] = (tc.variable_values || {})[v] || ''; });
          this.varValues = vals;
        }
      } else {
        // Ad hoc: seed with the agent's registered default message template
        this.userMessage = this.agentDefaultMessage;
        const vals = {};
        this.variables.forEach(v => { vals[v] = ''; });
        this.varValues = vals;
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
        // Auto-select: use agent's detected model first, then first available
        this.modelInput = data.detected || (data.all && data.all[0]) || '';
      } catch {
        this.availableModels = [];
      }
    },

    get formattedOutput() {
      if (!this.output) return '';
      try {
        return JSON.stringify(JSON.parse(this.output), null, 2);
      } catch {
        return this.output;
      }
    },

    get isJsonOutput() {
      if (!this.output) return false;
      try { JSON.parse(this.output); return true; } catch { return false; }
    },

    get filteredModels() { return this._filterModelsByQuery(this.modelInput); },
    get groupedModels()  { return this.groupModelsByProvider(this.filteredModels); },

    selectModel(name) {
      this.modelInput = name;
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
      this.outputOpen = true;
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
          toolCalls: result.tool_calls || [],
        };
      } catch (e) {
        this.outputState = 'error';
        this.output = 'Request failed: ' + e.message;
        showToast('Run failed: ' + e.message, 'error');
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
        this.judgeModel = this._canonicalModel(s.judge_model || '');
        this.judgeCriteria = s.judge_criteria || '';
        this._savedJudgeModel = this.judgeModel;
        this._savedJudgeCriteria = this.judgeCriteria;
        this.loadCriteriaRows();
        this.criteriaOpenIdx = -1;
        // Pre-wire bulk run judge settings from agent config
        if (this.judgeCriteria) {
          this.bulkIncludeEval = true;
          this.bulkJudgeModel = this.judgeModel || '';
          this.bulkAdvancedOpen = true;
        }
        // Coach model: use saved setting, or fall back to first available model
        this.coachModel = this._canonicalModel(s.coach_model || '')
          || (this.availableModels.length ? this.availableModels[0] : '');
        this.providerStatus = await api('/api/settings/status');
      } catch { /* ignore on first load */ }
    },

    // Judge model is saved alongside criteria via the Evals "Save" button
    // (saveEvalSettings), so picking one only dirties state.
    selectJudgeModel(name) {
      this.judgeModel = name;
    },

    // Coach model is a standalone preference — persist immediately so the
    // choice carries across reloads without requiring a separate save action.
    selectCoachModel(name) {
      this.coachModel = name;
      if (this.currentAgent) {
        api(`/api/agents/${encodeURIComponent(this.currentAgent)}/settings`, 'PUT', {
          coach_model: name,
        }).catch(() => {});
      }
    },

    // --- Provider classification (single source of truth) ---
    // Every place in the app that needs to classify a model by provider
    // (grouped dropdowns, API-key prompts, labels) goes through providerOf() /
    // groupModelsByProvider() / _PROVIDER_ORDER below. Aligned with
    // router.py::_provider_of for the prefix buckets both sides care about.
    _PROVIDER_LABELS: {
      'anthropic': 'Anthropic',
      'cohere': 'Cohere',
      'deepseek': 'DeepSeek',
      'gemini': 'Google (Gemini)',
      'groq': 'Groq',
      'meta': 'Meta (Llama)',
      'mistral': 'Mistral',
      'ollama': 'Ollama',
      'openai': 'OpenAI',
      'openai-compatible': 'OpenAI-compatible',
      'together': 'Together AI',
      'xai': 'xAI (Grok)',
      'azure_foundry': 'Azure Foundry',
    },
    // Order provider groups appear in dropdowns. Anything not in this list
    // (or an unknown bucket like 'other') is appended to the end.
    _PROVIDER_ORDER: [
      'anthropic', 'openai', 'gemini', 'mistral', 'groq',
      'deepseek', 'xai', 'cohere', 'together', 'meta',
      'azure_foundry', 'ollama', 'openai-compatible',
    ],
    // Bare-name classification fallback. Ordered: longest/most specific first.
    _BARE_PREFIX_PROVIDER: [
      ['gpt-', 'openai'], ['o1', 'openai'], ['o3', 'openai'], ['o4', 'openai'],
      ['claude-', 'anthropic'],
      ['gemini-', 'gemini'],
      ['mixtral-', 'mistral'], ['mistral-', 'mistral'],
      ['command-', 'cohere'],
      ['deepseek-', 'deepseek'],
      ['grok-', 'xai'],
    ],
    _BARE_EXACT_PROVIDER: {
      'chatgpt-4o-latest': 'openai',
      'deepseek-chat': 'deepseek',
      'deepseek-reasoner': 'deepseek',
    },
    providerLabel(id) {
      return this._PROVIDER_LABELS[id] || (id.charAt(0).toUpperCase() + id.slice(1));
    },
    _nextRegularProvider() {
      const regular = this.disconnectedProviders.filter(p => p !== 'azure_foundry');
      return regular.length ? regular[0] : (this.disconnectedProviders[0] || 'anthropic');
    },
    // Classify a model string → lowercase provider id. `fallback` is returned
    // for ambiguous bare names (e.g. "llama3" could be groq/together/ollama).
    // Use '' when the caller needs to detect ambiguity (requireKey); use
    // 'other' when grouping for display.
    providerOf(modelStr, fallback = 'other') {
      if (!modelStr) return fallback;
      const s = String(modelStr).trim().toLowerCase();
      // azure:* is always Foundry (single- and multi-connection both live under
      // the same key_store bucket). Must be checked before the generic split.
      if (s.startsWith('azure:')) return 'azure_foundry';
      if (s.includes(':')) return s.split(':', 1)[0] || fallback;
      if (this._BARE_EXACT_PROVIDER[s]) return this._BARE_EXACT_PROVIDER[s];
      for (const [prefix, prov] of this._BARE_PREFIX_PROVIDER) {
        if (s.startsWith(prefix)) return prov;
      }
      return fallback;
    },
    // Group a flat list of model strings into { providerId: [model, ...] }.
    // Used by every provider-grouped dropdown in the app.
    groupModelsByProvider(models) {
      const groups = {};
      for (const m of models) {
        const p = this.providerOf(m);
        (groups[p] ||= []).push(m);
      }
      return groups;
    },
    // Ordered list of provider ids present in `groups`, respecting
    // _PROVIDER_ORDER and appending unknown buckets at the end.
    orderedProviderIds(groups) {
      const present = Object.keys(groups);
      const known = this._PROVIDER_ORDER.filter(p => present.includes(p));
      const extras = present.filter(p => !this._PROVIDER_ORDER.includes(p)).sort();
      return [...known, ...extras];
    },
    // Display string for a model inside a provider-grouped dropdown. Strips the
    // redundant provider prefix when the row is already under that provider's
    // header (e.g. "anthropic:claude-haiku-4-5" → "claude-haiku-4-5" under
    // "Anthropic", "azure:prod:insights-..." → "prod:insights-..." under
    // "Azure Foundry"). The stored value stays full-qualified.
    modelDisplayName(model, providerId) {
      if (!model) return '';
      if (providerId === 'azure_foundry' && model.startsWith('azure:')) {
        return model.slice('azure:'.length);
      }
      if (providerId && model.startsWith(providerId + ':')) {
        return model.slice(providerId.length + 1);
      }
      return model;
    },

    // --- API Key Modal ---
    extractProvider(modelStr) {
      // Returns the lowercase provider ID used as the key in providerStatus /
      // _PROVIDER_LABELS, or '' for ambiguous names (so requireKey falls
      // through to the picker).
      const p = this.providerOf(modelStr, '');
      return p === 'other' ? '' : p;
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
      this.keyModalAddingProvider = true;  // auto-open form when a specific key is required
      this.keyModalOpen = true;
    },

    async openKeyManager() {
      // Ensure provider status is loaded
      if (!Object.keys(this.providerStatus).length) {
        try { this.providerStatus = await api('/api/settings/status'); } catch {}
      }
      this.keyModalProvider = this._nextRegularProvider();
      this.keyModalValue = '';
      this.keyModalCallback = null;
      this.keyModalAddingProvider = false;
      this.keyModalOpen = true;
      await this.loadAzureConfig();
    },

    async submitModalKey() {
      const key = (this.keyModalValue || '').trim();
      if (!key) { showToast('Enter an API key', 'error'); return; }
      try {
        await api('/api/settings/api-key', 'POST', { provider: this.keyModalProvider, key });
        this.keyModalValue = '';
        const label = this.providerLabel(this.keyModalProvider);
        showToast(`${label} key saved`, 'success');
        await this.loadEvalSettings();
        // Refresh provider status so connected list updates
        try { this.providerStatus = await api('/api/settings/status'); } catch {}
        // Collapse the add-provider form after saving
        this.keyModalAddingProvider = false;
        this.keyModalProviderDropdownOpen = false;
        // Auto-select next disconnected provider if any
        if (this.disconnectedProviders.length) {
          this.keyModalProvider = this._nextRegularProvider();
        }
        if (this.keyModalCallback) {
          this.keyModalOpen = false;
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
      this.keyModalAddingProvider = false;
      this.keyModalProviderDropdownOpen = false;
    },

    // --- Azure Foundry (multi-connection) ---
    _resetAzureForm() {
      this.azureForm = { name: '', endpoint: '', auth: 'key', key: '', api_version: '2024-10-21' };
    },

    async loadAzureConfig() {
      try {
        const data = await api('/api/settings/azure/connections');
        this.azureConnections = Array.isArray(data.connections) ? data.connections : [];
      } catch {
        this.azureConnections = [];
      }
    },

    toggleAzureCard(name) {
      this.azureExpanded = { ...this.azureExpanded, [name]: !this.azureExpanded[name] };
    },

    azureLastRefreshed(conn) {
      if (!conn.discovered_at) return 'never';
      const secs = Math.max(0, Math.floor(Date.now() / 1000 - conn.discovered_at));
      if (secs < 60) return `${secs}s ago`;
      if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
      if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
      return `${Math.floor(secs / 86400)}d ago`;
    },

    async submitAzureConnection() {
      const name = (this.azureForm.name || '').trim();
      const endpoint = (this.azureForm.endpoint || '').trim();
      const auth = this.azureForm.auth === 'aad' ? 'aad' : 'key';
      const key = (this.azureForm.key || '').trim();
      const api_version = (this.azureForm.api_version || '').trim() || '2024-10-21';

      if (!name) { showToast('Enter a connection name', 'error'); return; }
      if (!endpoint) { showToast('Enter an endpoint URL', 'error'); return; }
      if (auth === 'key' && !key) { showToast('Enter an API key', 'error'); return; }

      this.azureFormBusy = true;
      try {
        const res = await api('/api/settings/azure/connections', 'POST', {
          name, endpoint, auth,
          key: auth === 'key' ? key : null,
          api_version,
        });
        // Add returned connection to list
        if (res.connection) {
          this.azureConnections = [
            ...this.azureConnections.filter(c => c.name !== res.connection.name),
            res.connection,
          ];
          this.azureExpanded = { ...this.azureExpanded, [res.connection.name]: true };
          if (res.connection.discovery_error) {
            showToast(`Connected, but discovery failed: ${res.connection.discovery_error}`, 'error');
          } else {
            const n = (res.connection.deployments || []).length;
            showToast(`Connected — found ${n} deployment${n === 1 ? '' : 's'}`, 'success');
          }
        }
        this.azureAdding = false;
        this._resetAzureForm();
        try { this.providerStatus = await api('/api/settings/status'); } catch {}
        await this.loadModels();
      } catch (e) {
        showToast('Failed: ' + e.message, 'error');
      } finally {
        this.azureFormBusy = false;
      }
    },

    async refreshAzureConnection(name) {
      this.azureRefreshBusy = { ...this.azureRefreshBusy, [name]: true };
      try {
        const res = await api(`/api/settings/azure/connections/${encodeURIComponent(name)}/refresh`, 'POST');
        if (res.connection) {
          this.azureConnections = this.azureConnections.map(c =>
            c.name === name ? res.connection : c
          );
          const n = (res.connection.deployments || []).length;
          showToast(`${name} refreshed — ${n} deployment${n === 1 ? '' : 's'}`, 'success');
        }
        await this.loadModels();
      } catch (e) {
        showToast('Refresh failed: ' + e.message, 'error');
      } finally {
        this.azureRefreshBusy = { ...this.azureRefreshBusy, [name]: false };
      }
    },

    async addAzureDeploymentManual(connName, payload) {
      try {
        const res = await api(
          `/api/settings/azure/connections/${encodeURIComponent(connName)}/deployments`,
          'POST', payload
        );
        if (res.connection) {
          this.azureConnections = this.azureConnections.map(c =>
            c.name === connName ? res.connection : c
          );
        }
        showToast(`Added deployment ${payload.name}`, 'success');
        await this.loadModels();
      } catch (e) {
        showToast('Failed: ' + e.message, 'error');
      }
    },

    async removeAzureDeploymentManual(connName, depName) {
      try {
        const res = await api(
          `/api/settings/azure/connections/${encodeURIComponent(connName)}/deployments/${encodeURIComponent(depName)}`,
          'DELETE'
        );
        if (res.connection) {
          this.azureConnections = this.azureConnections.map(c =>
            c.name === connName ? res.connection : c
          );
        }
        await this.loadModels();
      } catch (e) {
        showToast('Failed: ' + e.message, 'error');
      }
    },

    async disconnectAzureConnection(name) {
      try {
        await api(`/api/settings/azure/connections/${encodeURIComponent(name)}`, 'DELETE');
        this.azureConnections = this.azureConnections.filter(c => c.name !== name);
        showToast(`${name} disconnected`, 'success');
        try { this.providerStatus = await api('/api/settings/status'); } catch {}
        await this.loadModels();
      } catch (e) {
        showToast('Failed: ' + e.message, 'error');
      }
    },

    async disconnectProvider(provider) {
      // Azure Foundry is multi-connection — disconnect removes ALL of them.
      if (provider === 'azure_foundry') {
        const n = this.azureConnections.length;
        if (!n) return;
        const label = `${n} Foundry connection${n === 1 ? '' : 's'}`;
        if (!await this.showConfirm(`Remove all ${label}? You can re-add them later.`, true)) return;
        try {
          for (const c of [...this.azureConnections]) {
            await api(`/api/settings/azure/connections/${encodeURIComponent(c.name)}`, 'DELETE');
          }
          this.azureConnections = [];
          showToast(`Removed ${label}`, 'success');
          try { this.providerStatus = await api('/api/settings/status'); } catch {}
          await this.loadModels();
        } catch (e) {
          showToast('Failed: ' + e.message, 'error');
        }
        return;
      }
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
      // Sync criteriaRows → judgeCriteria before sending
      this.judgeCriteria = this.serializeCriteria(this.criteriaRows);
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
        this.loadCriteriaRows();
        this.criteriaOpenIdx = -1;
        showToast('Judge criteria generated', 'success');
      } catch (e) {
        showToast('Failed: ' + e.message, 'error');
      } finally {
        this.evalGenerating = false;
      }
    },

    async runEval() {
      if (!this.currentAgent) return;
      if (!this.criteriaRows.length) { showToast('Set judge criteria first', 'error'); return; }
      const provider = this.extractProvider(this.judgeModel);
      this.requireKey(provider, () => this._doRunEval());
    },

    async _doRunEval() {
      this.evalRunning = true;
      try {
        await this.saveEvalSettings(true);
        const result = await api(`/api/agents/${encodeURIComponent(this.currentAgent)}/eval`, 'POST', {
          prompt_version_id: this.currentVersionId || null,
          model: this.modelInput || null,
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
        this.coachPanelOpen = false;
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

    coachActionLabel(action) {
      // Map canonical action IDs to friendly user-facing labels.
      const a = (action || '').toLowerCase();
      const labels = {
        'insert': 'ADD',
        'add': 'ADD',
        'append': 'ADD',
        'replace': 'REPLACE',
        'update': 'REPLACE',
        'edit': 'REPLACE',
        'delete': 'REMOVE',
        'remove': 'REMOVE',
      };
      return labels[a] || a.toUpperCase();
    },

    acceptSuggestion(idx) {
      const s = this.coachSuggestions[idx];
      if (!s || s.status !== 'pending') return;
      // Normalize action synonyms — LLMs often return 'add'/'remove' instead
      // of the schema's 'insert'/'delete'.
      const action = (s.action || '').toLowerCase();
      const isInsert = action === 'insert' || action === 'add' || action === 'append';
      const isDelete = action === 'delete' || action === 'remove';
      const isReplace = action === 'replace' || action === 'update' || action === 'edit';

      let applied = false;
      if (isDelete && s.search_text) {
        if (this.prompt.includes(s.search_text)) {
          this.prompt = this.prompt.replace(s.search_text, '');
          applied = true;
        }
      } else if (isReplace && s.search_text && s.suggested_text) {
        if (this.prompt.includes(s.search_text)) {
          this.prompt = this.prompt.replace(s.search_text, s.suggested_text);
          applied = true;
        }
      } else if (isInsert && s.suggested_text) {
        if (s.search_text) {
          const pos = this.prompt.indexOf(s.search_text);
          if (pos >= 0) {
            const end = pos + s.search_text.length;
            this.prompt = this.prompt.slice(0, end) + '\n' + s.suggested_text + this.prompt.slice(end);
          } else {
            // Search anchor not found → append to end so the suggestion still lands
            this.prompt += '\n' + s.suggested_text;
          }
        } else {
          this.prompt += '\n' + s.suggested_text;
        }
        applied = true;
      }

      if (!applied) {
        // Couldn't apply — leave status pending and surface an error instead of
        // silently marking accepted (which is what used to hide the bug).
        showToast(`Couldn't apply suggestion "${s.title || s.action}" — text not found in prompt`, 'error');
        return;
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

    dismissBanner() {
      this._bannerDismissed = true;
      sessionStorage.setItem('biscotti-banner-dismissed', '1');
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

    // ================================================================
    // Bulk Run
    // ================================================================

    get bulkCanStart() {
      return this.bulkSelectedTests.length > 0
        && this.bulkSelectedModels.length > 0
        && (this.bulkSelectedTemps.length > 0 || this.bulkReasoningEfforts.length > 0)
        && !this.bulkRunning;
    },

    get bulkSummaryText() {
      const t = this.bulkSelectedTests.length;
      const m = this.bulkSelectedModels.length;
      const temps = this.bulkSelectedTemps.length;
      const res = this.bulkReasoningEfforts.length;
      const axes = temps + res;
      if (t === 0 || m === 0 || axes === 0) {
        let msg = 'Select test cases to run.';
        if (t > 0 && m === 0) msg = 'Add at least one model in Variants.';
        else if (t > 0 && m > 0 && axes === 0) msg = 'Add a temperature or choose a reasoning effort in Variants.';
        return `<span class="bulk-summary-warning">${msg}</span>`;
      }
      const total = t * m * axes;
      return `<span class="mono">${t}</span> test case${t !== 1 ? 's' : ''} &times; <span class="mono">${m}</span> model${m !== 1 ? 's' : ''} &times; <span class="mono">${axes}</span> config${axes !== 1 ? 's' : ''} = <strong class="mono">${total} run${total !== 1 ? 's' : ''}</strong>`;
    },

    get bulkConfigSummary() {
      const t = this.bulkSelectedTests.length;
      const m = this.bulkSelectedModels.length;
      const axes = this.bulkSelectedTemps.length + this.bulkReasoningEfforts.length;
      return `${t} case${t !== 1 ? 's' : ''} x ${m} model${m !== 1 ? 's' : ''} x ${axes} config${axes !== 1 ? 's' : ''}`;
    },

    get bulkProgressPercent() {
      if (this.bulkTotalRuns <= 0) return 0;
      return Math.round((this.bulkCompleted / this.bulkTotalRuns) * 100);
    },

    get bulkErrorCount() {
      return this.bulkResults.filter(r => r.outcome === 'error').length;
    },

    get bulkSortedResults() {
      if (!this.bulkSortCol) return this.bulkResults;
      const col = this.bulkSortCol;
      const asc = this.bulkSortAsc;
      return [...this.bulkResults].sort((a, b) => {
        let va = a[col], vb = b[col];
        if (va == null) va = '';
        if (vb == null) vb = '';
        if (typeof va === 'number' && typeof vb === 'number') return asc ? va - vb : vb - va;
        return asc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va));
      });
    },

    // Group results by test case name, preserving insertion order.
    get bulkResultGroups() {
      const groups = [];
      const indexMap = new Map();
      for (const row of this.bulkResults) {
        const key = row.test_case_name || 'Ad hoc';
        if (!indexMap.has(key)) {
          indexMap.set(key, groups.length);
          groups.push({ tcName: key, rows: [] });
        }
        groups[indexMap.get(key)].rows.push(row);
      }
      return groups;
    },

    bulkToggleAllTests(checked) {
      if (checked) {
        this.bulkSelectedTests = this.testCases.map(tc => tc.name);
      } else {
        this.bulkSelectedTests = [];
      }
    },

    bulkToggleTest(name) {
      const idx = this.bulkSelectedTests.indexOf(name);
      if (idx === -1) {
        this.bulkSelectedTests.push(name);
      } else {
        this.bulkSelectedTests.splice(idx, 1);
      }
    },

    bulkAddModel(m) {
      if (m && !this.bulkSelectedModels.includes(m)) {
        this.bulkSelectedModels.push(m);
      }
    },

    bulkRemoveModel(m) {
      this.bulkSelectedModels = this.bulkSelectedModels.filter(x => x !== m);
    },

    bulkAddTemp() {
      const val = parseFloat(this.bulkTempInput);
      if (isNaN(val) || val < 0 || val > 2) {
        showToast('Temperature must be between 0 and 2', 'error');
        return;
      }
      const rounded = Math.round(val * 100) / 100;
      if (!this.bulkSelectedTemps.includes(rounded)) {
        this.bulkSelectedTemps.push(rounded);
        this.bulkSelectedTemps.sort((a, b) => a - b);
      }
      this.bulkTempInput = '';
    },

    bulkRemoveTemp(t) {
      this.bulkSelectedTemps = this.bulkSelectedTemps.filter(x => x !== t);
    },

    bulkToggleReasoningEffort(re) {
      const idx = this.bulkReasoningEfforts.indexOf(re);
      if (idx === -1) {
        this.bulkReasoningEfforts.push(re);
      } else {
        this.bulkReasoningEfforts.splice(idx, 1);
      }
    },

    sortBulk(col) {
      if (this.bulkSortCol === col) {
        this.bulkSortAsc = !this.bulkSortAsc;
      } else {
        this.bulkSortCol = col;
        this.bulkSortAsc = true;
      }
    },

    async startBulkRun() {
      if (!this.bulkCanStart) return;
      const agent = this.currentAgent;
      this.bulkRunning = true;
      this.bulkResults = [];
      this.bulkCompleted = 0;
      this.bulkSubView = 'new';
      this.bulkExportOpen = false;
      this.bulkConfigCollapsed = true; // hide config form to make room for results

      const temps = this.bulkSelectedTemps;
      const res = this.bulkReasoningEfforts;
      this.bulkTotalRuns = this.bulkSelectedTests.length * this.bulkSelectedModels.length * ((temps.length + res.length) || 1);

      try {
        const data = await api(`/api/agents/${encodeURIComponent(agent)}/bulk-run`, 'POST', {
          agent_name: agent,
          test_case_names: this.bulkSelectedTests,
          models: this.bulkSelectedModels,
          temperatures: temps,
          reasoning_efforts: res,
          include_eval: this.bulkIncludeEval,
          judge_model: this.bulkIncludeEval ? this.bulkJudgeModel : null,
          concurrency: this.bulkConcurrency,
        });

        this.bulkCurrentId = data.id;
        this.bulkTotalRuns = data.total_runs;

        // Connect to SSE stream
        if (this._bulkEventSource) this._bulkEventSource.close();
        const es = new EventSource(BASE + `/api/agents/${encodeURIComponent(agent)}/bulk-runs/${data.id}/stream`);
        this._bulkEventSource = es;

        es.addEventListener('run_complete', (e) => {
          const result = JSON.parse(e.data);
          this.bulkResults.push(result);
          // Render lucide icons (copy buttons, chevrons) on the newly-added row
          setTimeout(() => { if (typeof lucide !== 'undefined') lucide.createIcons(); }, 50);
        });

        es.addEventListener('progress', (e) => {
          const d = JSON.parse(e.data);
          this.bulkCompleted = d.completed;
        });

        es.addEventListener('done', async () => {
          this.bulkRunning = false;
          es.close();
          this._bulkEventSource = null;
          // Re-fetch from DB to pick up any scores the SSE race missed
          // (judge writes score before incrementing completed_runs, but
          // concurrent tasks can cause the slice ordering to be wrong)
          try {
            const fresh = await api(`/api/agents/${encodeURIComponent(agent)}/bulk-runs/${this.bulkCurrentId}`);
            this.bulkResults = fresh.runs || this.bulkResults;
          } catch { /* keep SSE results if re-fetch fails */ }
          this.loadBulkHistory();
          showToast('Bulk run complete', 'info');
        });

        es.addEventListener('error_event', (e) => {
          const d = JSON.parse(e.data);
          showToast(d.message || 'Bulk run error', 'error');
        });

        es.onerror = () => {
          this.bulkRunning = false;
          es.close();
          this._bulkEventSource = null;
          showToast('Lost connection to bulk run stream', 'error');
        };
      } catch (err) {
        this.bulkRunning = false;
        showToast(err.message, 'error');
      }
    },

    async cancelBulkRun() {
      if (!this.bulkCurrentId || !this.currentAgent) return;
      try {
        await api(`/api/agents/${encodeURIComponent(this.currentAgent)}/bulk-run/${this.bulkCurrentId}/cancel`, 'POST');
        showToast('Bulk run cancelled', 'info');
      } catch (err) {
        showToast(err.message, 'error');
      }
    },

    async loadBulkHistory() {
      if (!this.currentAgent) return;
      try {
        const data = await api(`/api/agents/${encodeURIComponent(this.currentAgent)}/bulk-runs`);
        this.bulkHistory = data;
        setTimeout(() => { if (typeof lucide !== 'undefined') lucide.createIcons(); }, 50);
      } catch (err) {
        console.warn('Failed to load bulk history:', err);
      }
    },

    formatBulkConfig(run) {
      if (!run.config_matrix) return '';
      const parts = [];
      for (const cfg of run.config_matrix) {
        if (cfg.temperature !== undefined) parts.push(`t=${cfg.temperature}`);
        if (cfg.reasoning_effort !== undefined) parts.push(`re=${cfg.reasoning_effort}`);
      }
      return parts.join(', ');
    },

    async viewBulkRun(id) {
      if (!this.currentAgent) return;
      try {
        const data = await api(`/api/agents/${encodeURIComponent(this.currentAgent)}/bulk-runs/${id}`);
        this.bulkCurrentId = id;
        this.bulkViewedRun = data;
        this.bulkResults = data.runs || [];
        this.bulkTotalRuns = data.total_runs || this.bulkResults.length;
        this.bulkCompleted = this.bulkResults.length;
        this.bulkSubView = 'detail';
        this.bulkRunning = false;
        setTimeout(() => { if (typeof lucide !== 'undefined') lucide.createIcons(); }, 50);
      } catch (err) {
        showToast(err.message, 'error');
      }
    },

    async deleteBulkRun(id) {
      if (!this.currentAgent) return;
      const ok = await this.showConfirm('Delete this bulk run permanently? This will also remove all its run logs.', true);
      if (!ok) return;
      try {
        await api(`/api/agents/${encodeURIComponent(this.currentAgent)}/bulk-runs/${id}`, 'DELETE');
        this.bulkHistory = this.bulkHistory.filter(r => r.id !== id);
        // If the deleted run is currently being viewed, return to history list
        if (this.bulkCurrentId === id) {
          this.bulkCurrentId = null;
          this.bulkViewedRun = null;
          this.bulkResults = [];
          this.bulkSubView = 'history';
        }
        showToast('Bulk run deleted', 'success');
      } catch (err) {
        showToast('Delete failed: ' + err.message, 'error');
      }
    },

    startFreshBulkRun() {
      // Clear previous results and return to a fully-expanded New Run form
      this.bulkResults = [];
      this.bulkCompleted = 0;
      this.bulkTotalRuns = 0;
      this.bulkRunning = false;
      this.bulkViewedRun = null;
      this.bulkSubView = 'new';
      this.bulkConfigCollapsed = false;
      if (this._bulkEventSource) {
        this._bulkEventSource.close();
        this._bulkEventSource = null;
      }
    },

    rerunBulkRun() {
      const run = this.bulkViewedRun;
      if (!run) return;
      const cm = run.config_matrix || {};
      this.bulkSelectedTests = [...(run.test_cases || [])];
      this.bulkSelectedModels = [...(cm.models || [])];
      this.bulkSelectedTemps = [...(cm.temperatures || [])];
      this.bulkReasoningEfforts = [...(cm.reasoning_efforts || [])];
      this.bulkIncludeEval = run.include_eval || false;
      this.bulkJudgeModel = this._canonicalModel(run.judge_model || '');
      this.bulkResults = [];
      this.bulkCompleted = 0;
      this.bulkTotalRuns = 0;
      this.bulkRunning = false;
      this.bulkSubView = 'new';
      this.bulkConfigExpanded = false;
      this.bulkViewedRun = null;
    },

    exportBulkRun(format, id) {
      const bulkId = id || this.bulkCurrentId;
      if (!bulkId || !this.currentAgent) return;
      const url = BASE + `/api/agents/${encodeURIComponent(this.currentAgent)}/bulk-runs/${bulkId}/export?format=${format}`;
      window.open(url, '_blank');
      this.bulkExportOpen = false;
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
