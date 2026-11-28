// Auth page micro-interactions: password visibility toggle, submit feedback
// and the confirm-password match contract pinned by E2E (customError set on
// mismatch, cleared as soon as the confirmation matches).

export function initEyeToggles(shell) {
    for (const button of shell.querySelectorAll('[data-eye]')) {
        const input = button.parentElement.querySelector('input');
        const icon = button.querySelector('[data-eye-icon]');
        if (!input || !icon) continue;
        button.addEventListener('click', () => {
            const revealed = input.type === 'password';
            input.type = revealed ? 'text' : 'password';
            button.setAttribute('aria-pressed', String(revealed));
            button.setAttribute('aria-label', revealed ? 'Ẩn mật khẩu' : 'Hiện mật khẩu');
            icon.classList.toggle('fa-eye', !revealed);
            icon.classList.toggle('fa-eye-slash', revealed);
        });
    }
}

function restoreSubmitButton(form) {
    const button = form.querySelector('button[type="submit"]');
    const icon = button?.querySelector('[data-btn-icon]');
    if (button) button.disabled = false;
    if (icon) {
        icon.classList.remove('fa-spinner', 'fa-spin-pulse');
        icon.classList.add(icon.getAttribute('data-btn-icon'));
    }
}

export function initSubmitFeedback(shell, eventTarget = globalThis) {
    for (const form of shell.querySelectorAll('form[data-auth-loading]')) {
        form.addEventListener('submit', (event) => {
            if (event.defaultPrevented) return;
            const button = form.querySelector('button[type="submit"]');
            const icon = button?.querySelector('[data-btn-icon]');
            if (!button || button.disabled) return;
            button.disabled = true;
            if (icon) {
                icon.classList.remove(icon.getAttribute('data-btn-icon'));
                icon.classList.add('fa-spinner', 'fa-spin-pulse');
            }
        });
        // A bfcache restore would otherwise present a permanently disabled button.
        eventTarget.addEventListener('pageshow', () => restoreSubmitButton(form));
    }
}

export function initConfirmMatch(shell) {
    const confirm = shell.querySelector('#confirm_password');
    const password = shell.querySelector('#password');
    const hint = shell.querySelector('[data-confirm-hint]');
    if (!confirm || !password) return;

    const sync = () => {
        const touched = confirm.value.length > 0;
        const mismatch = touched && confirm.value !== password.value;
        confirm.setCustomValidity(mismatch ? 'Mật khẩu không khớp' : '');
        confirm.classList.toggle('is-ok', touched && !mismatch);
        if (hint) {
            hint.dataset.state = mismatch ? 'err' : (touched ? 'ok' : '');
            hint.textContent = mismatch ? 'Mật khẩu xác nhận chưa khớp.' : (touched ? 'Mật khẩu khớp.' : '');
        }
    };
    confirm.addEventListener('input', sync);
    password.addEventListener('input', sync);
}

// Match the server's code-point count and support Unicode decimal digits.
export function initPasswordPattern(shell) {
    const input = shell.querySelector('[data-new-password]');
    if (!input) return;
    const valid = (value) => {
        const length = Array.from(value).length;
        return length >= 8 && length <= 128 && /[a-z]/.test(value) && /[A-Z]/.test(value) && /\p{Nd}/u.test(value);
    };
    const form = input.closest('form');
    const hint = shell.querySelector('[data-pattern-hint]');

    const sync = () => {
        const value = input.value;
        const ok = valid(value);
        if (ok) input.removeAttribute('aria-invalid');
        if (hint) {
            hint.dataset.state = ok ? 'ok' : (value ? 'err' : '');
            hint.textContent = ok ? 'Mật khẩu đạt yêu cầu.' : (value ? 'Mật khẩu chưa đạt yêu cầu.' : '');
        }
    };
    input.addEventListener('input', sync);
    form.addEventListener('submit', (event) => {
        if (!valid(input.value)) {
            event.preventDefault();
            input.setAttribute('aria-invalid', 'true');
            sync();
            input.focus();
        }
    });
}

// Keep one brand photo on small screens and when motion is reduced.
export function initAsideSlideshow(scope = document, scheduler = globalThis) {
    const slides = scope.querySelectorAll('[data-aside-slide]');
    if (slides.length < 2) return null;
    const rotation = scheduler.matchMedia?.('(min-width: 768px) and (prefers-reduced-motion: no-preference)');
    if (!rotation?.matches) return null;

    let index = 0;
    let loading = false;
    return scheduler.setInterval(async () => {
        if (!rotation.matches || scope.hidden || loading) return;
        const nextIndex = (index + 1) % slides.length;
        const next = slides[nextIndex];
        const source = next.dataset.asideSrc;

        loading = true;
        try {
            if (source && !next.style.backgroundImage) {
                const photo = new scheduler.Image();
                photo.src = source;
                await photo.decode();
                next.style.backgroundImage = `url("${source}")`;
            }
            if (!rotation.matches || scope.hidden) return;
            slides[index].classList.remove('is-active');
            next.classList.add('is-active');
            index = nextIndex;
        } catch {
            // Keep the visible photo if the upcoming one could not load.
        } finally {
            loading = false;
        }
    }, 5000);
}

function initAuthUi() {
    const shell = document.querySelector('.auth-shell');
    if (!shell) return;
    initEyeToggles(shell);
    initConfirmMatch(shell);
    initPasswordPattern(shell);
    initSubmitFeedback(shell, window);
    initAsideSlideshow(document, window);
}

// Module scripts run after parsing; only auto-init inside a browser document.
if (typeof document !== 'undefined') initAuthUi();
