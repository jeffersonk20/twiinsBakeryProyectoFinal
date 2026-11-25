/**
 * Gestión de Perfil de Usuario, Subida de Foto y Modal de Confirmación de Cierre de Sesión
 * TWIINS Bakery
 */
(() => {
    // 1. Asignación dinámica de estado activo en Tabnav (.active-tab)
    const currentPath = window.location.pathname.replace(/\/$/, "");
    const navLinks = document.querySelectorAll(".desktop-nav a, .detail-nav a");

    navLinks.forEach((link) => {
        const linkPath = link.getAttribute("href")?.split("?")[0].replace(/\/$/, "");
        if (linkPath && (linkPath === currentPath || (linkPath === "/inicio" && currentPath === ""))) {
            link.classList.add("active-tab");
            if (!link.classList.contains("active")) {
                link.classList.add("active");
            }
        }
    });

    // 2. Dropdown de Perfil
    const profileToggleBtn = document.getElementById("profileToggleBtn");
    const profileDropdownMenu = document.getElementById("profileDropdownMenu");
    const avatarInput = document.getElementById("inputFotoPerfil");
    const avatarTrigger = document.getElementById("dropdownAvatarTrigger");
    const avatarHint = document.getElementById("avatarUploadHint");
    const headerAvatar = document.getElementById("headerAvatarImg");
    const dropdownAvatar = document.getElementById("dropdownAvatarImg");

    function closeProfileDropdown() {
        if (!profileDropdownMenu) return;
        profileDropdownMenu.classList.remove("is-open");
        if (profileToggleBtn) {
            profileToggleBtn.setAttribute("aria-expanded", "false");
        }
    }

    if (profileToggleBtn && profileDropdownMenu) {
        profileToggleBtn.addEventListener("click", (e) => {
            e.stopPropagation();
            const isOpen = profileDropdownMenu.classList.toggle("is-open");
            profileToggleBtn.setAttribute("aria-expanded", String(isOpen));
        });

        // Cerrar al hacer clic fuera
        document.addEventListener("click", (e) => {
            if (!profileDropdownMenu.contains(e.target) && !profileToggleBtn.contains(e.target)) {
                closeProfileDropdown();
            }
        });

        // Cerrar con Escape
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape") {
                closeProfileDropdown();
                closeLogoutModal();
            }
        });
    }

    // 3. Subida interactiva de Foto de Perfil
    function showToast(mensaje, isError = false) {
        let toast = document.getElementById("avatarFeedbackToast");
        if (!toast) {
            toast = document.createElement("div");
            toast.id = "avatarFeedbackToast";
            toast.className = "avatar-feedback-toast";
            document.body.appendChild(toast);
        }
        toast.textContent = mensaje;
        toast.style.background = isError ? "#c62828" : "#153e49";
        toast.classList.add("show");
        setTimeout(() => toast.classList.remove("show"), 3500);
    }

    function triggerAvatarUpload() {
        if (avatarInput) avatarInput.click();
    }

    if (avatarTrigger) avatarTrigger.addEventListener("click", triggerAvatarUpload);
    if (avatarHint) avatarHint.addEventListener("click", triggerAvatarUpload);

    if (avatarInput) {
        avatarInput.addEventListener("change", async () => {
            const file = avatarInput.files && avatarInput.files[0];
            if (!file) return;

            // Validación en frontend: archivo de tipo imagen y tamaño <= 20MB
            if (!file.type.startsWith("image/")) {
                showToast("Por favor selecciona un archivo de imagen válido (JPG, PNG o WEBP).", true);
                avatarInput.value = "";
                return;
            }

            const maxBytes = 20 * 1024 * 1024; // 20 MB
            if (file.size > maxBytes) {
                showToast("La imagen supera el límite permitido de 20 MB.", true);
                avatarInput.value = "";
                return;
            }

            // Envío seguro al backend mediante FormData
            const formData = new FormData();
            formData.append("foto", file);

            try {
                showToast("Actualizando foto de perfil…");
                const response = await fetch("/api/cliente/foto-perfil", {
                    method: "POST",
                    body: formData,
                });

                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.error || "No se pudo actualizar la foto de perfil.");
                }

                // Recargar imagen en el avatar con cache-buster
                const cacheBuster = `?t=${Date.now()}`;
                const newUrl = `/cliente/foto-perfil${cacheBuster}`;
                if (headerAvatar) headerAvatar.src = newUrl;
                if (dropdownAvatar) dropdownAvatar.src = newUrl;

                showToast(data.mensaje || "Foto de perfil actualizada exitosamente.");
            } catch (err) {
                showToast(err.message || "Error al subir la imagen.", true);
            } finally {
                avatarInput.value = "";
            }
        });
    }

    // 4. Modal de Confirmación de Cierre de Sesión (Generado dinámicamente bajo demanda para no exponerlo en el HTML)
    function openLogoutModal(e) {
        if (e) e.preventDefault();
        closeProfileDropdown();

        let modal = document.getElementById("logoutModal");
        if (!modal) {
            modal = document.createElement("div");
            modal.id = "logoutModal";
            modal.className = "custom-modal-overlay";
            modal.setAttribute("role", "dialog");
            modal.setAttribute("aria-modal", "true");
            modal.setAttribute("aria-labelledby", "logoutModalTitle");
            modal.innerHTML = `
                <div class="custom-modal-card">
                    <div class="modal-icon-wrap">🔒</div>
                    <h3 id="logoutModalTitle">¿Estas seguro de cerrar sesión?</h3>
                    <p>Tendrás que ingresar tus credenciales nuevamente para acceder a tus reservas y pedidos.</p>
                    <div class="modal-actions">
                        <button type="button" class="modal-btn modal-btn-secondary" id="btnLogoutCancel">NO</button>
                        <a href="/cerrar-sesion" class="modal-btn modal-btn-primary" id="btnLogoutConfirm">SÍ</a>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);

            modal.querySelector("#btnLogoutCancel")?.addEventListener("click", closeLogoutModal);
            modal.addEventListener("click", (evt) => {
                if (evt.target === modal) closeLogoutModal();
            });
        }

        requestAnimationFrame(() => {
            modal.classList.add("is-visible");
            modal.setAttribute("aria-hidden", "false");
        });
    }

    function closeLogoutModal() {
        const modal = document.getElementById("logoutModal");
        if (modal) {
            modal.classList.remove("is-visible");
            modal.setAttribute("aria-hidden", "true");
            setTimeout(() => {
                if (modal && modal.parentNode) {
                    modal.parentNode.removeChild(modal);
                }
            }, 250);
        }
    }

    // Vincular botón en el dropdown
    const btnLogoutProfile = document.getElementById("btnCerrarSesionPerfil");
    if (btnLogoutProfile) {
        btnLogoutProfile.addEventListener("click", openLogoutModal);
    }

    // Interceptar también enlace "Salir" en mobile nav si existe
    const mobileExitLinks = document.querySelectorAll("a[href*='cerrar-sesion'], a[href*='cerrar_sesion']");
    mobileExitLinks.forEach((link) => {
        if (link.id !== "btnLogoutConfirm") {
            link.addEventListener("click", openLogoutModal);
        }
    });
})();

