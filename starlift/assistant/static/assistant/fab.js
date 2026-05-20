// Boot script: instantiates ChatWidget for every `.assistant-chat-root` on the
// page, wires the floating-button drawer (if present), and exposes a small
// public API used by the home-page prompt launcher.
//
// `widget.js` MUST be loaded before this file.
(function () {
    if (typeof window.AssistantChatWidget !== 'function') return;

    // Pick up every chat root on the page and spin up an instance. Both the
    // home-page embedded chat and the FAB drawer use `.assistant-chat-root`.
    const widgets = [];
    document.querySelectorAll('.assistant-chat-root').forEach((root) => {
        const w = new window.AssistantChatWidget(root);
        if (w.thread) {
            widgets.push({ root, widget: w });
            // Inline (home) widgets hydrate immediately so they're usable on
            // first load. Drawer widgets hydrate lazily on open.
            if (root.dataset.hydrate === 'eager') w.hydrate();
        }
    });

    const fabBtn = document.getElementById('assistant-fab');
    const drawer = document.getElementById('assistant-drawer');
    const closeBtn = document.getElementById('assistant-close');
    const drawerWidget = (() => {
        if (!drawer) return null;
        const root = drawer.querySelector('.assistant-chat-root');
        return widgets.find(w => w.root === root)?.widget || null;
    })();

    function openDrawer() {
        if (!drawer) return;
        drawer.classList.add('open');
        drawer.setAttribute('aria-hidden', 'false');
        if (fabBtn) {
            fabBtn.classList.add('open');
            fabBtn.innerHTML = '<i class="fa-solid fa-xmark"></i>';
        }
        if (drawerWidget && !drawerWidget.hydrated) {
            drawerWidget.hydrate().then(() => drawerWidget.input.focus());
        } else if (drawerWidget) {
            drawerWidget.input.focus();
        }
    }
    function closeDrawer() {
        if (!drawer) return;
        drawer.classList.remove('open');
        drawer.setAttribute('aria-hidden', 'true');
        if (fabBtn) {
            fabBtn.classList.remove('open');
            fabBtn.innerHTML = '<i class="fa-solid fa-robot"></i><span class="assistant-fab-dot"></span>';
        }
    }
    function toggleDrawer() {
        if (!drawer) return;
        drawer.classList.contains('open') ? closeDrawer() : openDrawer();
    }

    if (fabBtn) fabBtn.addEventListener('click', toggleDrawer);
    if (closeBtn) closeBtn.addEventListener('click', closeDrawer);

    if (drawer) {
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && drawer.classList.contains('open')) closeDrawer();
        });
        document.addEventListener('mousedown', (e) => {
            if (!drawer.classList.contains('open')) return;
            if (drawer.contains(e.target)) return;
            if (fabBtn && fabBtn.contains(e.target)) return;
            closeDrawer();
        });
    }

    // Public API for external triggers (home-page prompt launcher).
    window.assistantChat = {
        open: openDrawer,
        close: closeDrawer,
        openWith(text) {
            const t = (text || '').trim();
            if (!t) return;
            // Prefer the drawer if available (so it pops up); otherwise use
            // the first widget on the page (the embedded one on home).
            const target = drawerWidget || (widgets[0] && widgets[0].widget);
            if (!target) return;
            if (drawerWidget) openDrawer();
            const trySend = () => {
                if (target.conversationId) target.send(t);
                else setTimeout(trySend, 60);
            };
            target.hydrated ? trySend() : target.hydrate().then(trySend);
        },
    };
})();
