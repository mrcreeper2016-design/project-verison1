/* Support UI — shared message renderer used by both the drawer and the
   full-page tab/guest views. Exposes window.SupportUI.

   Anatomy of a message:
     .su-msg[data-side="mine|theirs"][data-group="user:42"][data-msg-id="..."]
       .su-avatar               (img | <i> | letter)
       .su-bubble-wrap
         .su-meta-top           (sender name, only for theirs + group head)
         .su-bubble             (body)
         .su-meta-bottom        (time, only on group tail)

   System messages: .su-msg.su-msg--system spans full width, no avatar.

   Grouping: adjacent messages with the same `data-group` and <3 min gap form a
   group. Avatar+name shown only on first; time shown only on last. */
(function () {
    'use strict';

    var GROUP_GAP_MS = 3 * 60 * 1000;
    var MONTHS_RU = ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
    function el(tag, cls, html) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        if (html != null) e.innerHTML = html;
        return e;
    }
    function pad(n) { return n < 10 ? '0' + n : String(n); }
    function fmtTime(d) { return pad(d.getHours()) + ':' + pad(d.getMinutes()); }

    function relativeTime(iso) {
        if (!iso) return '';
        var d = new Date(iso);
        if (isNaN(d)) return '';
        var diff = Date.now() - d.getTime();
        var sec = Math.floor(diff / 1000);
        if (sec < 45) return 'только что';
        var min = Math.floor(sec / 60);
        if (min < 60) return min + ' мин';
        var hr = Math.floor(min / 60);
        if (hr < 24) return hr + ' ч';
        var now = new Date();
        var sameYear = d.getFullYear() === now.getFullYear();
        var label = d.getDate() + ' ' + MONTHS_RU[d.getMonth()];
        return sameYear ? label : (label + ' ' + d.getFullYear());
    }

    function groupKey(m) {
        if (m.sender_kind === 'system') return 'system';
        var who = m.sender_kind === 'guest'
            ? 'guest:' + (m.sender_name || '')
            : m.sender_kind + ':' + (m.sender_id || 0);
        return who;
    }

    // Determine if msg is "mine" relative to viewer.
    function isMine(m, viewerKind) {
        if (m.sender_kind === 'system') return false;
        if (viewerKind === 'admin') return m.sender_kind === 'admin';
        if (viewerKind === 'guest') return m.sender_kind === 'guest';
        return m.sender_kind === 'user';
    }

    function avatarHtml(m, opts) {
        // opts.mineAvatarUrl / mineInitial — for current viewer's own bubbles
        // (so user can see their photo without needing API to include it).
        if (m.sender_kind === 'system') return '';
        var url = m.sender_avatar_url || '';
        var initial = '';
        if (opts && opts.viewerKind && isMine(m, opts.viewerKind)) {
            if (!url && opts.mineAvatarUrl) url = opts.mineAvatarUrl;
            initial = (opts.mineInitial || '').slice(0, 1).toUpperCase();
        }
        if (!initial) {
            initial = (m.sender_name || '?').replace(/[^A-Za-zА-Яа-я0-9]/g, '').slice(0, 1).toUpperCase() || '?';
        }
        if (url) {
            return '<img src="' + esc(url) + '" alt="">';
        }
        if (m.sender_kind === 'admin') {
            return '<i class="fa-solid fa-headset"></i>';
        }
        if (m.sender_kind === 'guest') {
            return '<i class="fa-solid fa-user"></i>';
        }
        return esc(initial);
    }

    function bubbleBodyHtml(text) {
        // Preserve line breaks, escape, keep simple URLs clickable.
        var safe = esc(text);
        safe = safe.replace(/(https?:\/\/[^\s<]+)/g, function (m) {
            return '<a href="' + m + '" target="_blank" rel="noopener">' + m + '</a>';
        });
        return safe.replace(/\n/g, '<br>');
    }

    function renderSystem(threadEl, m) {
        var d = el('div', 'su-msg su-msg--system');
        if (m.id) d.dataset.msgId = String(m.id);
        var pill = el('span', 'su-system-pill');
        pill.innerHTML = '<i class="fa-solid fa-circle-info"></i> ' + esc(m.body);
        d.appendChild(pill);
        threadEl.appendChild(d);
    }

    function renderMessage(threadEl, m, opts) {
        opts = opts || {};
        if (m.sender_kind === 'system') {
            renderSystem(threadEl, m);
            applyGroupingForLast(threadEl);
            if (opts.animate) flagNew(threadEl.lastElementChild);
            return;
        }
        var side = isMine(m, opts.viewerKind) ? 'mine' : 'theirs';
        var role = m.sender_kind; // user | admin | guest
        var wrap = el('div', 'su-msg');
        wrap.dataset.side = side;
        wrap.dataset.role = role;
        wrap.dataset.group = groupKey(m);
        wrap.dataset.createdAt = m.created_at || '';
        if (m.id) wrap.dataset.msgId = String(m.id);

        var av = el('div', 'su-avatar', avatarHtml(m, opts));
        wrap.appendChild(av);

        var body = el('div', 'su-bubble-wrap');
        var nameStr = m.sender_name || (role === 'guest' ? 'Гость' : '');
        body.appendChild(el('div', 'su-meta-top', esc(nameStr)));

        var bubble = el('div', 'su-bubble');
        bubble.innerHTML = bubbleBodyHtml(m.body || '');
        body.appendChild(bubble);

        var t = '';
        if (m.created_at) {
            var d = new Date(m.created_at);
            if (!isNaN(d)) t = fmtTime(d);
        }
        body.appendChild(el('div', 'su-meta-bottom', '<time>' + esc(t) + '</time>'));

        wrap.appendChild(body);
        threadEl.appendChild(wrap);

        applyGroupingForLast(threadEl);
        if (opts.animate) flagNew(wrap);
    }

    // After appending, re-evaluate grouping for the last two messages.
    function applyGroupingForLast(threadEl) {
        var msgs = threadEl.querySelectorAll('.su-msg');
        if (!msgs.length) return;
        var last = msgs[msgs.length - 1];
        var prev = msgs.length > 1 ? msgs[msgs.length - 2] : null;
        // Reset on the previous one — it might have been the tail of its group.
        if (prev) {
            prev.classList.remove('su-msg--tail');
        }
        last.classList.remove('su-msg--grouped', 'su-msg--tail');

        if (!prev) {
            last.classList.add('su-msg--tail');
            return;
        }
        // System messages never participate in grouping.
        var lastSystem = last.classList.contains('su-msg--system');
        var prevSystem = prev.classList.contains('su-msg--system');
        if (lastSystem || prevSystem) {
            if (!prevSystem) prev.classList.add('su-msg--tail');
            if (!lastSystem) last.classList.add('su-msg--tail');
            return;
        }
        var sameGroup = prev.dataset.group === last.dataset.group;
        var t1 = Date.parse(prev.dataset.createdAt || '');
        var t2 = Date.parse(last.dataset.createdAt || '');
        var withinWindow = isFinite(t1) && isFinite(t2) && (t2 - t1) < GROUP_GAP_MS;
        if (sameGroup && withinWindow) {
            last.classList.add('su-msg--grouped');
            // prev is no longer the tail
            prev.classList.remove('su-msg--tail');
            last.classList.add('su-msg--tail');
        } else {
            prev.classList.add('su-msg--tail');
            last.classList.add('su-msg--tail');
        }
    }

    function flagNew(elm) {
        if (!elm) return;
        elm.classList.add('su-msg--new');
        setTimeout(function () { elm.classList.remove('su-msg--new'); }, 260);
    }

    function setTyping(rootEl, label) {
        var bar = rootEl.querySelector('[data-su-typing]');
        if (!bar) return;
        if (label) {
            bar.querySelector('.su-typing-label').textContent = label;
            bar.hidden = false;
        } else {
            bar.hidden = true;
        }
    }

    function setConnection(rootEl, state) {
        var bar = rootEl.querySelector('[data-su-conn]');
        if (!bar) return;
        bar.hidden = (state === 'ok');
    }

    function applyClosed(rootEl, closed) {
        var composer = rootEl.querySelector('[data-su-composer]');
        var banner = rootEl.querySelector('[data-su-closed-banner]');
        if (composer) composer.hidden = !!closed;
        if (banner) banner.hidden = !closed;
    }

    function init(rootEl, ctx) {
        rootEl.__suCtx = ctx || {};
    }

    window.SupportUI = {
        init: init,
        renderMessage: renderMessage,
        renderSystem: renderSystem,
        applyGroupingForLast: applyGroupingForLast,
        setTyping: setTyping,
        setConnection: setConnection,
        applyClosed: applyClosed,
        relativeTime: relativeTime,
        esc: esc,
    };
})();
