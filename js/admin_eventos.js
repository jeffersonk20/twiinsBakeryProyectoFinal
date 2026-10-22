(() => {
    const root = document.querySelector("[data-admin-eventos]");
    if (!root) return;

    const csrfToken = root.dataset.csrfToken;
    const body = root.querySelector("[data-eventos-body]");
    const loading = root.querySelector("[data-loading]");
    const emptyList = root.querySelector("[data-empty-list]");
    const message = root.querySelector("[data-admin-message]");
    const filterButtons = root.querySelectorAll("[data-filter]");
    const rejectDialog = document.querySelector("[data-reject-dialog]");
    const rejectForm = document.querySelector("[data-reject-form]");
    const cancelRejectBtn = document.querySelector("[data-cancel-reject]");
    const rejectIdInput = document.getElementById("reject-solicitud-id");

    let solicitudes = [];
    let currentFilter = "NUEVA";

    function showMessage(text, isError = false) {
        message.textContent = text;
        message.classList.toggle("error", isError);
        message.hidden = false;
        window.setTimeout(() => {
            message.hidden = true;
        }, 5500);
    }

    function formatDate(raw) {
        if (!raw) return "—";
        // Handle format 'YYYY-MM-DD'
        const parts = String(raw).split("-");
        if (parts.length === 3) {
            return `${parts[2]}/${parts[1]}/${parts[0]}`;
        }
        return raw;
    }

    function formatCurrency(val) {
        if (val === null || val === undefined || val === "") return "—";
        const num = Number(val);
        if (Number.isNaN(num)) return `$${val}`;
        return new Intl.NumberFormat("en-US", {
            style: "currency",
            currency: "USD",
            maximumFractionDigits: 0
        }).format(num);
    }

    function render() {
        const filtered = solicitudes.filter(sol => {
            if (currentFilter === "TODAS") return true;
            return sol.estado === currentFilter;
        });

        if (filtered.length === 0) {
            body.innerHTML = "";
            emptyList.hidden = false;
            return;
        }

        emptyList.hidden = true;
        body.innerHTML = filtered.map(sol => {
            let actionHtml = "";
            if (sol.estado === "NUEVA" || sol.estado === "EN_REVISION") {
                actionHtml = `
                    <div class="actions-cell">
                        <button type="button" class="btn-aceptar" data-accept-id="${sol.id_solicitud}">
                            ✓ Aceptar
                        </button>
                        <button type="button" class="btn-rechazar" data-reject-id="${sol.id_solicitud}">
                            ✕ Rechazar
                        </button>
                    </div>
                `;
            } else if (sol.estado === "ACEPTADA") {
                actionHtml = `
                    <div class="actions-cell">
                        <span class="badge-estado aceptada">Aceptada</span>
                        <a href="/admin/chat/evento/${sol.id_chat_evento}" class="btn-chat-evento">
                            💬 Ir al chat
                        </a>
                    </div>
                `;
            } else if (sol.estado === "RECHAZADA") {
                actionHtml = `
                    <div class="actions-cell">
                        <span class="badge-estado rechazada">Rechazada</span>
                    </div>
                `;
            }

            return `
                <tr data-row-id="${sol.id_solicitud}">
                    <td class="cell-cliente">
                        <strong>${escapeHtml(sol.cliente)}</strong>
                        <small>${escapeHtml(sol.correo || '')}${sol.telefono ? ' · ' + escapeHtml(sol.telefono) : ''}</small>
                    </td>
                    <td class="cell-evento">${escapeHtml(sol.tipo_evento)}</td>
                    <td class="cell-fecha">${escapeHtml(formatDate(sol.fecha_evento))}</td>
                    <td class="cell-invitados">${escapeHtml(String(sol.num_invitados))}</td>
                    <td class="cell-presupuesto">${escapeHtml(formatCurrency(sol.presupuesto_estimado))}</td>
                    <td class="text-right">${actionHtml}</td>
                </tr>
            `;
        }).join("");
    }

    function escapeHtml(value) {
        return String(value ?? "").replace(/[&<>"']/g, char => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;"
        })[char]);
    }

    async function loadSolicitudes() {
        loading.hidden = false;
        emptyList.hidden = true;
        try {
            const res = await fetch("/api/admin/eventos");
            if (!res.ok) throw new Error("No se pudieron cargar las solicitudes.");
            solicitudes = await res.json();
            render();
        } catch (err) {
            showMessage(err.message || "Error al cargar solicitudes.", true);
        } finally {
            loading.hidden = true;
        }
    }

    // Filtros de píldoras
    filterButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            filterButtons.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentFilter = btn.dataset.filter;
            render();
        });
    });

    // Delegación de eventos para botones Aceptar / Rechazar
    body.addEventListener("click", async (e) => {
        const acceptBtn = e.target.closest("[data-accept-id]");
        if (acceptBtn) {
            const id = acceptBtn.dataset.acceptId;
            acceptBtn.disabled = true;
            acceptBtn.textContent = "Aceptando…";

            try {
                const res = await fetch(`/api/admin/eventos/${id}/aceptar`, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-CSRF-Token": csrfToken
                    }
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || "No se pudo aceptar la solicitud.");

                showMessage(data.mensaje || "Solicitud aceptada correctamente. Redirigiendo al chat...");

                // Redirigir directamente a la pantalla de Chat-Evento
                if (data.redirect_url) {
                    window.location.href = data.redirect_url;
                } else {
                    await loadSolicitudes();
                }
            } catch (err) {
                showMessage(err.message || "Error al aceptar solicitud.", true);
                acceptBtn.disabled = false;
                acceptBtn.textContent = "✓ Aceptar";
            }
            return;
        }

        const rejectBtn = e.target.closest("[data-reject-id]");
        if (rejectBtn) {
            const id = rejectBtn.dataset.rejectId;
            rejectIdInput.value = id;
            if (typeof rejectDialog.showModal === "function") {
                rejectDialog.showModal();
            } else {
                rejectDialog.setAttribute("open", "true");
            }
        }
    });

    if (cancelRejectBtn) {
        cancelRejectBtn.addEventListener("click", () => {
            if (typeof rejectDialog.close === "function") {
                rejectDialog.close();
            } else {
                rejectDialog.removeAttribute("open");
            }
        });
    }

    if (rejectForm) {
        rejectForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const id = rejectIdInput.value;
            const motivo = document.getElementById("reject-motivo").value;

            if (typeof rejectDialog.close === "function") {
                rejectDialog.close();
            } else {
                rejectDialog.removeAttribute("open");
            }

            try {
                const res = await fetch(`/api/admin/eventos/${id}/rechazar`, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-CSRF-Token": csrfToken
                    },
                    body: JSON.stringify({ motivo })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || "No se pudo rechazar la solicitud.");
                showMessage(data.mensaje || "Solicitud rechazada y correo enviado.");
                await loadSolicitudes();
            } catch (err) {
                showMessage(err.message || "Error al procesar el rechazo.", true);
            }
        });
    }

    loadSolicitudes();
})();
