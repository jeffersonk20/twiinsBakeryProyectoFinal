(() => {
    // 1. Establecer fecha mínima para eventos (mínimo 3 días de anticipación)
    const fechaInput = document.getElementById("fecha_evento");
    if (fechaInput) {
        const fechaMinima = new Date();
        fechaMinima.setDate(fechaMinima.getDate() + 3);
        const yyyy = fechaMinima.getFullYear();
        const mm = String(fechaMinima.getMonth() + 1).padStart(2, "0");
        const dd = String(fechaMinima.getDate()).padStart(2, "0");
        fechaInput.min = `${yyyy}-${mm}-${dd}`;
    }

    // 2. Selección interactiva de chips de servicios
    const chipsContainer = document.getElementById("serviciosChips");
    const inputServicios = document.getElementById("inputServicios");
    const serviciosError = document.getElementById("serviciosError");

    if (chipsContainer && inputServicios) {
        const chips = chipsContainer.querySelectorAll(".chip-btn");

        function actualizarServicios() {
            const seleccionados = Array.from(chips)
                .filter((chip) => chip.classList.contains("activo"))
                .map((chip) => chip.dataset.servicio || chip.textContent.trim());
            inputServicios.value = seleccionados.join(", ");
            if (serviciosError && seleccionados.length > 0) {
                serviciosError.style.display = "none";
            }
        }

        chips.forEach((chip) => {
            chip.addEventListener("click", () => {
                chip.classList.toggle("activo");
                actualizarServicios();
            });
        });
    }

    // 3. Confirmación de cancelación para eventos
    document.querySelectorAll("[data-confirm-cancel-evento]").forEach((form) => {
        form.addEventListener("submit", (event) => {
            if (!window.confirm("¿Estás seguro de que deseas cancelar esta solicitud de evento?")) {
                event.preventDefault();
            }
        });
    });
})();
