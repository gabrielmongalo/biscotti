/**
 * biscotti — reusable Alpine.js components
 * ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 * Extracted UI-chrome state (dropdown open, highlight index, query)
 * into component-local x-data so the global store only holds
 * business state.
 *
 * Usage (future — not wired up yet):
 *   <div class="typeahead-wrap"
 *        x-data="typeahead({ items: () => ['a','b','c'], selected: () => current, onSelect: v => current = v })"
 *        @click.outside="close()">
 *     <input x-bind="input">
 *     <div x-bind="dropdown">
 *       <template x-for="(item, idx) in filtered" :key="item.key">
 *         <div class="typeahead-item" x-bind="option(idx)" x-text="item.label"></div>
 *       </template>
 *       <div x-bind="empty" x-text="'No results'"></div>
 *     </div>
 *   </div>
 */

// ================================================================
// Typeahead component
// ================================================================
function typeahead(config = {}) {
  const {
    items = () => [],
    selected = () => null,
    onSelect = () => {},
    placeholder = '',
    searchable = true,
    inputClass = '',
    inputStyle = '',
    emptyText = 'No results',
    fixed = false,
  } = config;

  return {
    // --- Local UI state ---
    open: false,
    highlightIdx: -1,
    query: '',

    // --- Fixed-position rect (stored on focus when fixed=true) ---
    _rect: null,

    // --- Normalize raw items into {key, label, value} objects ---
    _normalize(raw) {
      return raw.map(item => {
        if (typeof item === 'string') {
          return { key: item, label: item, value: item };
        }
        // Assume {key, label, value} — fill in missing fields
        return {
          key: item.key ?? item.value ?? item.label,
          label: item.label ?? item.value ?? item.key,
          value: item.value ?? item.key,
        };
      });
    },

    // --- Computed: all normalized items ---
    get allItems() {
      return this._normalize(items());
    },

    // --- Computed: filtered by query when searchable ---
    get filtered() {
      const all = this.allItems;
      if (!searchable || !this.query.trim()) return all;
      const q = this.query.trim().toLowerCase();
      return all.filter(item => item.label.toLowerCase().includes(q));
    },

    // --- Clamp highlight within bounds ---
    _clampHighlight() {
      const max = this.filtered.length - 1;
      if (this.highlightIdx > max) this.highlightIdx = max;
      if (this.highlightIdx < -1) this.highlightIdx = -1;
    },

    // --- Select a value and close ---
    _select(item) {
      onSelect(item.value);
      this.query = '';
      this.open = false;
      this.highlightIdx = -1;
    },

    // --- Bindable: input element ---
    get input() {
      const self = this;
      return {
        'x-ref': 'typeaheadInput',
        type: 'text',
        style: inputStyle,
        autocomplete: 'off',
        placeholder: placeholder,

        // For readonly (non-searchable) mode, show selected label
        ':value'() {
          if (searchable) return undefined;
          const sel = selected();
          if (!sel) return '';
          const match = self.allItems.find(i => i.value === sel);
          return match ? match.label : sel;
        },

        // For searchable mode, bind to query
        ...(searchable
          ? {
              'x-model': 'query',
              'x-init'() {
                // Sync query to current selection on init
                const sel = selected();
                if (sel) {
                  const match = self.allItems.find(i => i.value === sel);
                  self.query = match ? match.label : (sel || '');
                }
              },
            }
          : { readonly: true }),

        '@focus'(e) {
          self.open = true;
          self.highlightIdx = -1;
          if (fixed) {
            self._rect = e.target.getBoundingClientRect();
          }
        },

        '@input'() {
          self.open = true;
          self.highlightIdx = -1;
          if (fixed) {
            self._rect = this.$el.getBoundingClientRect();
          }
        },

        '@click'() {
          if (!searchable) {
            self.open = !self.open;
          }
          if (fixed && self.open) {
            self._rect = this.$el.getBoundingClientRect();
          }
        },

        '@keydown.arrow-down.prevent'() {
          self.highlightIdx = Math.min(
            self.highlightIdx + 1,
            self.filtered.length - 1
          );
        },

        '@keydown.arrow-up.prevent'() {
          self.highlightIdx = Math.max(self.highlightIdx - 1, 0);
        },

        '@keydown.enter.prevent'() {
          if (self.highlightIdx >= 0 && self.filtered[self.highlightIdx]) {
            self._select(self.filtered[self.highlightIdx]);
          }
        },

        '@keydown.escape'() {
          self.open = false;
          self.highlightIdx = -1;
        },

        '@keydown.tab'() {
          self.open = false;
          self.highlightIdx = -1;
        },
      };
    },

    // --- Close handler (put @click.outside on the wrapper, not the dropdown) ---
    close() {
      this.open = false;
      this.highlightIdx = -1;
    },

    // --- Bindable: dropdown container ---
    // Uses :class="{ open }" to match existing CSS (.typeahead-dropdown.open { display: block })
    get dropdown() {
      const self = this;
      const base = {
        ':class'() { return { open: self.open, 'fixed-dropdown': fixed }; },
      };

      if (fixed) {
        base[':style'] = function () {
          if (!self._rect) return '';
          return (
            'top:' + (self._rect.bottom + 4) + 'px;' +
            'left:' + self._rect.left + 'px;' +
            'width:' + self._rect.width + 'px;'
          );
        };
      }

      return base;
    },

    // --- Bindable: each option div ---
    option(idx) {
      const self = this;
      return {
        ':class'() {
          return { highlighted: idx === self.highlightIdx };
        },
        '@mousedown.prevent'() {
          const item = self.filtered[idx];
          if (item) self._select(item);
        },
        '@mouseenter'() {
          self.highlightIdx = idx;
        },
      };
    },

    // --- Bindable: empty-state div ---
    get empty() {
      const self = this;
      return {
        class: 'typeahead-empty',
        'x-show'() {
          return self.filtered.length === 0;
        },
      };
    },
  };
}
