/**
 * Gestión del Sidebar y Modal de Cierre de Sesión en Panel de Administración
 * TWIINS Bakery
 */
(() => {
    'use strict';

    function initAdminLogout() {
        const modal = document.getElementById('adminLogoutModal');
        const btnLogout = document.getElementById('btnAdminLogout');
        const btnCancel = document.getElementById('btnAdminLogoutCancel');
        const btnConfirm = document.getElementById('btnAdminLogoutConfirm');
        const logoutForm = document.getElementById('adminLogoutForm');

        if (!modal) return;

        function openModal(e) {
            if (e) e.preventDefault();
            modal.classList.add('is-visible');
            modal.setAttribute('aria-hidden', 'false');
        }

        function closeModal() {
            modal.classList.remove('is-visible');
            modal.setAttribute('aria-hidden', 'true');
        }

        // Interceptar clic en botón o formulario de logout
        if (btnLogout) {
            btnLogout.addEventListener('click', openModal);
        }

        if (logoutForm) {
            logoutForm.addEventListener('submit', (e) => {
                // Solo prevenir si no venimos de confirmación directa
                if (!logoutForm.dataset.confirmed) {
                    e.preventDefault();
                    openModal(e);
                }
            });
        }

        if (btnCancel) {
            btnCancel.addEventListener('click', closeModal);
        }

        if (btnConfirm) {
            btnConfirm.addEventListener('click', () => {
                if (logoutForm) {
                    logoutForm.dataset.confirmed = 'true';
                    logoutForm.submit();
                }
            });
        }

        // Cerrar al hacer clic en el backdrop
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                closeModal();
            }
        });

        // Cerrar con Escape
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && modal.classList.contains('is-visible')) {
                closeModal();
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initAdminLogout);
    } else {
        initAdminLogout();
    }
})();

