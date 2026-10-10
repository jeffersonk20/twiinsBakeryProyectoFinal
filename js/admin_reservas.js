(() => {
    const app = document.querySelector("[data-admin-reservations]");
    if (!app) return;

    const csrfToken = app.dataset.csrfToken;
    const body = app.querySelector("[data-reservations-body]");
    const search = app.querySelector("[data-search]");
    const statusFilter = app.querySelector("[data-status-filter]");
    const message = app.querySelector("[data-admin-message]");
    const emptyList = app.querySelector("[data-empty-list]");
    const loading = app.querySelector("[data-loading]");
    const dialog = document.querySelector("[data-edit-dialog]");
    const editForm = document.querySelector("[data-edit-form]");
    let reservations = [];

    const statusNames = {
        PENDIENTE_PAGO: "Pendiente de anticipo",
        CONFIRMADA: "Confirmada",
        EN_PREPARACION: "En preparación",
        LISTA: "Lista para retirar",
        ENTREGADA: "Entregada",
        CANCELADA: "Cancelada"
    };
    const statusClasses = {
        CONFIRMADA: "confirmed",
        EN_PREPARACION: "preparing",
        LISTA: "ready",
        ENTREGADA: "delivered",
        CANCELADA: "cancelled"
    };

    function escapeHtml(value) {
        return String(value).replace(/[&<>"']/g, (character) => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;"
        })[character]);
    }

    function formatPrice(value) {
        return new Intl.NumberFormat("es-US", {
            style: "currency",
            currency: "USD"
        }).format(Number(value));
    }

    function displayDate(value) {
        const date = new Date(String(value).replace(" ", "T"));
        if (Number.isNaN(date.getTime())) return escapeHtml(value);
        return new Intl.DateTimeFormat("es", {
            dateStyle: "medium",
            timeStyle: "short"
        }).format(date);
    }

    function paymentName(value) {
        if (value === "EFECTIVO_TIENDA") return "Efectivo en tienda";
        if (value === "WOMPI") return "Tarjeta · Wompi";
        return "Sin método";
    }

    function showMessage(text, isError = false) {
        message.textContent = text;
        message.classList.toggle("error", isError);
        message.hidden = false;
        window.setTimeout(() => {
            message.hidden = true;
        }, 5500);
    }

    async function readResponse(response) {
        let result;
        try {
            result = await response.json();
        } catch {
            throw new Error("El servidor devolvió una respuesta que no se pudo interpretar.");
        }
        if (!response.ok) throw new Error(result.error || "No se pudo completar la operación.");
        return result;
    }

    function render() {
        const query = search.value.trim().toLocaleLowerCase();
        const selectedStatus = statusFilter.value;
        const filtered = reservations.filter((reservation) => {
            const matchesText = !query || [
                reservation.codigo,
                reservation.cliente,
                reservation.correo,
                reservation.producto,
                reservation.telefono
            ].some((value) => String(value).toLocaleLowerCase().includes(query));
            return matchesText && (!selectedStatus || reservation.estado === selectedStatus);
        });

        body.innerHTML = filtered.map((reservation) => {
            const stateClass = statusClasses[reservation.estado] || "";
            const paymentPending = reservation.pago_estado === "PENDIENTE";
            const cashPending = paymentPending
                && reservation.metodo_pago === "EFECTIVO_TIENDA"
                && reservation.estado !== "CANCELADA";
            const paidLabel = paymentPending ? "Pendiente" : "Anticipo pagado";
            const paymentClass = paymentPending ? "" : "paid";
            return `<tr>
                <td><div class="reservation-id"><strong>${escapeHtml(reservation.codigo)}</strong><span>${escapeHtml(reservation.cliente)}</span><span>${escapeHtml(reservation.correo)}</span></div></td>
                <td><div class="product-cell"><strong>${escapeHtml(reservation.producto)}</strong><span>${reservation.cantidad} unidad(es) · ${formatPrice(reservation.precio_unitario)} c/u</span></div></td>
                <td>${displayDate(reservation.fecha_retiro)}</td>
                <td><div class="amount-cell"><strong>${formatPrice(reservation.total)}</strong><span>Anticipo: ${formatPrice(reservation.anticipo_requerido)}</span></div></td>
                <td><span class="status-pill ${stateClass}">${escapeHtml(statusNames[reservation.estado] || reservation.estado)}</span></td>
                <td><span class="payment-state ${paymentClass}">${paidLabel}</span><span class="muted-cell">${escapeHtml(paymentName(reservation.metodo_pago))}</span></td>
                <td><div class="row-actions">
                    <button type="button" data-edit="${reservation.id}">Editar</button>
                    ${cashPending ? `<button type="button" data-pay="${reservation.id}">Registrar efectivo</button>` : ""}
                    <button type="button" class="delete-action" data-delete="${reservation.id}">Eliminar</button>
                </div></td>
            </tr>`;
        }).join("");
        emptyList.hidden = filtered.length > 0;
        app.querySelector("[data-visible-count]").textContent = String(filtered.length);
        app.querySelector("[data-count-total]").textContent = String(reservations.length);
        app.querySelector("[data-count-pending]").textContent = String(reservations.filter((item) => item.estado === "PENDIENTE_PAGO").length);
        app.querySelector("[data-count-confirmed]").textContent = String(reservations.filter((item) => ["CONFIRMADA", "EN_PREPARACION"].includes(item.estado)).length);
        app.querySelector("[data-count-ready]").textContent = String(reservations.filter((item) => item.estado === "LISTA").length);
    }

    async function loadReservations() {
        loading.hidden = false;
        try {
            const result = await readResponse(await fetch("/api/admin/reservas"));
            reservations = result;
            render();
        } catch (error) {
            showMessage(error.message, true);
            emptyList.hidden = false;
        } finally {
            loading.hidden = true;
        }
    }

    function openEdit(reservation) {
        const date = new Date(String(reservation.fecha_retiro).replace(" ", "T"));
        const minimumPickup = new Date();
        minimumPickup.setDate(minimumPickup.getDate() + 5);
        const minimumPickupDate = [
            minimumPickup.getFullYear(),
            String(minimumPickup.getMonth() + 1).padStart(2, "0"),
            String(minimumPickup.getDate()).padStart(2, "0")
        ].join("-");
        const localDate = [
            date.getFullYear(),
            String(date.getMonth() + 1).padStart(2, "0"),
            String(date.getDate()).padStart(2, "0")
        ].join("-");
        editForm.elements.fecha.min = localDate < minimumPickupDate
            ? localDate
            : minimumPickupDate;
        const localTime = `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
        editForm.elements.id.value = reservation.id;
        editForm.elements.nombre_cliente.value = reservation.cliente;
        editForm.elements.telefono.value = reservation.telefono;
        editForm.elements.cantidad.value = reservation.cantidad;
        editForm.elements.fecha.value = localDate;
        editForm.elements.hora.value = localTime;
        editForm.elements.estado.value = reservation.estado;
        editForm.elements.estado.disabled = reservation.estado === "CANCELADA";
        document.querySelector("[data-edit-code]").textContent = reservation.codigo;
        dialog.showModal();
    }

    search.addEventListener("input", render);
    statusFilter.addEventListener("change", render);
    app.addEventListener("click", async (event) => {
        const button = event.target.closest("button");
        if (!button) return;

        if (button.dataset.edit) {
            const reservation = reservations.find((item) => item.id === Number(button.dataset.edit));
            if (reservation) openEdit(reservation);
            return;
        }
        if (button.dataset.delete) {
            if (!window.confirm("¿Eliminar esta reserva y su registro de pago? Esta acción no se puede deshacer.")) return;
            try {
                await readResponse(await fetch(`/api/admin/reservas/${button.dataset.delete}`, {
                    method: "DELETE",
                    headers: { "X-CSRF-Token": csrfToken }
                }));
                showMessage("La reserva fue eliminada.");
                await loadReservations();
            } catch (error) {
                showMessage(error.message, true);
            }
            return;
        }
        if (button.dataset.pay) {
            if (!window.confirm("Confirma que el cliente ya pagó el anticipo en efectivo en la tienda.")) return;
            try {
                await readResponse(await fetch(`/api/admin/reservas/${button.dataset.pay}/marcar-pago`, {
                    method: "POST",
                    headers: { "X-CSRF-Token": csrfToken }
                }));
                showMessage("Anticipo registrado y reserva confirmada.");
                await loadReservations();
            } catch (error) {
                showMessage(error.message, true);
            }
        }
    });

    document.querySelector("[data-cancel-edit]").addEventListener("click", () => dialog.close());
    editForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = new FormData(editForm);
        const fechaRetiro = `${form.get("fecha")}T${form.get("hora")}:00`;
        const updates = {
            nombre_cliente: form.get("nombre_cliente"),
            telefono: form.get("telefono"),
            cantidad: Number(form.get("cantidad")),
            fecha_retiro: fechaRetiro,
            estado: editForm.elements.estado.value
        };
        try {
            await readResponse(await fetch(`/api/admin/reservas/${editForm.elements.id.value}`, {
                method: "PATCH",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRF-Token": csrfToken
                },
                body: JSON.stringify(updates)
            }));
            dialog.close();
            showMessage("La reserva fue actualizada.");
            await loadReservations();
        } catch (error) {
            showMessage(error.message, true);
        }
    });

    loadReservations();
})();
