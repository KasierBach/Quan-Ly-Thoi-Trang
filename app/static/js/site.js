(() => {
    const config = JSON.parse(document.getElementById('base-data').textContent);
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content;
    const contactButton = document.getElementById('contactBtn');
    contactButton?.addEventListener('click', () => {
        const open = contactButton.classList.toggle('active');
        document.getElementById('contactMenu')?.classList.toggle('show', open);
        contactButton.closest('.floating-contact')?.classList.toggle('active', open);
        contactButton.setAttribute('aria-expanded', String(open));
    });

    setTimeout(() => document.querySelectorAll('.flash-messages .alert').forEach(element => {
        bootstrap.Alert.getOrCreateInstance(element).close();
    }), 5000);

    const newsletter = document.getElementById('newsletter-form');
    newsletter?.addEventListener('submit', async event => {
        event.preventDefault();
        if (!newsletter.reportValidity()) return;
        const button = document.getElementById('subscribe-btn');
        button.disabled = true;
        try {
            const response = await fetch(config.subscribeUrl, {
                method: 'POST', headers: { 'X-CSRFToken': csrf },
                body: new URLSearchParams({ email: document.getElementById('newsletter-email').value })
            });
            const data = await response.json();
            document.getElementById('newsletter-status').textContent = data.message;
            if (response.ok && data.success) newsletter.reset();
        } catch {
            document.getElementById('newsletter-status').textContent = 'Không thể đăng ký. Vui lòng thử lại.';
        } finally {
            button.disabled = false;
        }
    });

    const applyTheme = theme => {
        document.documentElement.dataset.bsTheme = theme;
        document.getElementById('darkIcon').style.display = theme === 'dark' ? 'inline' : 'none';
        document.getElementById('lightIcon').style.display = theme === 'light' ? 'inline' : 'none';
    };
    if (!config.isLoggedIn) {
        try {
            const saved = localStorage.getItem('darkMode');
            if (saved) applyTheme(saved === 'enabled' ? 'dark' : 'light');
        } catch { /* Storage can be unavailable in private browsing. */ }
    }
    applyTheme(document.documentElement.dataset.bsTheme || 'light');
    document.getElementById('toggleTheme')?.addEventListener('click', async () => {
        const previous = document.documentElement.dataset.bsTheme;
        const next = previous === 'dark' ? 'light' : 'dark';
        applyTheme(next);
        if (config.isLoggedIn) {
            try {
                const response = await fetch(config.themeUrl, {
                    method: 'POST', headers: { 'X-CSRFToken': csrf },
                    body: new URLSearchParams({ dark_mode: next === 'dark' ? '1' : '0' })
                });
                if (!response.ok || !(await response.json()).success) applyTheme(previous);
            } catch { applyTheme(previous); }
        } else {
            try { localStorage.setItem('darkMode', next === 'dark' ? 'enabled' : 'disabled'); }
            catch { /* The visual preference still applies to the current page. */ }
        }
    });

    const input = document.getElementById('searchInput');
    const results = document.getElementById('searchAutocomplete');
    if (!input || !results) return;
    let timer;
    let request;
    const dismiss = () => {
        clearTimeout(timer);
        request?.abort();
        results.replaceChildren();
        results.classList.remove('show');
        input.setAttribute('aria-expanded', 'false');
    };
    input.addEventListener('input', () => {
        dismiss();
        const query = input.value.trim();
        if (!query) return;
        timer = setTimeout(async () => {
            request = new AbortController();
            const signal = request.signal;
            try {
                const response = await fetch(`${config.searchUrl}?${new URLSearchParams({ q: query })}`, { signal });
                const data = await response.json();
                if (signal.aborted || query !== input.value.trim() || !response.ok || !data.success) return;
                for (const product of data.products) {
                    const link = document.createElement('a');
                    link.href = `/product/${Number(product.id)}`;
                    link.className = 'search-autocomplete-item';
                    const image = document.createElement('img');
                    image.loading = 'lazy';
                    image.decoding = 'async';
                    // This is the existing CSS crop box, not the source image's dimensions.
                    image.style.aspectRatio = '1 / 1';
                    image.style.flexShrink = '0';
                    const candidate = new URL(product.image || '/static/images/default.jpg', location.origin);
                    image.src = candidate.origin === location.origin || candidate.protocol === 'https:' ? candidate.href : '/static/images/default.jpg';
                    image.alt = product.name;
                    image.className = 'search-autocomplete-img';
                    image.addEventListener('error', () => { image.src = '/static/images/default.jpg'; }, { once: true });
                    const info = document.createElement('div');
                    info.className = 'search-autocomplete-info';
                    const name = document.createElement('div');
                    name.className = 'search-autocomplete-name';
                    name.textContent = product.name;
                    const price = document.createElement('div');
                    price.className = 'search-autocomplete-meta';
                    price.textContent = `${new Intl.NumberFormat('vi-VN').format(Number(product.price))}₫ — ${product.category || ''}`;
                    info.append(name, price);
                    link.append(image, info);
                    results.append(link);
                }
                if (!data.products.length) {
                    const empty = document.createElement('div');
                    empty.className = 'search-no-results';
                    empty.textContent = 'Không tìm thấy sản phẩm';
                    results.append(empty);
                }
                results.classList.add('show');
                input.setAttribute('aria-expanded', 'true');
            } catch {
                if (!signal.aborted) dismiss();
            }
        }, 250);
    });
    document.addEventListener('click', event => { if (!event.target.closest('#searchForm')) dismiss(); });
    input.addEventListener('keydown', event => {
        if (event.key === 'Escape') dismiss();
        if (event.key === 'ArrowDown') { event.preventDefault(); results.querySelector('a')?.focus(); }
    });
    results.addEventListener('keydown', event => {
        if (event.key === 'Escape') { dismiss(); input.focus(); }
    });
})();
