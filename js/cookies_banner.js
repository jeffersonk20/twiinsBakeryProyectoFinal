/**
 * Banner de Cookies y Tecnologías Esenciales - TWIINS Bakery
 * Aparece en la página principal / index del cliente y solo presenta la opción de aceptar todas.
 * Excluido estrictamente del panel de administración.
 */
(() => {
    // 1. REGLA ESTRICTA: En el panel de administración NO debe aparecer jamás
    const path = (window.location.pathname || "").toLowerCase();
    if (path.startsWith("/admin")) {
        return;
    }

    // Clave de almacenamiento versionada para garantizar que aparezca si no se ha aceptado
    const COOKIE_STORAGE_KEY = "twiins_cookies_consent_v2";

    // Si ya existe la función global para abrir el banner, no duplicar
    if (window.abrirBannerCookies) return;

    function guardarPreferencia() {
        try {
            localStorage.setItem(COOKIE_STORAGE_KEY, "todas");
            // También guardar en cookie del navegador por 1 año
            const d = new Date();
            d.setTime(d.getTime() + 365 * 24 * 60 * 60 * 1000);
            document.cookie = `${COOKIE_STORAGE_KEY}=todas;expires=${d.toUTCString()};path=/;SameSite=Lax`;
        } catch (_) {}
    }

    function tieneConsentimiento() {
        try {
            return Boolean(localStorage.getItem(COOKIE_STORAGE_KEY));
        } catch (_) {
            return false;
        }
    }

    function cerrarBanner(bannerEl) {
        if (!bannerEl) return;
        bannerEl.classList.remove("visible");
        setTimeout(() => {
            if (bannerEl && bannerEl.parentNode) {
                bannerEl.parentNode.removeChild(bannerEl);
            }
        }, 400);
    }

    function crearBanner() {
        let existente = document.getElementById("twiinsCookieBanner");
        if (existente) return existente;

        const banner = document.createElement("div");
        banner.id = "twiinsCookieBanner";
        banner.className = "twiins-cookie-banner";
        banner.setAttribute("role", "dialog");
        banner.setAttribute("aria-live", "polite");
        banner.setAttribute("aria-label", "Aviso sobre cookies y tecnologías esenciales");

        banner.innerHTML = `
            <div class="twiins-cookie-header">
                <div class="twiins-cookie-icon" aria-hidden="true">🍪</div>
                <h3 class="twiins-cookie-title">Uso de Cookies y Tecnologías Esenciales</h3>
            </div>
            <p class="twiins-cookie-body">
                Utilizamos cookies técnicas y almacenamiento esencial propios para mantener tu sesión activa y segura, proteger tus transacciones con tokens de seguridad (CSRF) y permitirte gestionar tus reservas de productos y eventos en TWIINS Bakery. No utilizamos cookies de rastreo publicitario invasivo ni vendemos tu información. Al hacer clic en "Aceptar todas", autorizas el funcionamiento pleno del sitio. Puedes consultar todos los detalles en nuestra <a href="/politica-privacidad">Política de Privacidad</a>.
            </p>
            <div class="twiins-cookie-actions" style="justify-content: flex-end;">
                <button type="button" class="twiins-cookie-btn twiins-cookie-btn-primary" id="btnAceptarCookies" style="min-width: 160px;">Aceptar todas</button>
            </div>
        `;

        document.body.appendChild(banner);

        const btnAceptar = banner.querySelector("#btnAceptarCookies");
        if (btnAceptar) {
            btnAceptar.addEventListener("click", () => {
                guardarPreferencia();
                cerrarBanner(banner);
            });
        }

        return banner;
    }

    function mostrarBanner() {
        const banner = crearBanner();
        setTimeout(() => {
            if (banner) {
                banner.classList.add("visible");
            }
        }, 200);
    }

    // Exponer función global para abrir el banner en cualquier momento desde el enlace "Cookies" del footer
    window.abrirBannerCookies = () => {
        mostrarBanner();
    };

    // Comprobar si estamos en el index / página principal del cliente
    const esIndex = path === "/" || path === "" || path.endsWith("/index.html") || path.endsWith("/inicio");

    function inicializar() {
        // En el cliente: mostrar en el index si aún no se ha dado consentimiento
        if (!tieneConsentimiento() && esIndex) {
            setTimeout(mostrarBanner, 500);
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", inicializar);
    } else {
        inicializar();
    }
})();
