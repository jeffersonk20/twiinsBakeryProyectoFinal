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
    const rejectDialog = document.querySelector("[data-reject-dialog]");
    const rejectForm = document.querySelector("[data-reject-form]");
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
            const paymentPending = reservation.pago_estado === "PENDIENTE"
                || Number(reservation.monto_pagado || 0) < Number(reservation.anticipo_requerido || 0);
            const canConfirm = reservation.estado === "PENDIENTE_PAGO" && reservation.estado !== "CANCELADA";
            const canReject = !["CANCELADA", "ENTREGADA"].includes(reservation.estado);
            const canMarkReady = ["CONFIRMADA", "EN_PREPARACION"].includes(reservation.estado);
            const isReady = reservation.estado === "LISTA";
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
                    ${canConfirm ? `<button type="button" class="confirm-action" data-confirm="${reservation.id}" title="Confirmar reserva tras recibir el anticipo en tienda y avisar al cliente">✓ Confirmar reserva</button>` : ""}
                    ${canMarkReady ? `<button type="button" class="ready-action" data-ready="${reservation.id}" title="Avisar al cliente que su pedido ya está listo para retirar">🔔 Avisar lista</button>` : ""}
                    ${isReady ? `<button type="button" class="ready-again-action" data-ready="${reservation.id}" title="Reenviar aviso por correo al cliente">✉️ Reenviar aviso</button>` : ""}
                    ${canReject ? `<button type="button" class="reject-action" data-reject="${reservation.id}" title="Rechazar esta reserva y notificar por correo al cliente">✕ Rechazar</button>` : ""}
                    <button type="button" class="delete-action" data-delete="${reservation.id}" title="Eliminar reserva del sistema">Eliminar</button>
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
        const localDate = [
            date.getFullYear(),
            String(date.getMonth() + 1).padStart(2, "0"),
            String(date.getDate()).padStart(2, "0")
        ].join("-");
        const localTime = `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
        editForm.elements.id.value = reservation.id;
        editForm.elements.nombre_cliente.value = reservation.cliente;
        if (editForm.elements.correo) editForm.elements.correo.value = reservation.correo || "";
        editForm.elements.telefono.value = reservation.telefono;
        editForm.elements.cantidad.value = reservation.cantidad;
        editForm.elements.fecha.value = localDate;
        editForm.elements.hora.value = localTime;
        editForm.elements.estado.value = reservation.estado;
        editForm.elements.estado.disabled = false;
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

        const confirmId = button.dataset.confirm || button.dataset.pay;
        if (confirmId) {
            const reservation = reservations.find((item) => item.id === Number(confirmId));
            const codigo = reservation ? reservation.codigo : "";
            const cliente = reservation ? reservation.cliente : "el cliente";
            const correo = reservation ? reservation.correo : "";
            const msgConfirm = correo
                ? `¿Confirmar la recepción del anticipo para la reserva ${codigo} de ${cliente}?\n\nSe marcará como Confirmada y se enviará un correo a su Gmail (${correo}).`
                : `¿Confirmar la recepción del anticipo para la reserva ${codigo}?`;

            if (!window.confirm(msgConfirm)) return;

            const originalText = button.innerHTML;
            button.disabled = true;
            button.textContent = "Confirmando…";

            try {
                const result = await readResponse(await fetch(`/api/admin/reservas/${confirmId}/confirmar`, {
                    method: "POST",
                    headers: { "X-CSRF-Token": csrfToken }
                }));
                showMessage(result.mensaje || "Anticipo registrado y reserva confirmada.");
                await loadReservations();
            } catch (error) {
                showMessage(error.message, true);
                button.disabled = false;
                button.innerHTML = originalText;
            }
            return;
        }

        if (button.dataset.reject) {
            const reservation = reservations.find((item) => item.id === Number(button.dataset.reject));
            if (!reservation) return;

            if (rejectDialog && rejectForm) {
                rejectForm.elements.reserva_id.value = reservation.id;
                const codeSpan = document.querySelector("[data-reject-code]");
                if (codeSpan) codeSpan.textContent = reservation.codigo;
                rejectForm.elements.motivo.value = "";
                rejectDialog.showModal();
            } else {
                const motivo = window.prompt(
                    `¿Deseas rechazar la reserva ${reservation.codigo} de ${reservation.cliente}?\n\nPuedes ingresar un motivo que se notificará por correo:`,
                    "Disponibilidad limitada en agenda para la fecha o anticipo no recibido a tiempo."
                );
                if (motivo === null) return;
                try {
                    const result = await readResponse(await fetch(`/api/admin/reservas/${reservation.id}/rechazar`, {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json",
                            "X-CSRF-Token": csrfToken
                        },
                        body: JSON.stringify({ motivo })
                    }));
                    showMessage(result.mensaje || "Reserva rechazada y cliente notificado.");
                    await loadReservations();
                } catch (error) {
                    showMessage(error.message, true);
                }
            }
            return;
        }

        if (button.dataset.ready) {
            const reservation = reservations.find((item) => item.id === Number(button.dataset.ready));
            const codigo = reservation ? reservation.codigo : "";
            const cliente = reservation ? reservation.cliente : "el cliente";
            const correo = reservation ? reservation.correo : "";
            const msgConfirm = correo
                ? `¿Avisar a ${cliente} (${correo}) que la reserva ${codigo} está lista para retirar?\nSe le enviará una notificación por correo electrónico.`
                : `¿Marcar la reserva ${codigo} como lista para retirar?`;

            if (!window.confirm(msgConfirm)) return;

            const originalText = button.innerHTML;
            button.disabled = true;
            button.textContent = "Avisando…";

            try {
                const result = await readResponse(await fetch(`/api/admin/reservas/${button.dataset.ready}/marcar-lista`, {
                    method: "POST",
                    headers: { "X-CSRF-Token": csrfToken }
                }));
                showMessage(result.mensaje || "Reserva lista y notificación enviada al cliente.");
                await loadReservations();
            } catch (error) {
                showMessage(error.message, true);
                button.disabled = false;
                button.innerHTML = originalText;
            }
            return;
        }

        if (button.dataset.delete) {
            const reservation = reservations.find((item) => item.id === Number(button.dataset.delete));
            const codigo = reservation ? reservation.codigo : "";
            if (!window.confirm(`¿Eliminar la reserva ${codigo} y todos sus registros asociados? Esta acción no se puede deshacer.`)) return;
            try {
                const result = await readResponse(await fetch(`/api/admin/reservas/${button.dataset.delete}`, {
                    method: "DELETE",
                    headers: { "X-CSRF-Token": csrfToken }
                }));
                showMessage(result.mensaje || "La reserva fue eliminada.");
                await loadReservations();
            } catch (error) {
                showMessage(error.message, true);
            }
            return;
        }
    });

    document.querySelector("[data-cancel-edit]").addEventListener("click", () => dialog.close());
    editForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        const form = new FormData(editForm);
        const fechaRetiro = `${form.get("fecha")}T${form.get("hora")}:00`;
        const updates = {
            nombre_cliente: form.get("nombre_cliente"),
            correo: form.get("correo") ? form.get("correo").trim().toLowerCase() : "",
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
            showMessage("La reserva fue actualizada exitosamente.");
            await loadReservations();
        } catch (error) {
            showMessage(error.message, true);
        }
    });

    if (rejectForm) {
        rejectForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            const reservaId = rejectForm.elements.reserva_id.value;
            const motivo = rejectForm.elements.motivo.value.trim();
            const submitBtn = rejectForm.querySelector("button[type='submit']");
            const originalText = submitBtn ? submitBtn.textContent : "";
            if (submitBtn) {
                submitBtn.disabled = true;
                submitBtn.textContent = "Procesando…";
            }
            try {
                const result = await readResponse(await fetch(`/api/admin/reservas/${reservaId}/rechazar`, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-CSRF-Token": csrfToken
                    },
                    body: JSON.stringify({ motivo })
                }));
                if (rejectDialog) rejectDialog.close();
                showMessage(result.mensaje || "Reserva rechazada y notificación enviada al cliente.");
                await loadReservations();
            } catch (error) {
                showMessage(error.message, true);
            } finally {
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.textContent = originalText;
                }
            }
        });
    }

    const cancelReject = document.querySelector("[data-cancel-reject]");
    if (cancelReject && rejectDialog) {
        cancelReject.addEventListener("click", () => rejectDialog.close());
    }

    loadReservations();
})();
