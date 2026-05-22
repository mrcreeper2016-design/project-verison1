// Boot script: instantiates ChatWidget for every `.assistant-chat-root` on the
// page, wires the floating-button drawer (if present), and exposes a small
// public API used by the home-page prompt launcher.
//
// `widget.js` MUST be loaded before this file.
(function () {
    if (typeof window.AssistantChatWidget !== 'function') return;

    // Pick up every chat root on the page and spin up an instance. Both the
    // home-page embedded chat and the FAB drawer use `.assistant-chat-root`.
    // `root.__widget` is set in the widget ctor; we use that to avoid double-
    // wiring on SPA re-runs.
    const widgets = [];
    function initWidgets() {
        document.querySelectorAll('.assistant-chat-root').forEach((root) => {
            if (root.__widget) return; // already wired
            const w = new window.AssistantChatWidget(root);
            if (w.thread) {
                widgets.push({ root, widget: w });
                if (root.dataset.hydrate === 'eager') w.hydrate();
            }
        });
    }
    initWidgets();
    // SPA navigation re-renders #page-content — inline scripts run again, but
    // this file is loaded once. Re-init when the SPA finishes a swap.
    document.addEventListener('spa-page-loaded', initWidgets);

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
            var icon = fabBtn.querySelector('i.fa-solid');
            if (icon) {
                icon.classList.remove('fa-robot');
                icon.classList.add('fa-xmark');
            }
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
            var icon = fabBtn.querySelector('i.fa-solid');
            if (icon) {
                icon.classList.remove('fa-xmark');
                icon.classList.add('fa-robot');
            }
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
