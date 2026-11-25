/**
 * ADMIN INGRESOS Y FINANZAS - TWIINS BAKERY
 * Lógica interactiva: métricas en tiempo real, gráfica dinámica SVG/CSS,
 * registro de ingresos y restas/egresos, auditoría y modal dinámico sin popups nativos.
 */

(() => {
    "use strict";

    const app = document.querySelector("[data-admin-ingresos]");
    if (!app) return;

    const csrfToken = app.dataset.csrfToken || "";

    // Elementos del DOM
    const periodButtons = document.querySelectorAll(".period-btn");
    const chartBarsViewport = document.querySelector("[data-chart-bars]");
    const chartLoading = document.querySelector("[data-chart-loading]");
    const chartPeriodDesc = document.querySelector("[data-chart-period-desc]");

    // Métricas
    const statNeto = document.querySelector("[data-stat-neto]");
    const statHoy = document.querySelector("[data-stat-hoy]");
    const statSemana = document.querySelector("[data-stat-semana]");
    const statMes = document.querySelector("[data-stat-mes]");
    const statHistorico = document.querySelector("[data-stat-historico]");
    const statTicket = document.querySelector("[data-stat-ticket]");
    const statPedidos = document.querySelector("[data-stat-pedidos]");

    // Desglose
    const bdAnticipos = document.querySelector("[data-breakdown-anticipos]");
    const countAnticipos = document.querySelector("[data-count-anticipos]");
    const bdCompletos = document.querySelector("[data-breakdown-completos]");
    const countCompletos = document.querySelector("[data-count-completos]");
    const bdLiquidaciones = document.querySelector("[data-breakdown-liquidaciones]");
    const countLiquidaciones = document.querySelector("[data-count-liquidaciones]");
    const bdCanceladas = document.querySelector("[data-breakdown-canceladas]");
    const countCanceladas = document.querySelector("[data-count-canceladas]");
    const bdManualesIngreso = document.querySelector("[data-breakdown-manuales-ingreso]");
    const bdRestas = document.querySelector("[data-breakdown-restas]");

    // Balance lateral
    const sideBruto = document.querySelector("[data-side-bruto]");
    const sideRestas = document.querySelector("[data-side-restas]");
    const sideNeto = document.querySelector("[data-side-neto]");

    // Transacciones
    const txBody = document.querySelector("[data-transactions-body]");
    const txCount = document.querySelector("[data-transactions-count]");
    const txSearch = document.querySelector("[data-tx-search]");
    const txTypeFilter = document.querySelector("[data-tx-type-filter]");
    const txEmpty = document.querySelector("[data-tx-empty]");
    const txLoading = document.querySelector("[data-tx-loading]");

    // Modal de registro de movimiento
    const modalMovimiento = document.getElementById("modalMovimiento");
    const btnNuevoMovimiento = document.getElementById("btnNuevoMovimiento");
    const btnSideRegistrar = document.getElementById("btnSideRegistrar");
    const btnCerrarModalMovimiento = document.getElementById("btnCerrarModalMovimiento");
    const btnCancelarMovimiento = document.getElementById("btnCancelarMovimiento");
    const formMovimiento = document.getElementById("formMovimiento");
    const radioTipos = formMovimiento ? formMovimiento.querySelectorAll('input[name="tipo_movimiento"]') : [];
    const btnGuardarMovimiento = document.getElementById("btnGuardarMovimiento");
    const inputCategoria = document.getElementById("movCategoria");

    // Modal dinámico elegante (sustituye window.alert y window.confirm)
    const dynModal = document.getElementById("adminDynamicModal");
    const dynIcon = document.getElementById("adminDynamicModalIcon");
    const dynTitle = document.getElementById("adminDynamicModalTitle");
    const dynMessage = document.getElementById("adminDynamicModalMessage");
    const dynDetails = document.getElementById("adminDynamicModalDetails");
    const dynCancel = document.getElementById("adminDynamicModalCancel");
    const dynConfirm = document.getElementById("adminDynamicModalConfirm");
    let dynResolver = null;

    // Estado local
    let currentPeriod = "semana";
    let cachedData = null;
    let allTransactions = [];

    // Helper formato moneda
    function formatCurrency(amount) {
        const val = Number(amount) || 0;
        return "$" + val.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }

    // Modal dinámico Promise-based
    function mostrarModalDinamico({ icon = "🔔", title = "Aviso", message = "", details = "", showCancel = true, confirmText = "Aceptar", cancelText = "Cancelar" }) {
        return new Promise((resolve) => {
            if (!dynModal) {
                resolve(true);
                return;
            }
            dynResolver = resolve;
            if (dynIcon) dynIcon.textContent = icon;
            if (dynTitle) dynTitle.textContent = title;
            if (dynMessage) dynMessage.textContent = message;

            if (dynDetails) {
                if (details) {
                    dynDetails.textContent = details;
                    dynDetails.style.display = "block";
                } else {
                    dynDetails.style.display = "none";
                }
            }

            if (dynCancel) {
                dynCancel.style.display = showCancel ? "inline-block" : "none";
                dynCancel.textContent = cancelText;
            }
            if (dynConfirm) {
                dynConfirm.textContent = confirmText;
            }

            dynModal.classList.add("is-visible");
            dynModal.setAttribute("aria-hidden", "false");
        });
    }

    function cerrarModalDinamico(resultado = false) {
        if (!dynModal) return;
        dynModal.classList.remove("is-visible");
        dynModal.setAttribute("aria-hidden", "true");
        if (typeof dynResolver === "function") {
            const resolve = dynResolver;
            dynResolver = null;
            resolve(resultado);
        }
    }

    if (dynCancel) dynCancel.addEventListener("click", () => cerrarModalDinamico(false));
    if (dynConfirm) dynConfirm.addEventListener("click", () => cerrarModalDinamico(true));

    // Cargar datos desde la API
    async function cargarDatos(periodo = "semana") {
        currentPeriod = periodo;
        if (chartLoading) chartLoading.style.display = "flex";
        if (txLoading) txLoading.style.display = "block";
        if (txEmpty) txEmpty.hidden = true;

        try {
            const res = await fetch(`/api/admin/ingresos?periodo=${encodeURIComponent(periodo)}`, {
                headers: { "Accept": "application/json" },
                cache: "no-store",
            });

            if (!res.ok) {
                throw new Error("No se pudo obtener la información financiera");
            }

            const data = await res.json();
            cachedData = data;
            allTransactions = data.transacciones || [];

            actualizarMetricas(data);
            renderizarGrafica(data.grafica || []);
            renderizarTransacciones();

            if (chartPeriodDesc) {
                const descMap = {
                    "hoy": "Distribución horaria del día de hoy",
                    "semana": "Evolución diaria de los últimos 7 días",
                    "mes": "Distribución por semanas del mes en curso",
                    "todo": "Resumen histórico mensual",
                };
                chartPeriodDesc.textContent = descMap[periodo] || "Comportamiento del período seleccionado";
            }
        } catch (err) {
            mostrarModalDinamico({
                icon: "⚠️",
                title: "Error al cargar datos",
                message: "No se pudieron obtener los datos de ingresos. Por favor verifica tu conexión o recarga la página.",
                showCancel: false,
                confirmText: "Entendido",
            });
        } finally {
            if (chartLoading) chartLoading.style.display = "none";
            if (txLoading) txLoading.style.display = "none";
        }
    }

    // Actualizar tarjetas de métricas y desglose
    function actualizarMetricas(data) {
        const fijas = data.metricas_fijas || {};
        const resumen = data.resumen_periodo || {};

        if (statNeto) statNeto.textContent = formatCurrency(resumen.ingreso_neto);
        if (statHoy) statHoy.textContent = formatCurrency(fijas.hoy);
        if (statSemana) statSemana.textContent = formatCurrency(fijas.semana);
        if (statMes) statMes.textContent = formatCurrency(fijas.mes);
        if (statHistorico) statHistorico.textContent = formatCurrency(fijas.total_historico);
        if (statTicket) statTicket.textContent = formatCurrency(resumen.ticket_medio);
        if (statPedidos) statPedidos.textContent = resumen.total_pedidos || 0;

        // Desglose
        if (bdAnticipos) bdAnticipos.textContent = formatCurrency(resumen.anticipos_monto);
        if (countAnticipos) countAnticipos.textContent = `(${resumen.anticipos_conteo || 0} recibidos)`;
        if (bdCompletos) bdCompletos.textContent = formatCurrency(resumen.pagos_completos_monto);
        if (countCompletos) countCompletos.textContent = `(${resumen.pagos_completos_conteo || 0})`;
        if (bdLiquidaciones) bdLiquidaciones.textContent = formatCurrency(resumen.liquidaciones_monto);
        if (countLiquidaciones) countLiquidaciones.textContent = `(${resumen.liquidaciones_conteo || 0})`;
        if (bdCanceladas) bdCanceladas.textContent = formatCurrency(resumen.canceladas_monto);
        if (countCanceladas) countCanceladas.textContent = `(${resumen.canceladas_conteo || 0} retenidos)`;
        if (bdManualesIngreso) bdManualesIngreso.textContent = formatCurrency(resumen.ingresos_manuales);
        if (bdRestas) bdRestas.textContent = "-" + formatCurrency(resumen.restas_egresos);

        // Balance lateral
        if (sideBruto) sideBruto.textContent = formatCurrency(resumen.ingreso_bruto);
        if (sideRestas) sideRestas.textContent = "-" + formatCurrency(resumen.restas_egresos);
        if (sideNeto) sideNeto.textContent = formatCurrency(resumen.ingreso_neto);
    }

    // Renderizar gráfica de barras dinámica con CSS y tooltips elegantes
    function renderizarGrafica(puntos) {
        if (!chartBarsViewport) return;
        chartBarsViewport.innerHTML = "";

        if (!puntos || puntos.length === 0) {
            chartBarsViewport.innerHTML = '<div style="margin: auto; color: var(--muted); font-size: 13px;">No hay movimientos en este período</div>';
            return;
        }

        // Encontrar valor máximo para la escala
        let maxVal = 1;
        puntos.forEach(p => {
            const ing = Number(p.ingreso) || 0;
            const res = Number(p.resta) || 0;
            if (ing > maxVal) maxVal = ing;
            if (res > maxVal) maxVal = res;
        });

        puntos.forEach(p => {
            const ing = Number(p.ingreso) || 0;
            const res = Number(p.resta) || 0;
            const neto = Number(p.neto) || 0;

            const ingPercent = Math.max(4, Math.round((ing / maxVal) * 100));
            const resPercent = res > 0 ? Math.max(4, Math.round((res / maxVal) * 100)) : 0;

            const col = document.createElement("div");
            col.className = "chart-col";
            col.setAttribute("tabindex", "0");
            col.setAttribute("role", "figure");
            col.setAttribute("aria-label", `${p.label}: Ingresos ${formatCurrency(ing)}, Restas ${formatCurrency(res)}`);

            col.innerHTML = `
                <div class="chart-tooltip">
                    <strong>${p.label}</strong><br>
                    <span>Ingresos: +${formatCurrency(ing)}</span><br>
                    <span>Restas: -${formatCurrency(res)}</span><br>
                    <span style="font-weight:700; color:var(--teal-light)">Neto: ${formatCurrency(neto)}</span>
                </div>
                <div class="chart-col-bars-group">
                    <div class="chart-bar bar-ingreso" style="height: ${ing > 0 ? ingPercent : 0}%" title="Ingreso: ${formatCurrency(ing)}"></div>
                    ${res > 0 ? `<div class="chart-bar bar-resta" style="height: ${resPercent}%" title="Resta: ${formatCurrency(res)}"></div>` : ""}
                </div>
                <div class="chart-col-label">${p.label}</div>
            `;

            chartBarsViewport.appendChild(col);
        });
    }

    // Filtrar y renderizar la tabla de transacciones
    function renderizarTransacciones() {
        if (!txBody) return;
        txBody.innerHTML = "";

        const busqueda = (txSearch ? txSearch.value : "").trim().toLowerCase();
        const tipoFiltro = txTypeFilter ? txTypeFilter.value : "";

        const filtradas = allTransactions.filter(tx => {
            // Filtro por tipo
            if (tipoFiltro) {
                if (tipoFiltro === "MANUAL" && tx.origen !== "MANUAL") return false;
                if (tipoFiltro === "INGRESO" && tx.tipo !== "INGRESO") return false;
                if (tipoFiltro === "RESTA" && tx.tipo !== "RESTA") return false;
                if (["ANTICIPO", "PAGO_COMPLETO", "LIQUIDACION", "ANTICIPO_RETENIDO"].includes(tipoFiltro)) {
                    if (tx.subtipo !== tipoFiltro) return false;
                }
            }

            // Filtro por búsqueda
            if (busqueda) {
                const matchCliente = (tx.cliente || "").toLowerCase().includes(busqueda);
                const matchConcepto = (tx.concepto || "").toLowerCase().includes(busqueda);
                const matchCodigo = (tx.codigo_reserva || "").toLowerCase().includes(busqueda);
                const matchMetodo = (tx.metodo_pago || "").toLowerCase().includes(busqueda);
                if (!matchCliente && !matchConcepto && !matchCodigo && !matchMetodo) {
                    return false;
                }
            }

            return true;
        });

        if (txCount) txCount.textContent = filtradas.length;

        if (filtradas.length === 0) {
            if (txEmpty) txEmpty.hidden = false;
            return;
        }
        if (txEmpty) txEmpty.hidden = true;

        filtradas.forEach(tx => {
            const tr = document.createElement("tr");

            // Subtipo badge
            let badgeClass = "badge-tx ";
            if (tx.tipo === "RESTA") {
                badgeClass += "resta";
            } else if (tx.subtipo === "ANTICIPO") {
                badgeClass += "anticipo";
            } else if (tx.subtipo === "PAGO_COMPLETO") {
                badgeClass += "completo";
            } else if (tx.subtipo === "LIQUIDACION") {
                badgeClass += "liquidacion";
            } else if (tx.subtipo === "ANTICIPO_RETENIDO") {
                badgeClass += "cancelada";
            } else {
                badgeClass += "manual-ingreso";
            }

            // Monto format
            const esResta = tx.tipo === "RESTA";
            const montoFormatted = (esResta ? "- " : "+ ") + formatCurrency(tx.monto);
            const montoClass = esResta ? "amount-negative" : "amount-positive";

            // Detalle de origen / código
            let origenHTML = "";
            if (tx.origen === "RESERVA" && tx.codigo_reserva) {
                origenHTML = `<span class="tx-code-link">${tx.codigo_reserva}</span>`;
            } else {
                origenHTML = `<span style="color:var(--muted); font-size:12px;">Manual</span>`;
            }

            // Acciones
            let accionHTML = '<span style="color:#a0aec0;">—</span>';
            if (tx.puede_entregar_anticipo && tx.id_reserva) {
                accionHTML = `<button type="button" class="btn-entregar-anticipo" data-entregar-reserva="${tx.id_reserva}" data-codigo="${tx.codigo_reserva}" data-cliente="${encodeURIComponent(tx.cliente)}" data-monto="${tx.monto}"><span class="btn-entregar-icon">↩</span> Presiona si ya entregaste el anticipo retenido</button>`;
            } else if (tx.anticipo_devuelto) {
                accionHTML = `<span class="badge-anticipo-entregado">✓ Ya se entregó</span>`;
            } else if (tx.es_editable && tx.id_movimiento) {
                accionHTML = `<button type="button" class="btn-delete-tx" data-delete-id="${tx.id_movimiento}" data-concept="${encodeURIComponent(tx.concepto)}" data-amount="${tx.monto}">Eliminar</button>`;
            }

            tr.innerHTML = `
                <td>
                    <div style="font-weight:600;">${tx.fecha_corta || tx.fecha.slice(0, 10)}</div>
                    <div style="font-size:11px; color:var(--muted);">${tx.fecha.slice(11, 16)}</div>
                </td>
                <td>${origenHTML}</td>
                <td>
                    <div style="display:flex; align-items:center; gap:8px;">
                        <span class="${badgeClass}">${tx.subtipo_etiqueta || tx.tipo}</span>
                        <strong style="color:var(--ink);">${tx.concepto}</strong>
                    </div>
                    ${tx.cliente && tx.cliente !== 'Administración' ? `<div class="tx-concept-sub">Cliente: ${tx.cliente}</div>` : ''}
                    ${tx.notas ? `<div class="tx-concept-sub" style="font-style:italic;">Nota: ${tx.notas}</div>` : ''}
                </td>
                <td>
                    <span style="font-size:12px; font-weight:500;">${tx.metodo_pago}</span>
                </td>
                <td class="${montoClass}">
                    ${montoFormatted}
                </td>
                <td>
                    ${accionHTML}
                </td>
            `;

            txBody.appendChild(tr);
        });
    }

    // Delegación para acciones de tabla (eliminar movimiento y entregar anticipo retenido)
    if (txBody) {
        txBody.addEventListener("click", async (e) => {
            // Acción: Entregar anticipo retenido
            const btnEntregar = e.target.closest("[data-entregar-reserva]");
            if (btnEntregar) {
                const idReserva = btnEntregar.dataset.entregarReserva;
                const codigo = btnEntregar.dataset.codigo;
                const cliente = decodeURIComponent(btnEntregar.dataset.cliente || "Cliente");
                const monto = Number(btnEntregar.dataset.monto || 0);

                const confirmado = await mostrarModalDinamico({
                    icon: "💸",
                    title: "¿Registrar entrega de anticipo?",
                    message: `¿Confirmas que ya se entregó el anticipo retenido de ${formatCurrency(monto)} al cliente ${cliente}?`,
                    details: `Reserva ${codigo}. Al confirmar, el sistema restará este valor inmediatamente de los ingresos y registrará el egreso contable correspondiente.`,
                    confirmText: "Sí, ya se entregó",
                    cancelText: "Cancelar",
                });

                if (!confirmado) return;

                btnEntregar.disabled = true;
                btnEntregar.textContent = "Procesando...";

                try {
                    const res = await fetch("/api/admin/ingresos/entregar-anticipo-retenido", {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json",
                            "X-CSRF-Token": csrfToken,
                            "Accept": "application/json",
                        },
                        body: JSON.stringify({ id_reserva: idReserva }),
                    });

                    const data = await res.json();
                    if (!res.ok) {
                        throw new Error(data.error || "No se pudo registrar la entrega del anticipo");
                    }

                    await mostrarModalDinamico({
                        icon: "✅",
                        title: "¡Anticipo entregado!",
                        message: data.mensaje || `Se registró la entrega de ${formatCurrency(monto)} y se restó del sistema.`,
                        showCancel: false,
                        confirmText: "Aceptar",
                    });

                    cargarDatos(currentPeriod);
                } catch (err) {
                    await mostrarModalDinamico({
                        icon: "❌",
                        title: "Error en la operación",
                        message: err.message || "Ocurrió un error al registrar la entrega del anticipo.",
                        showCancel: false,
                        confirmText: "Entendido",
                    });
                    btnEntregar.disabled = false;
                    btnEntregar.innerHTML = '<span class="btn-entregar-icon">↩</span> Presiona si ya entregaste el anticipo retenido';
                }
                return;
            }

            // Acción: Eliminar movimiento manual
            const btn = e.target.closest("[data-delete-id]");
            if (!btn) return;

            const id = btn.dataset.deleteId;
            const concepto = decodeURIComponent(btn.dataset.concept || "movimiento");
            const monto = Number(btn.dataset.amount || 0);

            const confirmado = await mostrarModalDinamico({
                icon: "🗑️",
                title: "¿Eliminar este movimiento?",
                message: `¿Estás seguro de que deseas eliminar el registro de ${formatCurrency(monto)}?`,
                details: `Concepto: "${concepto}". Esta acción recalculará los totales financieros inmediatamente.`,
                confirmText: "Sí, eliminar",
                cancelText: "No, conservar",
            });

            if (!confirmado) return;

            try {
                const res = await fetch(`/api/admin/ingresos/movimiento/${id}`, {
                    method: "DELETE",
                    headers: {
                        "X-CSRF-Token": csrfToken,
                        "Accept": "application/json",
                    },
                });

                const data = await res.json();
                if (!res.ok) {
                    throw new Error(data.error || "No se pudo eliminar el movimiento");
                }

                await mostrarModalDinamico({
                    icon: "✅",
                    title: "Movimiento eliminado",
                    message: data.mensaje || "El movimiento fue eliminado exitosamente.",
                    showCancel: false,
                    confirmText: "Aceptar",
                });

                // Recargar datos
                cargarDatos(currentPeriod);
            } catch (err) {
                mostrarModalDinamico({
                    icon: "❌",
                    title: "Error al eliminar",
                    message: err.message || "Ocurrió un error al intentar eliminar el movimiento.",
                    showCancel: false,
                    confirmText: "Entendido",
                });
            }
        });
    }

    // Selector de período
    periodButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            periodButtons.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            const periodo = btn.dataset.period || "semana";
            cargarDatos(periodo);
        });
    });

    // Filtros de búsqueda y tipo en tiempo real
    if (txSearch) txSearch.addEventListener("input", renderizarTransacciones);
    if (txTypeFilter) txTypeFilter.addEventListener("change", renderizarTransacciones);

    // Modal de registro de movimiento: Abrir y Cerrar
    function abrirModalRegistro(tipoDefecto = "INGRESO") {
        if (!modalMovimiento) return;
        formMovimiento.reset();

        // Marcar radio correspondiente
        const radio = formMovimiento.querySelector(`input[name="tipo_movimiento"][value="${tipoDefecto}"]`);
        if (radio) radio.checked = true;

        actualizarEstiloFormulario(tipoDefecto);

        // Fecha actual por defecto en formato datetime-local
        const inputFecha = document.getElementById("movFecha");
        if (inputFecha) {
            const now = new Date();
            now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
            inputFecha.value = now.toISOString().slice(0, 16);
        }

        modalMovimiento.classList.add("is-visible");
        modalMovimiento.setAttribute("aria-hidden", "false");
        const movMonto = document.getElementById("movMonto");
        if (movMonto) movMonto.focus();
    }

    function cerrarModalRegistro() {
        if (!modalMovimiento) return;
        modalMovimiento.classList.remove("is-visible");
        modalMovimiento.setAttribute("aria-hidden", "true");
    }

    function actualizarEstiloFormulario(tipo) {
        if (btnGuardarMovimiento) {
            if (tipo === "RESTA") {
                btnGuardarMovimiento.textContent = "Aplicar resta / egreso";
                btnGuardarMovimiento.style.background = "linear-gradient(135deg, var(--pink), var(--pink-dark))";
                if (inputCategoria && inputCategoria.value === "VENTA_DIRECTA") {
                    inputCategoria.value = "INSUMOS";
                }
            } else {
                btnGuardarMovimiento.textContent = "Guardar ingreso";
                btnGuardarMovimiento.style.background = "linear-gradient(135deg, var(--teal), var(--teal-dark))";
                if (inputCategoria && inputCategoria.value === "INSUMOS") {
                    inputCategoria.value = "VENTA_DIRECTA";
                }
            }
        }
    }

    if (btnNuevoMovimiento) btnNuevoMovimiento.addEventListener("click", () => abrirModalRegistro("INGRESO"));
    if (btnSideRegistrar) btnSideRegistrar.addEventListener("click", () => abrirModalRegistro("INGRESO"));
    if (btnCerrarModalMovimiento) btnCerrarModalMovimiento.addEventListener("click", cerrarModalRegistro);
    if (btnCancelarMovimiento) btnCancelarMovimiento.addEventListener("click", cerrarModalRegistro);

    radioTipos.forEach(radio => {
        radio.addEventListener("change", (e) => {
            actualizarEstiloFormulario(e.target.value);
        });
    });

    // Guardar nuevo movimiento
    if (formMovimiento) {
        formMovimiento.addEventListener("submit", async (e) => {
            e.preventDefault();

            const tipo = formMovimiento.querySelector('input[name="tipo_movimiento"]:checked')?.value || "INGRESO";
            const montoVal = parseFloat(document.getElementById("movMonto")?.value || "0");
            const conceptoVal = (document.getElementById("movConcepto")?.value || "").trim();
            const categoriaVal = document.getElementById("movCategoria")?.value || "OTRO";
            const metodoVal = document.getElementById("movMetodo")?.value || "EFECTIVO";
            const fechaVal = document.getElementById("movFecha")?.value || "";
            const notasVal = (document.getElementById("movNotas")?.value || "").trim();

            if (!montoVal || montoVal <= 0) {
                await mostrarModalDinamico({
                    icon: "⚠️",
                    title: "Monto inválido",
                    message: "Por favor ingresa un monto válido mayor a $0.00.",
                    showCancel: false,
                    confirmText: "Entendido",
                });
                return;
            }

            if (conceptoVal.length < 3) {
                await mostrarModalDinamico({
                    icon: "⚠️",
                    title: "Concepto requerido",
                    message: "Ingresa una breve descripción o concepto del movimiento (mínimo 3 caracteres).",
                    showCancel: false,
                    confirmText: "Entendido",
                });
                return;
            }

            // Deshabilitar botón durante el envío
            btnGuardarMovimiento.disabled = true;
            btnGuardarMovimiento.textContent = "Guardando...";

            try {
                const payload = {
                    tipo: tipo,
                    monto: montoVal,
                    concepto: conceptoVal,
                    categoria: categoriaVal,
                    metodo_pago: metodoVal,
                    fecha: fechaVal || undefined,
                    notas: notasVal,
                };

                const res = await fetch("/api/admin/ingresos/movimiento", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-CSRF-Token": csrfToken,
                        "Accept": "application/json",
                    },
                    body: JSON.stringify(payload),
                });

                const data = await res.json();
                if (!res.ok) {
                    throw new Error(data.error || "No se pudo registrar el movimiento.");
                }

                cerrarModalRegistro();

                await mostrarModalDinamico({
                    icon: tipo === "INGRESO" ? "💰" : "📉",
                    title: tipo === "INGRESO" ? "¡Ingreso registrado!" : "¡Resta registrada!",
                    message: `${data.mensaje || "Movimiento guardado con éxito."} por valor de ${formatCurrency(montoVal)}.`,
                    showCancel: false,
                    confirmText: "Excelente",
                });

                // Actualizar panel inmediatamente
                cargarDatos(currentPeriod);
            } catch (err) {
                await mostrarModalDinamico({
                    icon: "❌",
                    title: "Error al registrar",
                    message: err.message || "Ocurrió un error al guardar el movimiento en el sistema.",
                    showCancel: false,
                    confirmText: "Entendido",
                });
            } finally {
                btnGuardarMovimiento.disabled = false;
                actualizarEstiloFormulario(tipo);
            }
        });
    }

    // Inicializar carga de datos al cargar la vista
    document.addEventListener("DOMContentLoaded", () => {
        cargarDatos("semana");
    });
    if (document.readyState === "complete" || document.readyState === "interactive") {
        cargarDatos("semana");
    }
})();
