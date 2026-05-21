/* Support pane inside the assistant FAB drawer. Uses window.SupportUI for
   message rendering, typing/connection indicators. Reuses
   /assistant/support/* JSON endpoints + SSE stream. */
(function () {
    'use strict';

    var drawer = document.getElementById('assistant-drawer');
    if (!drawer) return;

    var pane = drawer.querySelector('.drawer-pane[data-pane="support"]');
    var aiPane = drawer.querySelector('.drawer-pane[data-pane="ai"]');
    var tabs = drawer.querySelectorAll('.drawer-tab');
    var fabBadge = document.getElementById('supportFabBadge');
    var drawerBadge = document.getElementById('drawerSupportBadge');
    if (!pane || !window.SupportUI) return;

    var SU = window.SupportUI;
    var csrf = pane.dataset.csrf || '';
    var isAdmin = pane.dataset.isAdmin === '1';
    var viewerKind = pane.dataset.viewerKind || 'user';
    var userInitial = pane.dataset.userInitial || '?';
    var userAvatar = pane.dataset.userAvatar || '';

    SU.init(pane, {viewerKind: viewerKind, mineAvatarUrl: userAvatar, mineInitial: userInitial});

    // ── Element refs
    var viewList = pane.querySelector('[data-view="list"]');
    var viewNew = pane.querySelector('[data-view="new"]');
    var viewThread = pane.querySelector('[data-view="thread"]');

    var listEl = pane.querySelector('[data-support-list]');
    var threadList = pane.querySelector('[data-thread-list]');
    var threadSubject = pane.querySelector('[data-thread-subject]');
    var threadSub = pane.querySelector('[data-thread-sub]');
    var threadInput = pane.querySelector('[data-thread-input]');
    var threadSendBtn = pane.querySelector('[data-thread-send]');
    var threadStatus = pane.querySelector('[data-thread-status]');

    var menuWrap = pane.querySelector('[data-thread-menu-wrap]');
    var menuEl = pane.querySelector('[data-thread-menu]');

    var newSubject = pane.querySelector('[data-new-subject]');
    var newBody = pane.querySelector('[data-new-body]');
    var newError = pane.querySelector('[data-new-error]');
    var newCounter = pane.querySelector('[data-new-counter]');

    var typingLabel = pane.querySelector('.su-typing-label');

    // ── State
    var currentTicket = null;
    var currentSSE = null;
    var seenIds = new Set();
    var loadedOnce = false;
    var sseFirstOpen = false;
    var typingTimer = null;
    var typingActive = false;
    var typingResetTimer = null;
    var lastTypingKind = null;
    var typingClearTimer = null;

    function showView(view) {
        viewList.hidden = (view !== 'list');
        viewNew.hidden = (view !== 'new');
        viewThread.hidden = (view !== 'thread');
    }

    // ── Tabs (AI / Support)
    tabs.forEach(function (tab) {
        tab.addEventListener('click', function () {
            var target = tab.dataset.pane;
            tabs.forEach(function (t) { t.classList.toggle('active', t === tab); });
            aiPane.hidden = (target !== 'ai');
            pane.hidden = (target !== 'support');
            var clr = drawer.querySelector('[data-chat-clear]');
            if (clr) clr.style.display = (target === 'ai') ? '' : 'none';
            if (target === 'support') {
                if (!loadedOnce) { loadedOnce = true; loadList(); }
            } else {
                closeStream();
                stopTyping();
            }
        });
    });

    // ── Badges
    function updateBadges(n) {
        function set(badge) {
            if (!badge) return;
            if (n > 0) {
                badge.textContent = n > 99 ? '99+' : String(n);
                badge.style.display = '';
            } else {
                badge.style.display = 'none';
            }
        }
        set(drawerBadge);
        set(fabBadge);
    }

    // ── List
    function loadList() {
        fetch('/assistant/support/api/list/', { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d) { renderListError(); return; }
                renderList(d);
            }).catch(renderListError);
    }
    function renderListError() {
        listEl.innerHTML = '<div class="su-list-empty"><div class="su-list-empty-icon"><i class="fa-solid fa-triangle-exclamation"></i></div>Не удалось загрузить</div>';
    }
    function renderList(d) {
        updateBadges(d.unread_count || 0);
        var newBtn = pane.querySelector('[data-action="new-ticket"]');
        if (newBtn) newBtn.style.display = d.is_admin ? 'none' : '';
        var titleEl = pane.querySelector('.su-list-title');
        if (titleEl) titleEl.textContent = d.is_admin ? 'Все обращения' : 'Мои обращения';

        if (!d.items || !d.items.length) {
            listEl.innerHTML = d.is_admin
                ? '<div class="su-list-empty"><div class="su-list-empty-icon"><i class="fa-solid fa-inbox"></i></div><h4>Тишина</h4>Открытых обращений нет.</div>'
                : '<div class="su-list-empty"><div class="su-list-empty-icon"><i class="fa-solid fa-life-ring"></i></div><h4>Обращений пока нет</h4>Нажмите «Новое», чтобы написать в поддержку.</div>';
            return;
        }

        listEl.innerHTML = '';
        d.items.forEach(function (t) {
            listEl.appendChild(renderListItem(t));
        });
    }
    function renderListItem(t) {
        var item = document.createElement('div');
        item.className = 'su-list-item';
        item.dataset.id = String(t.id);

        var av = document.createElement('div');
        av.className = 'su-list-item-avatar';
        if (t.last_sender_kind) av.dataset.role = t.last_sender_kind;
        if (t.last_sender_avatar_url) {
            av.innerHTML = '<img src="' + SU.esc(t.last_sender_avatar_url) + '" alt="">';
        } else if (t.last_sender_kind === 'admin') {
            av.innerHTML = '<i class="fa-solid fa-headset"></i>';
        } else if (t.last_sender_kind === 'guest') {
            av.innerHTML = '<i class="fa-solid fa-user"></i>';
        } else {
            av.textContent = (t.last_sender_name || t.author || '?').slice(0, 1).toUpperCase();
        }
        item.appendChild(av);

        var body = document.createElement('div');
        body.className = 'su-list-item-body';

        var row = document.createElement('div');
        row.className = 'su-list-item-row';
        var subj = document.createElement('div');
        subj.className = 'su-list-item-subject';
        subj.textContent = t.subject || '—';
        var time = document.createElement('div');
        time.className = 'su-list-item-time';
        time.textContent = SU.relativeTime(t.last_message_at);
        row.appendChild(subj);
        row.appendChild(time);
        body.appendChild(row);

        var prev = document.createElement('div');
        prev.className = 'su-list-item-preview';
        var who = t.last_sender_name ? (t.last_sender_name + ': ') : '';
        prev.innerHTML = (who ? '<span class="su-list-item-preview-author">' + SU.esc(who) + '</span>' : '') + SU.esc(t.last_body_preview || '');
        body.appendChild(prev);

        var meta = document.createElement('div');
        meta.className = 'su-list-item-meta';
        var pill = document.createElement('span');
        pill.className = 'su-status-pill';
        pill.dataset.status = t.status;
        pill.textContent = t.status === 'closed' ? 'закрыт' : 'open';
        meta.appendChild(pill);
        if (t.unread) {
            var dot = document.createElement('span');
            dot.className = 'su-unread-dot';
            meta.appendChild(dot);
        }
        body.appendChild(meta);

        item.appendChild(body);
        return item;
    }
    listEl.addEventListener('click', function (e) {
        var row = e.target.closest('.su-list-item');
        if (!row) return;
        openTicket(parseInt(row.dataset.id, 10));
    });

    // ── Thread
    function openTicket(id) {
        closeStream();
        stopTyping();
        currentTicket = null;
        seenIds = new Set();
        threadList.innerHTML = '';
        SU.setTyping(pane, null);
        SU.setConnection(pane, 'ok');
        SU.applyClosed(pane, false);
        showView('thread');
        if (menuEl) menuEl.hidden = true;

        fetch('/assistant/support/api/t/' + id + '/', { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : Promise.reject(r); })
            .then(function (d) {
                currentTicket = d;
                threadSubject.textContent = d.subject;
                threadSub.textContent = d.author + ' · ' + (d.status === 'closed' ? 'закрыт' : 'открыт');
                threadList.innerHTML = '';
                d.messages.forEach(function (m) {
                    seenIds.add(m.id);
                    if (m.sender_kind === 'system') SU.renderSystem(threadList, m);
                    else SU.renderMessage(threadList, m, {viewerKind: viewerKind, mineAvatarUrl: userAvatar, mineInitial: userInitial});
                });
                SU.applyClosed(pane, d.status === 'closed');
                if (menuWrap) menuWrap.hidden = !(d.can_close && d.status !== 'closed');
                scrollBottom();
                if (d.status !== 'closed') startStream(d.id);
                loadList();
            })
            .catch(function () {
                threadList.innerHTML = '<div class="su-list-empty"><div class="su-list-empty-icon"><i class="fa-solid fa-triangle-exclamation"></i></div>Не удалось открыть тикет</div>';
            });
    }

    function scrollBottom() {
        requestAnimationFrame(function () {
            threadList.scrollTop = threadList.scrollHeight;
        });
    }

    // ── SSE
    function startStream(id) {
        closeStream();
        sseFirstOpen = false;
        try { currentSSE = new EventSource('/assistant/support/t/' + id + '/stream/'); }
        catch (e) { return; }

        currentSSE.addEventListener('open', function () {
            sseFirstOpen = true;
            SU.setConnection(pane, 'ok');
        });
        currentSSE.addEventListener('message', function (ev) {
            try {
                var m = JSON.parse(ev.data);
                if (seenIds.has(m.id)) return;
                seenIds.add(m.id);
                SU.setConnection(pane, 'ok');
                if (m.sender_kind === 'system') SU.renderSystem(threadList, m);
                else SU.renderMessage(threadList, m, {animate: true, viewerKind: viewerKind, mineAvatarUrl: userAvatar, mineInitial: userInitial});
                scrollBottom();
                loadUnreadBadge();
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
                if (d.status === 'closed' && currentTicket) {
                    currentTicket.status = 'closed';
                    SU.applyClosed(pane, true);
                    if (menuWrap) menuWrap.hidden = true;
                    threadSub.textContent = (currentTicket.author || '') + ' · закрыт';
                }
            } catch (e) { /* ignore */ }
            closeStream();
        });
        currentSSE.onerror = function () {
            closeStream();
            SU.setConnection(pane, 'reconnecting');
            setTimeout(function () { if (currentTicket) startStream(currentTicket.id); }, 2000);
        };
    }
    function closeStream() {
        if (currentSSE) { try { currentSSE.close(); } catch (e) {} currentSSE = null; }
    }

    // ── Typing (incoming)
    function handleTypingEvent(d) {
        if (!d || !d.kind) return;
        if (d.active) {
            lastTypingKind = d.kind;
            var label = d.kind === 'admin' ? 'Поддержка печатает…'
                       : d.kind === 'guest' ? 'Гость печатает…'
                       : 'Печатает…';
            SU.setTyping(pane, label);
            if (typingClearTimer) clearTimeout(typingClearTimer);
            // Safety: hide after 6s with no refresh.
            typingClearTimer = setTimeout(function () { SU.setTyping(pane, null); }, 6000);
        } else {
            if (d.kind === lastTypingKind) {
                lastTypingKind = null;
                SU.setTyping(pane, null);
            }
        }
    }

    // ── Typing (outgoing)
    function postTyping(active) {
        if (!currentTicket) return;
        fetch('/assistant/support/t/' + currentTicket.id + '/typing/', {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
            body: JSON.stringify({ active: !!active }),
        }).catch(function () {});
    }
    function onInputTyping() {
        if (!currentTicket) return;
        var hasText = (threadInput.value || '').trim().length > 0;
        if (!hasText) {
            stopTyping();
            return;
        }
        if (!typingActive) {
            typingActive = true;
            postTyping(true);
        }
        if (typingTimer) clearTimeout(typingTimer);
        // Re-ping every 2s while user keeps typing (server TTL = 4s).
        typingTimer = setTimeout(function () {
            if (typingActive && (threadInput.value || '').trim()) {
                postTyping(true);
                onInputTyping();
            }
        }, 2000);
        if (typingResetTimer) clearTimeout(typingResetTimer);
        // If user stops typing for 3s — release.
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

    // ── Composer
    function sendThread() {
        if (!currentTicket) return;
        var content = (threadInput.value || '').trim();
        if (!content) return;
        threadSendBtn.disabled = true;
        threadInput.disabled = true;
        threadStatus.textContent = 'Отправка…';
        fetch('/assistant/support/t/' + currentTicket.id + '/send/', {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
            body: JSON.stringify({ content: content }),
        }).then(function (r) {
            if (!r.ok) return r.json().then(function (d) { throw d; }).catch(function () { throw {error: 'http_' + r.status}; });
            return r.json();
        }).then(function () {
            threadInput.value = '';
            threadInput.style.height = '';
            threadStatus.textContent = '';
            stopTyping();
        }).catch(function (err) {
            threadStatus.textContent = (err && err.error) ? ('Ошибка: ' + err.error) : 'Ошибка';
        }).finally(function () {
            threadSendBtn.disabled = false;
            threadInput.disabled = false;
            threadInput.focus();
        });
    }
    threadSendBtn.addEventListener('click', sendThread);
    threadInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendThread(); }
    });
    threadInput.addEventListener('input', function () {
        threadInput.style.height = 'auto';
        threadInput.style.height = Math.min(140, threadInput.scrollHeight) + 'px';
        onInputTyping();
    });

    // ── Three-dot menu (admin only)
    pane.querySelector('[data-action="toggle-menu"]')?.addEventListener('click', function (e) {
        e.stopPropagation();
        if (!menuEl) return;
        menuEl.hidden = !menuEl.hidden;
    });
    document.addEventListener('click', function (e) {
        if (!menuEl || menuEl.hidden) return;
        if (!menuEl.contains(e.target) && !e.target.closest('[data-action="toggle-menu"]')) {
            menuEl.hidden = true;
        }
    });

    pane.querySelector('[data-action="close-ticket"]')?.addEventListener('click', function () {
        if (!currentTicket) return;
        if (!confirm('Закрыть тикет? Пользователь не сможет писать.')) return;
        fetch('/assistant/support/t/' + currentTicket.id + '/close/', {
            method: 'POST', credentials: 'same-origin',
            headers: { 'X-CSRFToken': csrf },
        }).then(function () {
            openTicket(currentTicket.id);
        });
    });

    // ── New ticket
    pane.querySelector('[data-action="new-ticket"]')?.addEventListener('click', function () {
        newSubject.value = '';
        newBody.value = '';
        if (newCounter) newCounter.textContent = '0 / 5000';
        newError.hidden = true;
        showView('new');
        setTimeout(function () { newSubject.focus(); }, 50);
    });
    pane.querySelectorAll('[data-action="back-to-list"]').forEach(function (btn) {
        btn.addEventListener('click', function () {
            closeStream();
            stopTyping();
            SU.setTyping(pane, null);
            currentTicket = null;
            showView('list');
            loadList();
        });
    });
    if (newBody && newCounter) {
        newBody.addEventListener('input', function () {
            newCounter.textContent = (newBody.value || '').length + ' / 5000';
        });
    }
    pane.querySelector('[data-action="submit-new"]')?.addEventListener('click', function () {
        var subj = (newSubject.value || '').trim();
        var bod = (newBody.value || '').trim();
        if (!subj || !bod) {
            newError.textContent = 'Заполните тему и сообщение';
            newError.hidden = false;
            return;
        }
        newError.hidden = true;
        var btn = pane.querySelector('[data-action="submit-new"]');
        btn.disabled = true;
        fetch('/assistant/support/api/new/', {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf },
            body: JSON.stringify({ subject: subj, body: bod }),
        }).then(function (r) {
            if (!r.ok) return r.json().then(function (d) { throw d; }).catch(function () { throw {error: 'http_' + r.status}; });
            return r.json();
        }).then(function (d) {
            openTicket(d.ticket_id);
        }).catch(function (err) {
            newError.textContent = (err && err.error) ? ('Ошибка: ' + err.error) : 'Не удалось отправить';
            newError.hidden = false;
        }).finally(function () { btn.disabled = false; });
    });

    // ── Periodic unread polling
    function loadUnreadBadge() {
        fetch('/assistant/support/api/unread/', { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) { if (d) updateBadges(d.count || 0); })
            .catch(function () {});
    }
    loadUnreadBadge();
    setInterval(loadUnreadBadge, 60000);
    document.addEventListener('visibilitychange', function () { if (!document.hidden) loadUnreadBadge(); });
})();
