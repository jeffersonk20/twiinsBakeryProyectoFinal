/**
 * Banner de Cookies y Tecnologías Esenciales - TWIINS Bakery
 * Cumplimiento de normativas y transparencia para los usuarios en El Salvador.
 */
(() => {
    const COOKIE_STORAGE_KEY = "twiins_cookies_consent";

    // Si ya existe la función global para abrir el banner, no duplicar
    if (window.abrirBannerCookies) return;

    function guardarPreferencia(valor) {
        try {
            localStorage.setItem(COOKIE_STORAGE_KEY, valor);
            // También guardar en cookie del navegador por 1 año
            const d = new Date();
            d.setTime(d.getTime() + 365 * 24 * 60 * 60 * 1000);
            document.cookie = `${COOKIE_STORAGE_KEY}=${valor};expires=${d.toUTCString()};path=/;SameSite=Lax`;
        } catch (_) {}
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
        // Evitar duplicados
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
            <div class="twiins-cookie-actions">
                <button type="button" class="twiins-cookie-btn twiins-cookie-btn-secondary" id="btnSoloNecesariasCookies">Solo necesarias</button>
                <button type="button" class="twiins-cookie-btn twiins-cookie-btn-primary" id="btnAceptarCookies">Aceptar todas</button>
            </div>
        `;

        document.body.appendChild(banner);

        const btnAceptar = banner.querySelector("#btnAceptarCookies");
        const btnNecesarias = banner.querySelector("#btnSoloNecesariasCookies");

        if (btnAceptar) {
            btnAceptar.addEventListener("click", () => {
                guardarPreferencia("todas");
                cerrarBanner(banner);
            });
        }

        if (btnNecesarias) {
            btnNecesarias.addEventListener("click", () => {
                guardarPreferencia("necesarias");
                cerrarBanner(banner);
            });
        }

        return banner;
    }

    function mostrarBanner() {
        const banner = crearBanner();
        // Animación suave de entrada
        setTimeout(() => {
            if (banner) {
                banner.classList.add("visible");
            }
        }, 300);
    }

    // Exponer función global para abrir el banner si el usuario desea revisar su consentimiento
    window.abrirBannerCookies = () => {
        mostrarBanner();
    };

    // Al cargar la página, comprobar si ya se dio consentimiento
    const consent = localStorage.getItem(COOKIE_STORAGE_KEY);
    if (!consent) {
        if (document.readyState === "loading") {
            document.addEventListener("DOMContentLoaded", () => {
                setTimeout(mostrarBanner, 600);
            });
        } else {
            setTimeout(mostrarBanner, 600);
        }
    }
})();
