/* Support chat client: SSE stream + composer for user/admin/guest. */
(function(){
    var root = document.getElementById('support-root');
    if (!root) return;

    var ticketId = root.dataset.ticketId || '';
    var token = root.dataset.token || '';
    var isGuest = root.dataset.isGuest === '1';
    var isAdmin = root.dataset.isAdmin === '1';
    var status = root.dataset.status || 'open';
    var csrf = root.dataset.csrf || '';

    var thread = document.getElementById('chat-thread');
    var input = document.getElementById('chat-input');
    var sendBtn = document.getElementById('chat-send-btn');
    var statusEl = document.getElementById('chat-status');
    var closeBtn = document.getElementById('support-close-btn');

    function escapeHtml(s){
        return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }
    function renderMessage(m){
        if (!thread) return;
        if (m.sender_kind === 'system') {
            var d = document.createElement('div');
            d.className = 'support-system';
            d.textContent = m.body;
            thread.appendChild(d);
            scrollBottom();
            return;
        }
        var isMine = (isAdmin && m.sender_kind === 'admin') ||
                     (!isAdmin && !isGuest && m.sender_kind === 'user') ||
                     (isGuest && m.sender_kind === 'guest');
        var bubbleSide = isMine ? 'user' : 'assistant';
        var avatarHtml;
        if (m.sender_kind === 'admin') avatarHtml = '<i class="fa-solid fa-headset"></i>';
        else if (m.sender_kind === 'guest') avatarHtml = '<i class="fa-solid fa-user"></i>';
        else avatarHtml = escapeHtml((m.sender_name||'?').slice(0,1).toUpperCase());

        var div = document.createElement('div');
        div.className = 'chat-msg ' + bubbleSide;
        div.innerHTML = '<div class="chat-avatar">'+avatarHtml+'</div>' +
                        '<div class="chat-bubble">'+escapeHtml(m.body).replace(/\n/g,'<br>')+'</div>';
        thread.appendChild(div);
        scrollBottom();
    }
    function scrollBottom(){
        if (thread) thread.scrollTop = thread.scrollHeight;
    }

    // ---- SSE
    var sseUrl = isGuest
        ? '/support/t/' + encodeURIComponent(token) + '/stream/'
        : '/assistant/support/t/' + ticketId + '/stream/';

    var seenIds = new Set();
    Array.prototype.slice.call(document.querySelectorAll('#chat-thread [data-msg-id]'))
        .forEach(function(el){ seenIds.add(parseInt(el.dataset.msgId,10)); });

    function startSSE(){
        if (status === 'closed') return;
        var es;
        try { es = new EventSource(sseUrl); } catch (e) { return; }
        es.addEventListener('message', function(ev){
            try {
                var m = JSON.parse(ev.data);
                if (seenIds.has(m.id)) return;
                seenIds.add(m.id);
                renderMessage(m);
            } catch (e) {}
        });
        es.addEventListener('status', function(ev){
            try {
                var d = JSON.parse(ev.data);
                if (d.status === 'closed') {
                    status = 'closed';
                    if (statusEl) statusEl.textContent = 'Тикет закрыт. Перезагрузите страницу.';
                    if (input) input.disabled = true;
                    if (sendBtn) sendBtn.disabled = true;
                }
            } catch (e) {}
            es.close();
        });
        es.onerror = function(){
            es.close();
            setTimeout(startSSE, 2000);
        };
    }
    startSSE();
    scrollBottom();

    // ---- Send
    function setBusy(b){
        if (sendBtn) sendBtn.disabled = b;
        if (input) input.disabled = b;
    }
    function send(){
        if (!input) return;
        var content = (input.value || '').trim();
        if (!content) return;
        setBusy(true);
        if (statusEl) statusEl.textContent = 'Отправка…';
        var url = isGuest
            ? '/support/t/' + encodeURIComponent(token) + '/send/'
            : '/assistant/support/t/' + ticketId + '/send/';
        fetch(url, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
            body: JSON.stringify({ content: content })
        }).then(function(r){
            if (!r.ok) {
                return r.json().then(function(d){ throw d; }).catch(function(){ throw {error: 'http_' + r.status}; });
            }
            return r.json();
        }).then(function(){
            input.value = '';
            input.style.height = '';
            if (statusEl) statusEl.textContent = '';
        }).catch(function(err){
            if (statusEl) statusEl.textContent = (err && err.error) ? ('Ошибка: ' + err.error) : 'Ошибка отправки';
        }).finally(function(){ setBusy(false); input && input.focus(); });
    }

    if (sendBtn) sendBtn.addEventListener('click', send);
    if (input) {
        input.addEventListener('keydown', function(e){
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                send();
            }
        });
        input.addEventListener('input', function(){
            input.style.height = 'auto';
            input.style.height = Math.min(160, input.scrollHeight) + 'px';
        });
    }

    if (closeBtn) {
        closeBtn.addEventListener('click', function(){
            if (!confirm('Закрыть тикет? Пользователь не сможет писать.')) return;
            fetch('/assistant/support/t/' + ticketId + '/close/', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'X-CSRFToken': csrf, 'X-Requested-With': 'XMLHttpRequest' },
            }).then(function(){ location.reload(); });
        });
    }
})();
