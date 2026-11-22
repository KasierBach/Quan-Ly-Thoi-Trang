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
        form.addEventListener('submit', () => {
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

function initAuthUi() {
    const shell = document.querySelector('.auth-shell');
    if (!shell) return;
    initEyeToggles(shell);
    initSubmitFeedback(shell, window);
    initConfirmMatch(shell);
}

// Module scripts run after parsing; only auto-init inside a browser document.
if (typeof document !== 'undefined') initAuthUi();
