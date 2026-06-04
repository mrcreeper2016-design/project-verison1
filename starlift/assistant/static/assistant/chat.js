(function () {
    const root = document.getElementById('chat-root');
    if (!root) return;

    const conversationId = root.dataset.conversationId;
    const csrf = root.dataset.csrf;
    const userInitial = root.dataset.userInitial || '?';
    const thread = document.getElementById('chat-thread');
    const input = document.getElementById('chat-input');
    const sendBtn = document.getElementById('chat-send-btn');
    const status = document.getElementById('chat-status');

    function el(tag, cls, html) {
        const e = document.createElement(tag);
        if (cls) e.className = cls;
        if (html !== undefined) e.innerHTML = html;
        return e;
    }
    function escapeHtml(s) {
        return String(s || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }
    function scrollDown() {
        thread.scrollTop = thread.scrollHeight;
    }
    function hideEmpty() {
        const empty = thread.querySelector('.chat-empty');
        if (empty) empty.remove();
    }
    function linkifyMarkdownRefs(plainText) {
        const e = escapeHtml(plainText);
        return e
            .replace(/\[([^\]]+)\]\(#speaker-(\d+)\)/g,
                '<a class="chat-link chat-link-speaker" href="/speakers/#open-speaker-$2" data-speaker-id="$2">$1</a>')
            .replace(/\[([^\]]+)\]\(#event-(\d+)\)/g,
                '<a class="chat-link chat-link-event" href="/events/#event-$2" data-event-id="$2">$1</a>');
    }
    function finalizeBubble(bubble) {
        if (!bubble) return;
        const raw = bubble.textContent || '';
        if (raw.indexOf('](#') === -1) return;
        bubble.innerHTML = linkifyMarkdownRefs(raw);
    }

    function appendUser(text) {
        hideEmpty();
        const wrap = el('div', 'chat-msg user');
        wrap.appendChild(el('div', 'chat-avatar', escapeHtml(userInitial)));
        wrap.appendChild(el('div', 'chat-bubble', escapeHtml(text)));
        thread.appendChild(wrap);
        scrollDown();
    }

    function appendTyping() {
        const t = el('div', 'chat-typing');
        t.id = 'chat-typing-indicator';
        t.appendChild(el('span'));
        t.appendChild(el('span'));
        t.appendChild(el('span'));
        thread.appendChild(t);
        scrollDown();
    }
    function removeTyping() {
        const t = document.getElementById('chat-typing-indicator');
        if (t) t.remove();
    }

    function startAssistantMessage() {
        removeTyping();
        const wrap = el('div', 'chat-msg assistant');
        wrap.appendChild(el('div', 'chat-avatar', '<i class="fa-solid fa-robot"></i>'));
        const bubble = el('div', 'chat-bubble', '');
        wrap.appendChild(bubble);
        thread.appendChild(wrap);
        scrollDown();
        return bubble;
    }

    function appendToolChip(_name, _args) {
        // Tool chips are intentionally hidden from the UI.
        return null;
    }

    function appendError(reason) {
        removeTyping();
        const e = el('div', 'chat-error',
            `<i class="fa-solid fa-triangle-exclamation"></i> ${escapeHtml(reason)}`);
        thread.appendChild(e);
        scrollDown();
    }

    function setStatus(text) {
        if (status) status.textContent = text || '';
    }

    function unlockInput() {
        input.disabled = false;
        sendBtn.disabled = false;
        setStatus('');
        input.focus();
    }
    function lockInput() {
        input.disabled = true;
        sendBtn.disabled = true;
    }

    function openStream() {
        appendTyping();
        setStatus('Думаю…');
        let assistantBubble = null;
        const es = new EventSource(`/assistant/c/${conversationId}/stream/`);

        es.addEventListener('delta', (e) => {
            if (!assistantBubble) {
                removeTyping();
                assistantBubble = startAssistantMessage();
            }
            const data = JSON.parse(e.data);
            assistantBubble.textContent += data.text;
            scrollDown();
        });
        // Tool calls happen behind the scenes — keep the typing indicator
        // and just update the subtle status text below the composer.
        es.addEventListener('tool_start', () => {
            setStatus('Ищу данные…');
        });
        es.addEventListener('tool_end', () => {
            setStatus('Думаю…');
        });
        es.addEventListener('error', (e) => {
            removeTyping();
            const map = {
                provider_error: 'Ошибка GigaChat. Проверьте ключ и модель в .env.',
                budget_exceeded: 'Превышен лимит токенов.',
                max_tools_exceeded: 'Превышен лимит итераций.',
                unknown_tool: 'Ассистент попросил неизвестный инструмент.',
            };
            try {
                const data = JSON.parse(e.data || '{}');
                appendError(map[data.reason] || data.reason || 'неизвестная ошибка');
            } catch {
                appendError('соединение прервано');
            }
            es.close();
            unlockInput();
        });
        es.addEventListener('done', () => {
            removeTyping();
            es.close();
            finalizeBubble(assistantTextEl);
            unlockInput();
        });
    }

    function autoresize() {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 160) + 'px';
    }

    async function send() {
        const text = (input.value || '').trim();
        if (!text) return;
        input.value = '';
        autoresize();
        lockInput();
        appendUser(text);

        try {
            const resp = await fetch(`/assistant/c/${conversationId}/send/`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
                credentials: 'same-origin',
                body: JSON.stringify({ content: text }),
            });
            if (!resp.ok) {
                const data = await resp.json().catch(() => ({ error: 'unknown' }));
                const map = {
                    rate_limited: 'превышен лимит сообщений, подождите немного',
                    empty: 'пустой запрос',
                };
                appendError(map[data.error] || data.error || 'не удалось отправить');
                unlockInput();
                return;
            }
        } catch (err) {
            appendError('сеть недоступна');
            unlockInput();
            return;
        }
        openStream();
    }

    sendBtn.addEventListener('click', send);
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            send();
        }
    });
    input.addEventListener('input', autoresize);

    document.querySelectorAll('.chat-empty-hint').forEach(btn => {
        btn.addEventListener('click', () => {
            input.value = btn.dataset.prompt;
            autoresize();
            send();
        });
    });

    if (root.dataset.autostart === '1') {
        lockInput();
        openStream();
    } else {
        input.focus();
    }

    // Linkify any pre-rendered assistant bubbles (chat detail page renders
    // history server-side and may contain stored [Name](#speaker-N) refs).
    document.querySelectorAll('.chat-msg.assistant .chat-bubble').forEach(finalizeBubble);

    // ── Sidebar: delete conversation ──────────────────────────────────────
    document.querySelectorAll('.chat-sidebar-delete').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.preventDefault();
            e.stopPropagation();
            const convId = btn.dataset.convId;
            if (!convId) return;
            if (!confirm('Удалить эту беседу безвозвратно?')) return;
            btn.disabled = true;
            try {
                const resp = await fetch(`/assistant/conversations/${convId}/delete/`, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrf, 'Content-Type': 'application/json' },
                    credentials: 'same-origin',
                });
                if (!resp.ok) {
                    btn.disabled = false;
                    return;
                }
                // If we just deleted the currently-open conversation,
                // bounce to /assistant/ which will create or reuse one.
                if (convId === conversationId) {
                    window.location.href = '/assistant/';
                    return;
                }
                const row = btn.closest('.chat-sidebar-row');
                if (row) row.remove();
            } catch (err) {
                btn.disabled = false;
            }
        });
    });
})();
