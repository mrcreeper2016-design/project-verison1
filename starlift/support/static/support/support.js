/* Support page client (full /assistant/support/ + guest /support/t/<token>/).
   Hydrates from a JSON <script type="application/json"> bootstrap then
   streams updates via SSE. Uses window.SupportUI for rendering. */
(function () {
    'use strict';

    var root = document.querySelector('.support-ui[data-status]');
    if (!root || !window.SupportUI) return;

    var SU = window.SupportUI;
    var isGuest = root.dataset.isGuest === '1';
    var isAdmin = root.dataset.isAdmin === '1';
    var viewerKind = root.dataset.viewerKind || (isGuest ? 'guest' : (isAdmin ? 'admin' : 'user'));
    var ticketId = root.dataset.ticketId || '';
    var token = root.dataset.token || '';
    var status = root.dataset.status || 'open';
    var csrf = root.dataset.csrf || '';
    var userInitial = root.dataset.userInitial || '?';
    var userAvatar = root.dataset.userAvatar || '';

    SU.init(root, {viewerKind: viewerKind, mineAvatarUrl: userAvatar, mineInitial: userInitial});

    var threadList = root.querySelector('[data-thread-list]');
    var threadInput = root.querySelector('[data-thread-input]');
    var threadSendBtn = root.querySelector('[data-thread-send]');
    var threadStatus = root.querySelector('[data-thread-status]');
    var menuEl = root.querySelector('[data-thread-menu]');

    var seenIds = new Set();
    var currentSSE = null;
    var typingTimer = null;
    var typingActive = false;
    var typingResetTimer = null;
    var typingClearTimer = null;
    var lastTypingKind = null;

    function scrollBottom() {
        requestAnimationFrame(function () { threadList.scrollTop = threadList.scrollHeight; });
    }

    // ── Hydrate from bootstrap JSON
    var bootstrap = document.getElementById('page-bootstrap-messages');
    if (bootstrap) {
        try {
            var data = JSON.parse(bootstrap.textContent || '[]');
            data.forEach(function (m) {
                seenIds.add(m.id);
                if (m.sender_kind === 'system') SU.renderSystem(threadList, m);
                else SU.renderMessage(threadList, m, {viewerKind: viewerKind, mineAvatarUrl: userAvatar, mineInitial: userInitial});
            });
            scrollBottom();
        } catch (e) { /* ignore */ }
    }

    // ── URLs
    var streamUrl = isGuest
        ? '/support/t/' + encodeURIComponent(token) + '/stream/'
        : '/assistant/support/t/' + ticketId + '/stream/';
    var sendUrl = isGuest
        ? '/support/t/' + encodeURIComponent(token) + '/send/'
        : '/assistant/support/t/' + ticketId + '/send/';
    var typingUrl = isGuest
        ? '/support/t/' + encodeURIComponent(token) + '/typing/'
        : '/assistant/support/t/' + ticketId + '/typing/';
    var closeUrl = isAdmin && !isGuest
        ? '/assistant/support/t/' + ticketId + '/close/'
        : null;
    var deleteUrl = isAdmin && !isGuest
        ? '/assistant/support/t/' + ticketId + '/delete/'
        : null;

    // ── SSE
    function startSSE() {
        if (status === 'closed') return;
        closeSSE();
        try { currentSSE = new EventSource(streamUrl); }
        catch (e) { return; }

        currentSSE.addEventListener('open', function () { SU.setConnection(root, 'ok'); });
        currentSSE.addEventListener('message', function (ev) {
            try {
                var m = JSON.parse(ev.data);
                if (seenIds.has(m.id)) return;
                seenIds.add(m.id);
                SU.setConnection(root, 'ok');
                if (m.sender_kind === 'system') SU.renderSystem(threadList, m);
                else SU.renderMessage(threadList, m, {animate: true, viewerKind: viewerKind, mineAvatarUrl: userAvatar, mineInitial: userInitial});
                scrollBottom();
            } catch (e) { /* ignore */ }
        });
        currentSSE.addEventListener('typing', function (ev) {
            try {
                var d = JSON.parse(ev.data);
                handleTypingEvent(d);
            } catch (e) { /* ignore */ }
        });
        currentSSE.addEventListener('status', function (ev) {
            try {
                var d = JSON.parse(ev.data);
                if (d.status === 'closed') {
                    status = 'closed';
                    SU.applyClosed(root, true);
                    if (threadStatus) threadStatus.textContent = '';
                }
            } catch (e) { /* ignore */ }
            closeSSE();
        });
        currentSSE.onerror = function () {
            closeSSE();
            SU.setConnection(root, 'reconnecting');
            setTimeout(function () { if (status !== 'closed') startSSE(); }, 2000);
        };
    }
    function closeSSE() {
        if (currentSSE) { try { currentSSE.close(); } catch (e) {} currentSSE = null; }
    }
    startSSE();

    // ── Typing in
    function handleTypingEvent(d) {
        if (!d || !d.kind) return;
        if (d.active) {
            lastTypingKind = d.kind;
            var label = d.kind === 'admin' ? 'Поддержка печатает…'
                       : d.kind === 'guest' ? 'Гость печатает…'
                       : 'Печатает…';
            SU.setTyping(root, label);
            if (typingClearTimer) clearTimeout(typingClearTimer);
            typingClearTimer = setTimeout(function () { SU.setTyping(root, null); }, 6000);
        } else {
            if (d.kind === lastTypingKind) {
                lastTypingKind = null;
                SU.setTyping(root, null);
            }
        }
    }

    // ── Typing out
    function postTyping(active) {
        fetch(typingUrl, {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
            body: JSON.stringify({ active: !!active }),
        }).catch(function () {});
    }
    function onInputTyping() {
        var hasText = (threadInput.value || '').trim().length > 0;
        if (!hasText) { stopTyping(); return; }
        if (!typingActive) { typingActive = true; postTyping(true); }
        if (typingTimer) clearTimeout(typingTimer);
        typingTimer = setTimeout(function () {
            if (typingActive && (threadInput.value || '').trim()) {
                postTyping(true);
                onInputTyping();
            }
        }, 2000);
        if (typingResetTimer) clearTimeout(typingResetTimer);
        typingResetTimer = setTimeout(stopTyping, 3000);
    }
    function stopTyping() {
        if (typingTimer) { clearTimeout(typingTimer); typingTimer = null; }
        if (typingResetTimer) { clearTimeout(typingResetTimer); typingResetTimer = null; }
        if (typingActive) {
            typingActive = false;
            postTyping(false);
        }
    }

    // ── Send
    function setBusy(b) {
        if (threadSendBtn) threadSendBtn.disabled = b;
        if (threadInput) threadInput.disabled = b;
    }
    function send() {
        if (!threadInput) return;
        var content = (threadInput.value || '').trim();
        if (!content) return;
        setBusy(true);
        if (threadStatus) threadStatus.textContent = 'Отправка…';
        fetch(sendUrl, {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
            body: JSON.stringify({ content: content }),
        }).then(function (r) {
            if (!r.ok) return r.json().then(function (d) { throw d; }).catch(function () { throw {error: 'http_' + r.status}; });
            return r.json();
        }).then(function () {
            threadInput.value = '';
            threadInput.style.height = '';
            if (threadStatus) threadStatus.textContent = '';
            stopTyping();
        }).catch(function (err) {
            if (threadStatus) threadStatus.textContent = (err && err.error) ? ('Ошибка: ' + err.error) : 'Ошибка отправки';
        }).finally(function () {
            setBusy(false);
            threadInput.focus();
        });
    }

    if (threadSendBtn) threadSendBtn.addEventListener('click', send);
    if (threadInput) {
        threadInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
        });
        threadInput.addEventListener('input', function () {
            threadInput.style.height = 'auto';
            threadInput.style.height = Math.min(140, threadInput.scrollHeight) + 'px';
            onInputTyping();
        });
    }

    // ── Three-dot menu (admin only, non-guest)
    var menuToggle = root.querySelector('[data-action="toggle-menu"]');
    if (menuToggle && menuEl) {
        menuToggle.addEventListener('click', function (e) {
            e.stopPropagation();
            menuEl.hidden = !menuEl.hidden;
        });
        document.addEventListener('click', function (e) {
            if (menuEl.hidden) return;
            if (!menuEl.contains(e.target) && !e.target.closest('[data-action="toggle-menu"]')) {
                menuEl.hidden = true;
            }
        });
    }
    var closeBtn = root.querySelector('[data-action="close-ticket"]');
    var deleteBtn = root.querySelector('[data-action="delete-ticket"]');

    function syncAdminMenu() {
        if (!isAdmin || isGuest) return;
        var closed = status === 'closed';
        if (closeBtn) closeBtn.hidden = closed;
        if (deleteBtn) deleteBtn.hidden = !closed;
    }
    syncAdminMenu();

    if (closeBtn && closeUrl) {
        closeBtn.addEventListener('click', function () {
            if (!confirm('Закрыть тикет?')) return;
            fetch(closeUrl, {
                method: 'POST', credentials: 'same-origin',
                headers: { 'X-CSRFToken': csrf },
            }).then(function () { location.reload(); });
        });
    }

    if (deleteBtn && deleteUrl) {
        deleteBtn.addEventListener('click', function () {
            if (!confirm('Удалить обращение безвозвратно? Все сообщения будут стёрты.')) return;
            deleteBtn.disabled = true;
            fetch(deleteUrl, {
                method: 'POST', credentials: 'same-origin',
                headers: { 'X-CSRFToken': csrf },
            }).then(function (r) {
                if (!r.ok) {
                    deleteBtn.disabled = false;
                    alert('Не удалось удалить тикет');
                    return;
                }
                // После удаления возвращаемся к списку обращений админа.
                window.location.href = '/assistant/support/';
            }).catch(function () {
                deleteBtn.disabled = false;
                alert('Сеть недоступна');
            });
        });
    }
})();
