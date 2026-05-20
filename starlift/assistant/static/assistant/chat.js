(function () {
    const root = document.getElementById('chat-root');
    if (!root) return;
    const conversationId = root.dataset.conversationId;
    const csrf = root.dataset.csrf;
    const thread = document.getElementById('chat-thread');
    const input = document.getElementById('chat-input');
    const sendBtn = document.getElementById('chat-send-btn');

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

    function appendUser(text) {
        const wrap = el('div', 'chat-msg user');
        wrap.appendChild(el('div', 'chat-text', escapeHtml(text)));
        thread.appendChild(wrap);
        scrollDown();
    }

    function startAssistantMessage() {
        const wrap = el('div', 'chat-msg assistant');
        const txt = el('div', 'chat-text', '');
        wrap.appendChild(txt);
        thread.appendChild(wrap);
        scrollDown();
        return txt;
    }

    function appendToolChip(name, args) {
        const chip = el('div', 'chat-tool-chip loading',
            `<i class="fa-solid fa-magnifying-glass"></i> ${escapeHtml(name)}`);
        chip.title = JSON.stringify(args || {});
        thread.appendChild(chip);
        scrollDown();
        return chip;
    }

    function appendError(reason) {
        const e = el('div', 'chat-error',
            `<i class="fa-solid fa-triangle-exclamation"></i> Ошибка: ${escapeHtml(reason)}`);
        thread.appendChild(e);
        scrollDown();
    }

    function unlockInput() {
        input.disabled = false;
        sendBtn.disabled = false;
        input.focus();
    }

    function openStream() {
        const assistantTextEl = startAssistantMessage();
        const es = new EventSource(`/assistant/c/${conversationId}/stream/`);
        let currentChip = null;

        es.addEventListener('delta', (e) => {
            const data = JSON.parse(e.data);
            assistantTextEl.textContent += data.text;
            scrollDown();
        });
        es.addEventListener('tool_start', (e) => {
            const data = JSON.parse(e.data);
            currentChip = appendToolChip(data.name, data.args);
        });
        es.addEventListener('tool_end', (e) => {
            const data = JSON.parse(e.data);
            if (currentChip) {
                currentChip.classList.remove('loading');
                currentChip.innerHTML +=
                    data.summary ? ` · ${escapeHtml(data.summary)}` : '';
            }
        });
        es.addEventListener('error', (e) => {
            try {
                const data = JSON.parse(e.data || '{}');
                appendError(data.reason || 'stream error');
            } catch {
                appendError('соединение прервано');
            }
            es.close();
            unlockInput();
        });
        es.addEventListener('done', () => {
            es.close();
            unlockInput();
        });
    }

    async function send() {
        const text = (input.value || '').trim();
        if (!text) return;
        input.value = '';
        input.disabled = true;
        sendBtn.disabled = true;
        appendUser(text);

        const resp = await fetch(`/assistant/c/${conversationId}/send/`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
            credentials: 'same-origin',
            body: JSON.stringify({ content: text }),
        });
        if (!resp.ok) {
            const data = await resp.json().catch(() => ({ error: 'unknown' }));
            const map = { rate_limited: 'превышен лимит сообщений', empty: 'пустой запрос' };
            appendError(map[data.error] || data.error || 'send failed');
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

    if (root.dataset.autostart === '1') {
        openStream();
    } else {
        input.focus();
    }
})();
