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
    const cardChargeDialog = document.querySelector("[data-card-charge-dialog]");
    const cardChargeForm = document.querySelector("[data-card-charge-form]");
    const cancelCardCharge = document.querySelector("[data-cancel-card-charge]");
    const cardResultBox = document.querySelector("[data-card-result-box]");
    const btnCopiarEnlace = document.getElementById("btnCopiarEnlaceWompi");
    const btnVerificarPagoWompi = document.getElementById("btnVerificarPagoWompi");
    const verificarWompiStatus = document.getElementById("verificarWompiStatus");
    const qrCodeImg = document.getElementById("qrCodeImg");
    const btnConfirmarManualPOS = document.getElementById("btnConfirmarManualPOS");
    const btnConfirmarManualWompi = document.getElementById("btnConfirmarManualWompi");
    const btnQuickAnticipo = document.getElementById("btnQuickAnticipo");
    const btnQuickSaldo = document.getElementById("btnQuickSaldo");
    const cardChargeMonto = document.getElementById("card-charge-monto");
    let reservations = [];
    let currentWompiUrl = "";
    let wompiCheckTimer = null;

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
        if (value === "WOMPI_POS") return "Tarjeta · POS tienda";
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
            const total = Number(reservation.total || 0);
            const pagado = Number(reservation.monto_pagado || 0);
            const anticipo = Number(reservation.anticipo_requerido || (total / 2) || 0);
            const saldoPendiente = Math.max(0, total - pagado);

            const anticipoPagado = pagado >= (anticipo - 0.01) || pagado >= ((total * 0.5) - 0.01);
            let displayStatusText = statusNames[reservation.estado] || reservation.estado;
            let displayStateClass = statusClasses[reservation.estado] || "";

            if (reservation.estado === "PENDIENTE_PAGO") {
                if (pagado >= total && total > 0) {
                    displayStatusText = "Pago 100% · Por confirmar";
                    displayStateClass = "pending-acceptance";
                } else if (anticipoPagado && (anticipo > 0 || total > 0)) {
                    displayStatusText = "Anticipo pagado · Por confirmar";
                    displayStateClass = "pending-acceptance";
                } else {
                    displayStatusText = "Pendiente de anticipo";
                    displayStateClass = "pending";
                }
            }

            const canConfirm = reservation.estado === "PENDIENTE_PAGO" && reservation.estado !== "CANCELADA";
            const canReject = !["CANCELADA", "ENTREGADA"].includes(reservation.estado);
            const canMarkReady = ["CONFIRMADA", "EN_PREPARACION"].includes(reservation.estado);
            const isReady = reservation.estado === "LISTA";
            const hasPendingBalance = saldoPendiente > 0.01 && !["CANCELADA", "ENTREGADA"].includes(reservation.estado);

            const paymentPending = reservation.pago_estado === "PENDIENTE" || !anticipoPagado;
            let paidLabel = "Pendiente";
            let paidSub = "";
            let paymentClass = "";

            if (pagado >= total) {
                paidLabel = "✓ Pago completo (100%)";
                paidSub = `Total liquidado (${formatPrice(pagado)})`;
                paymentClass = "paid total-paid";
            } else if (anticipoPagado) {
                paidLabel = "✓ Anticipo 50% pagado";
                paidSub = `Pagado: ${formatPrice(pagado)} · Resta: ${formatPrice(saldoPendiente)}`;
                paymentClass = "paid";
            } else if (pagado > 0) {
                paidLabel = "Abono parcial";
                paidSub = `Pagado: ${formatPrice(pagado)} · Falta anticipo: ${formatPrice(Math.max(0, anticipo - pagado))}`;
                paymentClass = "partial";
            } else {
                paidLabel = "Sin pagos";
                paidSub = `Anticipo req: ${formatPrice(anticipo)}`;
                paymentClass = "pending";
            }

            const confirmBtnText = anticipoPagado ? "✓ Aceptar reserva" : "✓ Confirmar anticipo";
            const confirmBtnTitle = anticipoPagado
                ? "Aceptar reserva (anticipo o total pagado; pasar a Confirmada y avisar al cliente)"
                : "Confirmar reserva tras recibir el anticipo en tienda y avisar al cliente";

            return `<tr>
                <td><div class="reservation-id">
                    <strong>${escapeHtml(reservation.codigo)}</strong>
                    ${reservation.es_canje_fidelidad ? `<span style="background:#fdf2f8;color:#db2777;border:1px solid #fbcfe8;font-size:10.5px;font-weight:700;padding:2px 8px;border-radius:10px;display:inline-block;margin:2px 0;">🎁 Canje Fidelidad (-${reservation.puntos_usados || 0} pts)</span>` : ''}
                    <span>${escapeHtml(reservation.cliente)}</span>
                    <span>${escapeHtml(reservation.correo)}</span>
                </div></td>
                <td><div class="product-cell">
                    <strong>${escapeHtml(reservation.producto)}</strong>
                    ${(reservation.producto && reservation.producto.toLowerCase().includes("porcion")) ? `<span style="background:#fdf2f8;color:#be185d;border:1px solid #fbcfe8;font-size:10px;font-weight:700;padding:1px 6px;border-radius:8px;display:inline-block;margin:2px 0;">🍰 Porciones</span><br>` : ''}
                    <span>${reservation.cantidad} ${(reservation.producto && reservation.producto.toLowerCase().includes("porcion")) ? "porción(es)" : "unidad(es)"} · ${formatPrice(reservation.precio_unitario)} c/u</span>
                </div></td>
                <td>${displayDate(reservation.fecha_retiro)}</td>
                <td><div class="amount-cell">
                    <strong>${formatPrice(reservation.total)}</strong>
                    <span>Pagado: ${formatPrice(pagado)}</span>
                    ${saldoPendiente > 0.01 
                        ? `<span style="color:#b45309;font-weight:600;font-size:11px;">Saldo: ${formatPrice(saldoPendiente)}</span>`
                        : `<span style="color:#15803d;font-weight:600;font-size:11px;">✓ 100% Pagado</span>`}
                </div></td>
                <td><span class="status-pill ${displayStateClass}">${escapeHtml(displayStatusText)}</span></td>
                <td><span class="payment-state ${paymentClass}">${paidLabel}</span><span class="muted-cell">${escapeHtml(paymentName(reservation.metodo_pago))} · ${paidSub}</span></td>
                <td><div class="row-actions">
                    <button type="button" data-edit="${reservation.id}">Editar</button>
                    ${canConfirm ? `<button type="button" class="confirm-action" data-confirm="${reservation.id}" title="${escapeHtml(confirmBtnTitle)}">${confirmBtnText}</button>` : ""}
                    ${hasPendingBalance ? `<button type="button" class="card-pay-action" data-card-charge="${reservation.id}" title="Realizar cobro con tarjeta mediante Wompi en tienda">💳 Cobrar con tarjeta</button>` : ""}
                    ${hasPendingBalance ? `<button type="button" class="liquidate-action" data-liquidate="${reservation.id}" data-saldo="${saldoPendiente.toFixed(2)}" data-codigo="${escapeHtml(reservation.codigo)}" data-cliente="${escapeHtml(reservation.cliente)}" title="Registrar pago completo del saldo pendiente ($${saldoPendiente.toFixed(2)})">💰 Liquidar saldo ($${saldoPendiente.toFixed(2)})</button>` : ""}
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
        app.querySelector("[data-count-pending]").textContent = String(
            reservations.filter((item) => {
                const tot = Number(item.total || 0);
                const pag = Number(item.monto_pagado || 0);
                const ant = Number(item.anticipo_requerido || (tot / 2) || 0);
                const pagadoAnt = pag >= (ant - 0.01) || pag >= ((tot * 0.5) - 0.01);
                return item.estado === "PENDIENTE_PAGO" && !pagadoAnt;
            }).length
        );
        app.querySelector("[data-count-confirmed]").textContent = String(
            reservations.filter((item) => {
                const tot = Number(item.total || 0);
                const pag = Number(item.monto_pagado || 0);
                const ant = Number(item.anticipo_requerido || (tot / 2) || 0);
                const pagadoAnt = pag >= (ant - 0.01) || pag >= ((tot * 0.5) - 0.01);
                return ["CONFIRMADA", "EN_PREPARACION"].includes(item.estado) || (item.estado === "PENDIENTE_PAGO" && pagadoAnt);
            }).length
        );
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

        if (button.dataset.cardCharge) {
            const reservation = reservations.find((item) => item.id === Number(button.dataset.cardCharge));
            if (!reservation || !cardChargeDialog) return;

            const total = Number(reservation.total || 0);
            const anticipo = Number(reservation.anticipo_requerido || (total / 2) || 0);
            const pagado = Number(reservation.monto_pagado || 0);
            const saldo = Math.max(0, total - pagado);
            const anticipoFaltante = Math.max(0, anticipo - pagado);
            const anticipoYaCubierto = anticipoFaltante <= 0.01;

            document.querySelector("[data-card-code]").textContent = reservation.codigo;
            document.querySelector("[data-card-customer]").textContent = reservation.cliente;
            document.querySelector("[data-card-total]").textContent = formatPrice(total);
            document.querySelector("[data-card-anticipo]").textContent = formatPrice(anticipo);
            document.querySelector("[data-card-paid]").textContent = formatPrice(pagado);
            document.querySelector("[data-card-pending]").textContent = formatPrice(saldo);

            document.getElementById("card-charge-reserva-id").value = reservation.id;
            cardChargeMonto.max = saldo.toFixed(2);

            const activarBotonMonto = (esAnticipo) => {
                if (esAnticipo) {
                    if (btnQuickAnticipo && !btnQuickAnticipo.disabled) {
                        btnQuickAnticipo.classList.add("active-choice");
                        if (btnQuickSaldo) btnQuickSaldo.classList.remove("active-choice");
                        cardChargeMonto.value = anticipoFaltante.toFixed(2);
                    }
                } else {
                    if (btnQuickSaldo) {
                        btnQuickSaldo.classList.add("active-choice");
                        if (btnQuickAnticipo) btnQuickAnticipo.classList.remove("active-choice");
                        cardChargeMonto.value = saldo.toFixed(2);
                    }
                }
            };

            if (anticipoYaCubierto) {
                // El anticipo ya fue cubierto: desactivar el botón de 50% y enfocar solo en el saldo restante
                if (btnQuickAnticipo) {
                    btnQuickAnticipo.disabled = true;
                    btnQuickAnticipo.textContent = "✓ Anticipo 50% ya cubierto";
                    btnQuickAnticipo.classList.remove("active-choice");
                    btnQuickAnticipo.classList.add("disabled-choice");
                    btnQuickAnticipo.onclick = null;
                }
                if (btnQuickSaldo) {
                    btnQuickSaldo.disabled = false;
                    btnQuickSaldo.textContent = `Cobrar saldo restante ($${saldo.toFixed(2)})`;
                    btnQuickSaldo.onclick = () => activarBotonMonto(false);
                }
                activarBotonMonto(false);
            } else {
                // Aún no cubre el anticipo: habilitar ambas opciones, por defecto anticipo
                if (btnQuickAnticipo) {
                    btnQuickAnticipo.disabled = false;
                    btnQuickAnticipo.textContent = `Cobrar anticipo 50% ($${anticipoFaltante.toFixed(2)})`;
                    btnQuickAnticipo.classList.remove("disabled-choice");
                    btnQuickAnticipo.onclick = () => activarBotonMonto(true);
                }
                if (btnQuickSaldo) {
                    btnQuickSaldo.disabled = false;
                    btnQuickSaldo.textContent = `Cobrar total completo ($${saldo.toFixed(2)})`;
                    btnQuickSaldo.onclick = () => activarBotonMonto(false);
                }
                activarBotonMonto(true);
            }

            cardChargeMonto.oninput = () => {
                const val = parseFloat(cardChargeMonto.value || 0);
                if (!anticipoYaCubierto && Math.abs(val - anticipoFaltante) < 0.01) {
                    btnQuickAnticipo?.classList.add("active-choice");
                    btnQuickSaldo?.classList.remove("active-choice");
                } else if (Math.abs(val - saldo) < 0.01) {
                    btnQuickSaldo?.classList.add("active-choice");
                    btnQuickAnticipo?.classList.remove("active-choice");
                } else {
                    btnQuickAnticipo?.classList.remove("active-choice");
                    btnQuickSaldo?.classList.remove("active-choice");
                }
            };

            if (cardResultBox) cardResultBox.style.display = "none";
            const genBtn = document.getElementById("btnGenerarEnlaceWompi");
            if (genBtn) {
                genBtn.disabled = false;
                genBtn.textContent = "💳 Generar enlace Wompi";
            }

            cardChargeDialog.showModal();
            return;
        }

        const liquidateId = button.dataset.liquidate;
        if (liquidateId) {
            const saldo = button.dataset.saldo;
            const codigo = button.dataset.codigo;
            const cliente = button.dataset.cliente;
            const msgConfirm = `¿Registrar la liquidación completa del saldo pendiente ($${saldo}) para la reserva ${codigo} de ${cliente}?\n\nLa reserva quedará 100% pagada en el sistema.`;
            if (!window.confirm(msgConfirm)) return;

            button.disabled = true;
            const origText = button.textContent;
            button.textContent = "Liquidando…";

            try {
                const result = await readResponse(await fetch(`/api/admin/reservas/${liquidateId}/liquidar-pago`, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-CSRF-Token": csrfToken
                    },
                    body: JSON.stringify({ metodo_pago: "EFECTIVO_TIENDA" })
                }));
                showMessage(result.mensaje || `¡Saldo restante de $${saldo} liquidado con éxito!`);
                await loadReservations();
            } catch (err) {
                showMessage(err.message, true);
                button.disabled = false;
                button.textContent = origText;
            }
            return;
        }

        const confirmId = button.dataset.confirm || button.dataset.pay;
        if (confirmId) {
            const reservation = reservations.find((item) => item.id === Number(confirmId));
            const codigo = reservation ? reservation.codigo : "";
            const cliente = reservation ? reservation.cliente : "el cliente";
            const correo = reservation ? reservation.correo : "";
            const msgConfirm = correo
                ? `¿Aceptar y confirmar la reserva ${codigo} de ${cliente}?\n\nSe pasará al estado Confirmada y se enviará un correo a su cuenta (${correo}).`
                : `¿Aceptar y confirmar la reserva ${codigo}?`;

            if (!window.confirm(msgConfirm)) return;

            const originalText = button.innerHTML;
            button.disabled = true;
            button.textContent = "Confirmando…";

            try {
                const result = await readResponse(await fetch(`/api/admin/reservas/${confirmId}/confirmar`, {
                    method: "POST",
                    headers: { "X-CSRF-Token": csrfToken }
                }));
                showMessage(result.mensaje || `Reserva ${codigo} confirmada exitosamente.`);
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

    // GESTIÓN DE COBRO CON TARJETA (WOMPI) EN PANEL ADMIN
    if (cardChargeForm) {
        cardChargeForm.addEventListener("submit", async (event) => {
            event.preventDefault();
            const reservaId = document.getElementById("card-charge-reserva-id").value;
            const monto = parseFloat(cardChargeMonto.value);
            const genBtn = document.getElementById("btnGenerarEnlaceWompi");

            if (!monto || monto <= 0) {
                alert("Por favor ingresa un monto válido mayor a 0.");
                return;
            }

            if (genBtn) {
                genBtn.disabled = true;
                genBtn.textContent = "Conectando con Wompi…";
            }

            try {
                const result = await readResponse(await fetch(`/api/admin/reservas/${reservaId}/cobro-tarjeta`, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-CSRF-Token": csrfToken
                    },
                    body: JSON.stringify({ monto })
                }));

                currentWompiUrl = result.url_pago;
                if (cardResultBox) {
                    cardResultBox.style.display = "block";
                    document.querySelector("[data-result-amount]").textContent = formatPrice(result.monto);
                    if (qrCodeImg) {
                        qrCodeImg.src = `https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=${encodeURIComponent(result.url_pago)}`;
                    }
                }
                showMessage("Enlace de cobro Wompi generado con éxito.");
                iniciarVerificacionWompi(reservaId);
            } catch (error) {
                showMessage(error.message, true);
            } finally {
                if (genBtn) {
                    genBtn.disabled = false;
                    genBtn.textContent = "💳 Generar enlace Wompi";
                }
            }
        });
    }

    function detenerVerificacionWompi() {
        if (wompiCheckTimer) {
            clearInterval(wompiCheckTimer);
            wompiCheckTimer = null;
        }
    }

    async function chequearPagoWompi(reservaId, manual = false) {
        if (!reservaId) return;
        if (verificarWompiStatus) {
            verificarWompiStatus.textContent = "Consultando estado con Wompi…";
            verificarWompiStatus.style.color = "#2b6cb0";
        }
        try {
            const resp = await fetch(`/api/admin/reservas/${reservaId}/verificar-pago-wompi`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRF-Token": csrfToken
                }
            });
            const data = await resp.json();
            if (data.pagado) {
                detenerVerificacionWompi();
                if (cardChargeDialog) cardChargeDialog.close();
                showMessage(data.mensaje || "¡Pago completado con éxito en Wompi!");
                await loadReservations();
                return true;
            } else {
                if (verificarWompiStatus) {
                    verificarWompiStatus.textContent = manual
                        ? "Wompi informa: El cliente aún no ha completado el pago."
                        : "Esperando pago… (comprobando con Wompi cada 3s)";
                    verificarWompiStatus.style.color = manual ? "#c53030" : "#64748b";
                }
            }
        } catch (err) {
            if (manual && verificarWompiStatus) {
                verificarWompiStatus.textContent = "No se pudo consultar Wompi. Intenta de nuevo.";
                verificarWompiStatus.style.color = "#c53030";
            }
        }
        return false;
    }

    function iniciarVerificacionWompi(reservaId) {
        detenerVerificacionWompi();
        if (verificarWompiStatus) {
            verificarWompiStatus.textContent = "Esperando pago… (comprobando con Wompi en tiempo real)";
            verificarWompiStatus.style.color = "#64748b";
        }
        // Consulta inmediata a los 2 segundos, luego cada 3.5 segundos
        wompiCheckTimer = setInterval(() => {
            chequearPagoWompi(reservaId, false);
        }, 3500);
    }

    if (btnVerificarPagoWompi) {
        btnVerificarPagoWompi.addEventListener("click", async () => {
            const reservaId = document.getElementById("card-charge-reserva-id").value;
            btnVerificarPagoWompi.disabled = true;
            const originalTxt = btnVerificarPagoWompi.textContent;
            btnVerificarPagoWompi.textContent = "Comprobando…";
            await chequearPagoWompi(reservaId, true);
            btnVerificarPagoWompi.disabled = false;
            btnVerificarPagoWompi.textContent = originalTxt;
        });
    }

    if (btnCopiarEnlace) {
        btnCopiarEnlace.addEventListener("click", async () => {
            if (!currentWompiUrl) return;
            try {
                await navigator.clipboard.writeText(currentWompiUrl);
                const oldText = btnCopiarEnlace.textContent;
                btnCopiarEnlace.textContent = "✓ ¡Enlace copiado al portapapeles!";
                setTimeout(() => {
                    btnCopiarEnlace.textContent = oldText;
                }, 2500);
            } catch {
                prompt("Copia este enlace de pago:", currentWompiUrl);
            }
        });
    }

    if (btnConfirmarManualPOS) {
        btnConfirmarManualPOS.addEventListener("click", async () => {
            const reservaId = document.getElementById("card-charge-reserva-id").value;
            const monto = parseFloat(cardChargeMonto.value);
            if (!window.confirm(`¿Confirmar que cobraste $${monto.toFixed(2)} con tarjeta presencialmente en el POS físico?`)) return;

            btnConfirmarManualPOS.disabled = true;
            btnConfirmarManualPOS.textContent = "Registrando…";

            try {
                const result = await readResponse(await fetch(`/api/admin/reservas/${reservaId}/marcar-cobro-tarjeta-manual`, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-CSRF-Token": csrfToken
                    },
                    body: JSON.stringify({ monto })
                }));
                if (cardChargeDialog) cardChargeDialog.close();
                showMessage(result.mensaje || "Cobro registrado exitosamente.");
                await loadReservations();
            } catch (error) {
                showMessage(error.message, true);
            } finally {
                btnConfirmarManualPOS.disabled = false;
                btnConfirmarManualPOS.textContent = "✓ Marcar como cobrado en terminal POS físico";
            }
        });
    }

    if (btnConfirmarManualWompi) {
        btnConfirmarManualWompi.addEventListener("click", async () => {
            const reservaId = document.getElementById("card-charge-reserva-id").value;
            const monto = parseFloat(cardChargeMonto.value);
            if (!window.confirm(`¿Confirmar que el cliente ya completó el pago de $${monto.toFixed(2)} en su celular y registrar el pago ahora?`)) return;

            btnConfirmarManualWompi.disabled = true;
            const originalText = btnConfirmarManualWompi.textContent;
            btnConfirmarManualWompi.textContent = "Registrando pago…";

            try {
                const result = await readResponse(await fetch(`/api/admin/reservas/${reservaId}/marcar-cobro-tarjeta-manual`, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-CSRF-Token": csrfToken
                    },
                    body: JSON.stringify({ monto })
                }));
                detenerVerificacionWompi();
                if (cardChargeDialog) cardChargeDialog.close();
                showMessage(result.mensaje || "¡Pago con tarjeta registrado exitosamente!");
                await loadReservations();
            } catch (error) {
                showMessage(error.message, true);
            } finally {
                btnConfirmarManualWompi.disabled = false;
                btnConfirmarManualWompi.textContent = originalText;
            }
        });
    }

    if (cardChargeDialog) {
        cardChargeDialog.addEventListener("close", () => detenerVerificacionWompi());
    }

    if (cancelCardCharge && cardChargeDialog) {
        cancelCardCharge.addEventListener("click", () => {
            detenerVerificacionWompi();
            cardChargeDialog.close();
        });
    }

    loadReservations();
})();
