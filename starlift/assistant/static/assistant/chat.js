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

    function appendToolChip(name, args) {
        const chip = el('div', 'chat-tool-chip loading',
            `<i class="fa-solid fa-bolt"></i> ${escapeHtml(name)}`);
        chip.title = JSON.stringify(args || {});
        thread.appendChild(chip);
        scrollDown();
        return chip;
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
        let currentChip = null;

        es.addEventListener('delta', (e) => {
            if (!assistantBubble) {
                assistantBubble = startAssistantMessage();
            }
            const data = JSON.parse(e.data);
            assistantBubble.textContent += data.text;
            scrollDown();
        });
        es.addEventListener('tool_start', (e) => {
            removeTyping();
            const data = JSON.parse(e.data);
            currentChip = appendToolChip(data.name, data.args);
            setStatus(`Использую инструмент ${data.name}…`);
        });
        es.addEventListener('tool_end', (e) => {
            const data = JSON.parse(e.data);
            if (currentChip) {
                currentChip.classList.remove('loading');
                currentChip.classList.add('done');
                if (data.summary) {
                    currentChip.innerHTML += ` · ${escapeHtml(data.summary)}`;
                }
            }
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
})();
