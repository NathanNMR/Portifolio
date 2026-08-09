(function () {
    "use strict";

    var ICONS = {
        gmail: '<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg"><rect width="48" height="48" rx="11" fill="#fff"/><path d="M6 15.3v17.4A2.3 2.3 0 0 0 8.3 35H13V19.6L24 27.4l11-7.8V35h4.7a2.3 2.3 0 0 0 2.3-2.3V15.3a2.3 2.3 0 0 0-3.63-1.88L24 22.6 9.63 13.42A2.3 2.3 0 0 0 6 15.3z" fill="#EA4335"/></svg>',
        outlook: '<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg"><rect width="48" height="48" rx="11" fill="#0A2767"/><path d="M27 21.8 42 14v20a2 2 0 0 1-2 2H27z" fill="#0364B8"/><path d="M27 24 42 31.5V34a2 2 0 0 1-2 2H27z" fill="#0A2767" fill-opacity=".5"/><rect x="6" y="11" width="21" height="26" rx="2.2" fill="#28A8EA"/><path d="M16.5 15.3c-3.6 0-6 2.9-6 6.9s2.4 6.9 6 6.9 6-2.9 6-6.9-2.4-6.9-6-6.9zm0 11c-1.9 0-3.1-1.7-3.1-4.1s1.2-4.1 3.1-4.1 3.1 1.7 3.1 4.1-1.2 4.1-3.1 4.1z" fill="#fff"/></svg>',
        apple: '<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg"><rect width="48" height="48" rx="11" fill="#0A84FF"/><rect x="9" y="14" width="30" height="20" rx="2.6" fill="#fff"/><path d="M9.5 15.6 24 26.5l14.5-10.9" fill="none" stroke="#0A84FF" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        yahoo: '<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg"><rect width="48" height="48" rx="11" fill="#5F01D1"/><text x="24" y="31" font-family="Arial, Helvetica, sans-serif" font-size="17" font-weight="700" fill="#fff" text-anchor="middle">Y!</text></svg>',
        generic: '<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg"><rect x="9" y="13" width="30" height="22" rx="2.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="M10 14.5 24 25 38 14.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        copy: '<svg viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg"><rect x="17" y="17" width="21" height="21" rx="2.8" fill="none" stroke="currentColor" stroke-width="1.8"/><rect x="10" y="10" width="21" height="21" rx="2.8" fill="var(--card-bg)" stroke="currentColor" stroke-width="1.8"/></svg>'
    };

    var overlay = null;

    function buildModal() {
        var el = document.createElement("div");
        el.className = "email-modal-overlay";
        el.id = "emailModalOverlay";
        el.innerHTML =
            '<div class="email-modal" role="dialog" aria-modal="true" aria-labelledby="emailModalTitle">' +
                '<div class="email-modal-header">' +
                    '<div>' +
                        '<div class="email-modal-title" id="emailModalTitle">Enviar e-mail</div>' +
                        '<div class="email-modal-subtitle">Escolha como prefere entrar em contato</div>' +
                    '</div>' +
                    '<button class="email-modal-close" id="emailModalClose" type="button" aria-label="Fechar">&times;</button>' +
                '</div>' +
                '<div class="email-options" id="emailOptionsList"></div>' +
                '<div class="email-modal-footer">' +
                    '<span id="emailModalAddress"></span>' +
                '</div>' +
            '</div>';
        document.body.appendChild(el);
        return el;
    }

    function showToast(msg) {
        var toast = document.createElement("div");
        toast.className = "toast-notification";
        toast.textContent = msg;
        document.body.appendChild(toast);
        setTimeout(function () { toast.remove(); }, 3400);
    }

    function closeEmailModal() {
        if (overlay) overlay.classList.remove("active");
        document.removeEventListener("keydown", escHandler);
    }

    function escHandler(e) {
        if (e.key === "Escape") closeEmailModal();
    }

    function openEmailModal(email) {
        if (!overlay) overlay = buildModal();

        var encoded = encodeURIComponent(email);
        var options = [
            { key: "gmail", label: "Gmail", href: "https://mail.google.com/mail/?view=cm&fs=1&to=" + encoded, external: true },
            { key: "outlook", label: "Outlook", href: "https://outlook.live.com/mail/0/deeplink/compose?to=" + encoded, external: true },
            { key: "yahoo", label: "Yahoo Mail", href: "https://compose.mail.yahoo.com/?to=" + encoded, external: true },
            { key: "apple", label: "Apple Mail", href: "mailto:" + email, external: false },
            { key: "generic", label: "Aplicativo padrão do dispositivo", href: "mailto:" + email, external: false }
        ];

        var list = overlay.querySelector("#emailOptionsList");
        list.innerHTML = options.map(function (opt) {
            return '<a class="email-option" href="' + opt.href + '"' +
                (opt.external ? ' target="_blank" rel="noopener"' : "") + '>' +
                '<span class="email-option-icon">' + ICONS[opt.key] + '</span>' +
                '<span class="email-option-label">' + opt.label + '</span>' +
                '<span class="email-option-arrow">→</span>' +
                '</a>';
        }).join("") +
            '<button class="email-option email-option-copy" id="emailCopyBtn" type="button">' +
            '<span class="email-option-icon">' + ICONS.copy + '</span>' +
            '<span class="email-option-label">Copiar endereço de e-mail</span>' +
            '<span class="email-option-arrow">⧉</span>' +
            '</button>';

        overlay.querySelector("#emailModalAddress").textContent = email;

        overlay.querySelector("#emailCopyBtn").onclick = function () {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(email).then(function () {
                    showToast("✓ E-mail copiado para a área de transferência");
                    closeEmailModal();
                });
            }
        };

        overlay.querySelector("#emailModalClose").onclick = closeEmailModal;
        overlay.onclick = function (e) {
            if (e.target === overlay) closeEmailModal();
        };

        overlay.classList.add("active");
        document.addEventListener("keydown", escHandler);
    }

    document.addEventListener("DOMContentLoaded", function () {
        document.querySelectorAll("[data-email-modal]").forEach(function (trigger) {
            trigger.addEventListener("click", function (e) {
                var email = trigger.getAttribute("data-email");
                if (email) {
                    e.preventDefault();
                    openEmailModal(email);
                }
            });
        });
    });
})();