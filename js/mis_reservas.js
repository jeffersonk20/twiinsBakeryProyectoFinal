(() => {
    document.querySelectorAll("[data-confirm-cancel]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            if (!window.confirm("¿Confirmas la cancelación? Los pagos realizados no son reembolsables.")) {
                event.preventDefault();
            }
        });
    });
})();
