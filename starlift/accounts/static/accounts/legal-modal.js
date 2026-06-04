(function () {
    const modal = document.getElementById('legalModal');
    if (!modal) return;

    const titleEl = modal.querySelector('[data-legal-title]');
    const bodyEl = modal.querySelector('.legal-modal__body');
    const docs = modal.querySelectorAll('[data-legal-doc]');
    const closers = modal.querySelectorAll('[data-legal-close]');

    const TITLES = {
        consent: 'Согласие на обработку персональных данных',
        privacy: 'Политика конфиденциальности',
        terms: 'Пользовательское соглашение',
    };

    let lastFocused = null;

    function open(which) {
        lastFocused = document.activeElement;
        if (titleEl) titleEl.textContent = TITLES[which] || 'Документ';
        docs.forEach(d => { d.hidden = d.dataset.legalDoc !== which; });
        modal.classList.add('is-open');
        document.body.classList.add('legal-modal-open');
        if (bodyEl) bodyEl.scrollTop = 0;
        const closeBtn = modal.querySelector('.legal-modal__close');
        if (closeBtn) closeBtn.focus({ preventScroll: true });
    }

    function close() {
        modal.classList.remove('is-open');
        document.body.classList.remove('legal-modal-open');
        if (lastFocused && typeof lastFocused.focus === 'function') {
            try { lastFocused.focus({ preventScroll: true }); } catch (_) {}
        }
    }

    document.querySelectorAll('.legal-link[data-legal]').forEach(el => {
        el.addEventListener('click', (e) => {
            // Не даём событию подняться до <label>, чтобы клик
            // не переключал чекбокс согласия.
            e.preventDefault();
            e.stopPropagation();
            const which = el.dataset.legal;
            if (which) open(which);
        });
    });

    closers.forEach(b => b.addEventListener('click', close));

    modal.addEventListener('click', (e) => {
        if (e.target === modal) close();
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && modal.classList.contains('is-open')) close();
    });
})();
