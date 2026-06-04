// Reusable chat widget. Multiple instances can live on the same page
// (home embedded + FAB drawer); they share the user's single backend
// conversation and re-hydrate from /assistant/state/ when the other one
// posts a message.
//
// One instance owns one "root" element. Inside it, the widget looks for:
//   [data-chat-thread]    — message container (required)
//   [data-chat-input]     — textarea (required)
//   [data-chat-send]      — send button (required)
//   [data-chat-status]    — small status line (optional)
//   [data-chat-clear]     — clear/reset button (optional)
// And reads from the root's dataset:
//   csrf, userAvatar, userInitial
//
// The constructor wires events. Call .hydrate() to pull /state/ once.
window.AssistantChatWidget = class AssistantChatWidget {
    constructor(root) {
        this.root = root;
        this.thread = root.querySelector('[data-chat-thread]');
        this.input = root.querySelector('[data-chat-input]');
        this.sendBtn = root.querySelector('[data-chat-send]');
        this.statusEl = root.querySelector('[data-chat-status]');
        // Clear button lives in the card/drawer header — outside the chat root.
        // Look inside root first, then inside the closest containing card.
        this.clearBtn = root.querySelector('[data-chat-clear]')
            || (root.closest('.home-chat-card, .assistant-drawer') || root.parentElement)
                ?.querySelector('[data-chat-clear]')
            || null;
        if (!this.thread || !this.input || !this.sendBtn) return;

        this.csrf = root.dataset.csrf || '';
        this.userAvatar = (root.dataset.userAvatar || '').trim();
        this.userInitial = root.dataset.userInitial || '?';
        this.conversationId = '';
        this.hydrated = false;
        this.isStreaming = false;

        // Expose the instance on the root element so external code (e.g. the
        // home-page collapse toggle) can call .hydrate() lazily.
        root.__widget = this;

        this._wire();
        this._listenForCrossWidgetUpdates();
    }

    // ── helpers ───────────────────────────────────────────────────────────
    _el(tag, cls, html) {
        const e = document.createElement(tag);
        if (cls) e.className = cls;
        if (html !== undefined) e.innerHTML = html;
        return e;
    }
    _esc(s) {
        return String(s || '')
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }
    _userAvatarHtml() {
        return this.userAvatar
            ? `<img src="${this._esc(this.userAvatar)}" alt="${this._esc(this.userInitial)}">`
            : this._esc(this.userInitial);
    }
    _scrollDown() { this.thread.scrollTop = this.thread.scrollHeight; }
    _hideEmpty() {
        const e = this.thread.querySelector('.chat-empty');
        if (e) e.remove();
    }
    _setStatus(t) { if (this.statusEl) this.statusEl.textContent = t || ''; }
    _lock() { this.input.disabled = true; this.sendBtn.disabled = true; }
    _unlock() { this.input.disabled = false; this.sendBtn.disabled = false; this._setStatus(''); }
    _autoresize() {
        this.input.style.height = 'auto';
        this.input.style.height = Math.min(this.input.scrollHeight, 160) + 'px';
    }
    _linkifyRefs(plainText) {
        const e = this._esc(plainText);
        return e
            .replace(/\[([^\]]+)\]\(#speaker-(\d+)\)/g,
                '<a class="chat-link chat-link-speaker" href="/speakers/#open-speaker-$2">$1</a>')
            .replace(/\[([^\]]+)\]\(#event-(\d+)\)/g,
                '<a class="chat-link chat-link-event" href="/events/#event-$2">$1</a>');
    }
    _finalizeBubble(bubble) {
        if (!bubble) return;
        const raw = bubble.textContent || '';
        if (raw.indexOf('](#') === -1) return;
        bubble.innerHTML = this._linkifyRefs(raw);
    }

    // ── rendering ─────────────────────────────────────────────────────────
    _appendUser(text) {
        this._hideEmpty();
        const wrap = this._el('div', 'chat-msg user');
        wrap.appendChild(this._el('div', 'chat-avatar', this._userAvatarHtml()));
        wrap.appendChild(this._el('div', 'chat-bubble', this._esc(text)));
        this.thread.appendChild(wrap);
        this._scrollDown();
    }
    _appendAssistantBubble() {
        const wrap = this._el('div', 'chat-msg assistant');
        wrap.appendChild(this._el('div', 'chat-avatar', '<i class="fa-solid fa-robot"></i>'));
        const bubble = this._el('div', 'chat-bubble', '');
        wrap.appendChild(bubble);
        this.thread.appendChild(wrap);
        this._scrollDown();
        return bubble;
    }
    _appendTyping() {
        const t = this._el('div', 'chat-typing');
        t.dataset.typing = '1';
        t.appendChild(this._el('span'));
        t.appendChild(this._el('span'));
        t.appendChild(this._el('span'));
        this.thread.appendChild(t);
        this._scrollDown();
    }
    _removeTyping() {
        const t = this.thread.querySelector('[data-typing="1"]');
        if (t) t.remove();
    }
    _appendError(reason) {
        this._removeTyping();
        this.thread.appendChild(this._el('div', 'chat-error',
            `<i class="fa-solid fa-triangle-exclamation"></i> ${this._esc(reason)}`));
        this._scrollDown();
    }
    _appendStored(m) {
        if (m.role === 'user') {
            const wrap = this._el('div', 'chat-msg user');
            wrap.appendChild(this._el('div', 'chat-avatar', this._userAvatarHtml()));
            wrap.appendChild(this._el('div', 'chat-bubble', this._esc(m.content)));
            this.thread.appendChild(wrap);
        } else if (m.role === 'assistant' && (m.content || '').trim()) {
            const wrap = this._el('div', 'chat-msg assistant');
            wrap.appendChild(this._el('div', 'chat-avatar', '<i class="fa-solid fa-robot"></i>'));
            const bubble = this._el('div', 'chat-bubble', '');
            bubble.textContent = m.content || '';
            wrap.appendChild(bubble);
            this.thread.appendChild(wrap);
            this._finalizeBubble(bubble);
        }
        // tool — intentionally not rendered.
    }
    _renderEmptyHint() {
        this.thread.innerHTML = '';
        const wrap = this._el('div', 'chat-empty');
        wrap.innerHTML = `
            <div class="chat-empty-icon"><i class="fa-solid fa-wand-magic-sparkles"></i></div>
            <h3>Чем помочь?</h3>
            <p>Спросите про спикеров, события или NPS.</p>
            <div class="chat-empty-hints">
                <button type="button" class="chat-empty-hint" data-prompt="Покажи топ-5 спикеров">Топ-5 спикеров</button>
                <button type="button" class="chat-empty-hint" data-prompt="Ближайшие события">Ближайшие события</button>
                <button type="button" class="chat-empty-hint" data-prompt="Какой NPS за последние 30 дней?">NPS за месяц</button>
            </div>`;
        this.thread.appendChild(wrap);
        wrap.querySelectorAll('.chat-empty-hint').forEach(b => {
            b.addEventListener('click', () => {
                this.input.value = b.dataset.prompt;
                this._autoresize();
                this.send();
            });
        });
    }

    // ── public methods ───────────────────────────────────────────────────
    async hydrate() {
        try {
            const r = await fetch('/assistant/state/', { credentials: 'same-origin' });
            if (!r.ok) return;
            const data = await r.json();
            this.conversationId = data.conversation_id;
            this.thread.innerHTML = '';
            const msgs = data.messages || [];
            if (msgs.length === 0) this._renderEmptyHint();
            else msgs.forEach(m => this._appendStored(m));
            this._scrollDown();
            this.hydrated = true;
        } catch (_) { /* ignore */ }
    }

    async clear() {
        if (!confirm('Очистить беседу безвозвратно?')) return;
        this.clearBtn && (this.clearBtn.disabled = true);
        try {
            const r = await fetch('/assistant/clear/', {
                method: 'POST',
                headers: { 'X-CSRFToken': this.csrf, 'Content-Type': 'application/json' },
                credentials: 'same-origin',
            });
            if (!r.ok) return;
            const d = await r.json();
            this.conversationId = d.conversation_id;
            this._renderEmptyHint();
            this._broadcastUpdate();
        } finally {
            this.clearBtn && (this.clearBtn.disabled = false);
        }
    }

    async send(prefill) {
        if (typeof prefill === 'string') this.input.value = prefill;
        const text = (this.input.value || '').trim();
        if (!text || this.isStreaming) return;
        if (!this.conversationId) {
            await this.hydrate();
            if (!this.conversationId) return;
        }
        this.input.value = '';
        this._autoresize();
        this.isStreaming = true;
        this._lock();
        this._appendUser(text);

        try {
            const r = await fetch(`/assistant/c/${this.conversationId}/send/`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.csrf },
                credentials: 'same-origin',
                body: JSON.stringify({ content: text }),
            });
            if (!r.ok) {
                const d = await r.json().catch(() => ({ error: 'unknown' }));
                const map = {
                    rate_limited: 'превышен лимит сообщений, подождите немного',
                    empty: 'пустой запрос',
                };
                this._appendError(map[d.error] || d.error || 'не удалось отправить');
                this.isStreaming = false;
                this._unlock();
                return;
            }
        } catch (_) {
            this._appendError('сеть недоступна');
            this.isStreaming = false;
            this._unlock();
            return;
        }
        this._broadcastUpdate(); // tell siblings the user message was persisted
        this._openStream();
    }

    _openStream() {
        this._appendTyping();
        this._setStatus('Думаю…');
        let assistantBubble = null;
        const es = new EventSource(`/assistant/c/${this.conversationId}/stream/`);

        es.addEventListener('delta', (e) => {
            if (!assistantBubble) {
                this._removeTyping();
                assistantBubble = this._appendAssistantBubble();
            }
            const d = JSON.parse(e.data);
            assistantBubble.textContent += d.text;
            this._scrollDown();
        });
        es.addEventListener('tool_start', () => this._setStatus('Ищу данные…'));
        es.addEventListener('tool_end', () => this._setStatus('Думаю…'));
        es.addEventListener('error', (e) => {
            this._removeTyping();
            const map = {
                provider_error: 'Ошибка GigaChat. Проверьте ключ и модель в .env.',
                budget_exceeded: 'Превышен лимит токенов.',
                max_tools_exceeded: 'Превышен лимит итераций.',
                unknown_tool: 'Ассистент попросил неизвестный инструмент.',
            };
            try {
                const d = JSON.parse(e.data || '{}');
                this._appendError(map[d.reason] || d.reason || 'неизвестная ошибка');
            } catch {
                this._appendError('соединение прервано');
            }
            es.close();
            this.isStreaming = false;
            this._unlock();
        });
        es.addEventListener('done', () => {
            this._removeTyping();
            es.close();
            this._finalizeBubble(assistantBubble);
            this.isStreaming = false;
            this._unlock();
            this._broadcastUpdate();
        });
    }

    // ── cross-widget sync ────────────────────────────────────────────────
    _broadcastUpdate() {
        window.dispatchEvent(new CustomEvent('assistant:updated', { detail: { from: this } }));
    }
    _listenForCrossWidgetUpdates() {
        window.addEventListener('assistant:updated', (e) => {
            if (e.detail && e.detail.from === this) return;
            if (this.isStreaming) return;
            this.hydrate();
        });
    }

    _wire() {
        this.sendBtn.addEventListener('click', () => this.send());
        this.input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.send();
            }
        });
        this.input.addEventListener('input', () => this._autoresize());
        if (this.clearBtn) this.clearBtn.addEventListener('click', () => this.clear());
    }
};
