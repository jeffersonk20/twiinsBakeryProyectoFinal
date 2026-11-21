/**
 * TWIINS Bakery - Panel de Administración: Módulo de Fidelidad
 * Lógica para pantallas independientes: Dashboard, Historial, Canjes y Configuración
 */
(() => {
    'use strict';

    const rootEl = document.querySelector('[data-admin-fidelidad]');
    if (!rootEl) return;

    const csrfToken = rootEl.dataset.csrfToken || '';
    const section = rootEl.dataset.section || 'dashboard';

    function escapeHtml(text) {
        if (!text) return '';
        return String(text).replace(/[&<>"']/g, (m) => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
        }[m]));
    }

    function showAdminToast(msg, isError = false) {
        let toast = document.getElementById('adminFidelidadToast');
        if (!toast) {
            toast = document.createElement('div');
            toast.id = 'adminFidelidadToast';
            toast.style.cssText = `
                position: fixed;
                bottom: 24px;
                right: 24px;
                background: ${isError ? '#dc2626' : '#15803d'};
                color: #fff;
                padding: 12px 20px;
                border-radius: 10px;
                font-size: 13px;
                font-weight: 600;
                box-shadow: 0 4px 18px rgba(0,0,0,0.2);
                z-index: 9999;
                transition: opacity 0.3s ease;
            `;
            document.body.appendChild(toast);
        }
        toast.textContent = msg;
        toast.style.background = isError ? '#dc2626' : '#15803d';
        toast.style.display = 'block';
        toast.style.opacity = '1';
        setTimeout(() => {
            toast.style.opacity = '0';
            setTimeout(() => { toast.style.display = 'none'; }, 300);
        }, 4000);
    }

    // =========================================================================
    // 1. PANTALLA: CANJES DE FIDELIDAD (admin_fidelidad_canjes)
    // =========================================================================
    if (section === 'canjes') {
        const canjesBody = document.getElementById('canjesTableBody');
        const searchInput = document.getElementById('canjesSearchInput');
        const statusFilter = document.getElementById('canjesStatusFilter');
        const statusModal = document.getElementById('modalCambiarEstadoCanje');
        const formCambiarEstado = document.getElementById('formCambiarEstadoCanje');
        let canjesList = [];

        async function loadCanjes() {
            try {
                const resp = await fetch('/api/admin/fidelidad/canjes');
                const data = await resp.json();
                canjesList = data.canjes || [];
                renderCanjesTable();
            } catch (err) {
                showAdminToast('Error al cargar canjes: ' + err.message, true);
            }
        }

        function renderCanjesTable() {
            if (!canjesBody) return;
            const term = (searchInput?.value || '').toLowerCase().trim();
            const status = statusFilter?.value || '';

            const filtered = canjesList.filter(item => {
                const matchTerm = !term || 
                    (item.codigo || '').toLowerCase().includes(term) ||
                    (item.cliente || '').toLowerCase().includes(term) ||
                    (item.producto || '').toLowerCase().includes(term) ||
                    (item.correo || '').toLowerCase().includes(term);
                const matchStatus = !status || item.estado === status;
                return matchTerm && matchStatus;
            });

            if (filtered.length === 0) {
                canjesBody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:30px;color:#728186;">No se encontraron canjes de fidelidad.</td></tr>`;
                return;
            }

            canjesBody.innerHTML = filtered.map(item => {
                const isDelivered = item.estado === 'ENTREGADA';
                const statusPillClass = isDelivered ? 'delivered' : item.estado === 'LISTA' ? 'ready' : 'confirmed';
                return `
                    <tr>
                        <td>
                            <span class="badge-canje-fidelidad">🎁 ${escapeHtml(item.codigo)}</span>
                        </td>
                        <td>
                            <strong>${escapeHtml(item.cliente)}</strong><br>
                            <small style="color:#728186;">${escapeHtml(item.telefono || 'Sin teléfono')} · ${escapeHtml(item.correo || '')}</small>
                        </td>
                        <td>
                            <strong style="color:#123f49;">${escapeHtml(item.producto)}</strong>
                        </td>
                        <td>
                            <span class="badge-pts-loss">-${item.puntos_usados} pts</span>
                        </td>
                        <td>
                            ${escapeHtml(item.fecha_canje)}
                        </td>
                        <td>
                            <strong>${escapeHtml(item.fecha_retiro || 'Por coordinar')}</strong>
                        </td>
                        <td>
                            <span class="status-pill ${statusPillClass}">${escapeHtml(item.estado_display || item.estado)}</span>
                        </td>
                        <td>
                            <div class="row-actions">
                                <button type="button" class="btn-action-edit" data-edit-canje="${item.id}">Actualizar estado</button>
                                ${!isDelivered ? `<button type="button" class="btn-action-deliver confirm-action" data-deliver-canje="${item.id}">✓ Marcar entregado</button>` : ''}
                            </div>
                        </td>
                    </tr>
                `;
            }).join('');
        }

        searchInput?.addEventListener('input', renderCanjesTable);
        statusFilter?.addEventListener('change', renderCanjesTable);

        // Click en acciones de la tabla
        canjesBody?.addEventListener('click', async (e) => {
            const btnDeliver = e.target.closest('[data-deliver-canje]');
            if (btnDeliver) {
                const id = btnDeliver.dataset.deliverCanje;
                if (!confirm('¿Deseas marcar este producto canjeado como ENTREGADO al cliente?')) return;
                try {
                    const resp = await fetch(`/api/admin/fidelidad/canjes/${id}/estado`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
                        body: JSON.stringify({ estado: 'ENTREGADA' })
                    });
                    const res = await resp.json();
                    if (!resp.ok || !res.ok) throw new Error(res.error || 'Error al actualizar');
                    showAdminToast('¡Canje marcado como ENTREGADO con éxito!');
                    loadCanjes();
                } catch (err) {
                    showAdminToast(err.message, true);
                }
                return;
            }

            const btnEdit = e.target.closest('[data-edit-canje]');
            if (btnEdit) {
                const id = btnEdit.dataset.editCanje;
                const canje = canjesList.find(c => String(c.id) === String(id));
                if (!canje) return;

                document.getElementById('editCanjeId').value = canje.id;
                document.getElementById('editCanjeCodigo').textContent = canje.codigo;
                document.getElementById('editCanjeCliente').textContent = canje.cliente;
                document.getElementById('editCanjeProducto').textContent = canje.producto;
                document.getElementById('selectCanjeEstado').value = canje.estado;
                
                statusModal?.classList.add('is-visible');
            }
        });

        document.getElementById('btnCerrarModalCanje')?.addEventListener('click', () => {
            statusModal?.classList.remove('is-visible');
        });

        formCambiarEstado?.addEventListener('submit', async (e) => {
            e.preventDefault();
            const id = document.getElementById('editCanjeId').value;
            const nuevoEstado = document.getElementById('selectCanjeEstado').value;

            try {
                const resp = await fetch(`/api/admin/fidelidad/canjes/${id}/estado`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
                    body: JSON.stringify({ estado: nuevoEstado })
                });
                const res = await resp.json();
                if (!resp.ok || !res.ok) throw new Error(res.error || 'Error al actualizar');
                showAdminToast('Estado de la orden de canje actualizado.');
                statusModal?.classList.remove('is-visible');
                loadCanjes();
            } catch (err) {
                showAdminToast(err.message, true);
            }
        });

        loadCanjes();
    }

    // =========================================================================
    // 2. PANTALLA: HISTORIAL DE PUNTOS (admin_fidelidad_historial)
    // =========================================================================
    if (section === 'historial') {
        const histBody = document.getElementById('historialAllTableBody');
        const searchInput = document.getElementById('historialSearchInput');
        const tipoFilter = document.getElementById('historialTipoFilter');
        let movimientos = [];

        async function loadHistorial() {
            try {
                const resp = await fetch('/api/admin/fidelidad/historial');
                const data = await resp.json();
                movimientos = data.movimientos || [];
                renderHistorialTable();
            } catch (err) {
                showAdminToast('Error al cargar historial: ' + err.message, true);
            }
        }

        function renderHistorialTable() {
            if (!histBody) return;
            const term = (searchInput?.value || '').toLowerCase().trim();
            const tipo = tipoFilter?.value || '';

            const filtered = movimientos.filter(item => {
                const matchTerm = !term ||
                    (item.cliente || '').toLowerCase().includes(term) ||
                    (item.correo || '').toLowerCase().includes(term) ||
                    (item.motivo || '').toLowerCase().includes(term);
                const matchTipo = !tipo || item.tipo_movimiento === tipo;
                return matchTerm && matchTipo;
            });

            if (filtered.length === 0) {
                histBody.innerHTML = `<tr><td colspan="5" style="text-align:center;padding:30px;color:#728186;">No hay movimientos registrados con los filtros aplicados.</td></tr>`;
                return;
            }

            histBody.innerHTML = filtered.map(item => {
                const isGain = item.puntos > 0;
                return `
                    <tr>
                        <td>
                            <strong>${escapeHtml(item.cliente)}</strong><br>
                            <small style="color:#728186;">${escapeHtml(item.correo)}</small>
                        </td>
                        <td>${escapeHtml(item.fecha)}</td>
                        <td>${escapeHtml(item.motivo)}</td>
                        <td>
                            <span class="${isGain ? 'badge-pts-gain' : 'badge-pts-loss'}">
                                ${isGain ? '+' : ''}${item.puntos} pts
                            </span>
                        </td>
                        <td>
                            <strong>${item.saldo_resultante} pts</strong>
                        </td>
                    </tr>
                `;
            }).join('');
        }

        searchInput?.addEventListener('input', renderHistorialTable);
        tipoFilter?.addEventListener('change', renderHistorialTable);
        loadHistorial();
    }

    // =========================================================================
    // 3. PANTALLA: CONFIGURACIÓN DE FIDELIDAD (admin_fidelidad_configuracion)
    // =========================================================================
    if (section === 'configuracion') {
        const formReglas = document.getElementById('formReglasFidelidad');
        const prodTableBody = document.getElementById('configProductosTableBody');
        const prodSearch = document.getElementById('configProdSearch');
        let productList = [];

        async function loadConfigData() {
            try {
                const resp = await fetch('/api/admin/fidelidad/configuracion');
                const data = await resp.json();
                
                if (data.config) {
                    document.getElementById('inputPuntosPorDolar').value = data.config.puntos_por_dolar || 1;
                    document.getElementById('inputMetaMinima').value = data.config.meta_minima_canje || 50;
                    document.getElementById('checkProgramaActivo').checked = Boolean(data.config.programa_activo);
                }

                productList = data.productos || [];
                renderProductConfigTable();
            } catch (err) {
                showAdminToast('Error al cargar configuración: ' + err.message, true);
            }
        }

        function renderProductConfigTable() {
            if (!prodTableBody) return;
            const term = (prodSearch?.value || '').toLowerCase().trim();

            const filtered = productList.filter(p => !term || (p.nombre || '').toLowerCase().includes(term) || (p.categoria || '').toLowerCase().includes(term));

            if (filtered.length === 0) {
                prodTableBody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:24px;color:#728186;">No hay productos que coincidan.</td></tr>`;
                return;
            }

            prodTableBody.innerHTML = filtered.map(p => `
                <tr data-prod-row="${p.id}">
                    <td>
                        <div style="display:flex;align-items:center;gap:10px;">
                            ${p.tiene_imagen ? `<img src="${escapeHtml(p.imagen)}" alt="" class="table-product-thumb">` : '<span style="font-size:24px;">🍰</span>'}
                            <div>
                                <strong>${escapeHtml(p.nombre)}</strong><br>
                                <small style="color:#728186;">${escapeHtml(p.categoria || 'Sin categoría')} · $${Number(p.precio).toFixed(2)}</small>
                            </div>
                        </div>
                    </td>
                    <td>
                        <label class="switch-toggle-label">
                            <input type="checkbox" class="check-canjeable" ${p.canjeable_puntos ? 'checked' : ''}>
                            <span>${p.canjeable_puntos ? 'Sí' : 'No'}</span>
                        </label>
                    </td>
                    <td>
                        <input type="number" class="input-puntos-canje" min="50" step="1" value="${p.puntos_canje || 50}" style="width:90px;padding:6px;border-radius:6px;border:1px solid #d8ccc4;" ${p.canjeable_puntos ? '' : 'disabled'}>
                    </td>
                    <td>
                        <label class="switch-toggle-label">
                            <input type="checkbox" class="check-genera-puntos" ${p.genera_puntos ? 'checked' : ''}>
                            <span>${p.genera_puntos ? 'Sí' : 'No'}</span>
                        </label>
                    </td>
                    <td>
                        <button type="button" class="btn-guardar-prod-fidelidad button-primary" data-save-prod="${p.id}" style="padding:6px 12px;font-size:12px;">Guardar</button>
                    </td>
                </tr>
            `).join('');
        }

        prodSearch?.addEventListener('input', renderProductConfigTable);

        // Guardar reglas generales
        formReglas?.addEventListener('submit', async (e) => {
            e.preventDefault();
            const btn = formReglas.querySelector('button[type="submit"]');
            btn.disabled = true;

            const puntosDolar = parseInt(document.getElementById('inputPuntosPorDolar').value, 10);
            const metaMinima = parseInt(document.getElementById('inputMetaMinima').value, 10);
            const activo = document.getElementById('checkProgramaActivo').checked;

            try {
                const resp = await fetch('/api/admin/fidelidad/configuracion', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
                    body: JSON.stringify({
                        puntos_por_dolar: puntosDolar,
                        meta_minima_canje: metaMinima,
                        programa_activo: activo
                    })
                });
                const res = await resp.json();
                if (!resp.ok || !res.ok) throw new Error(res.error || 'Error al guardar');
                showAdminToast('¡Reglas generales del programa de fidelidad guardadas!');
            } catch (err) {
                showAdminToast(err.message, true);
            } finally {
                btn.disabled = false;
            }
        });

        // Guardar configuración de un producto individual
        prodTableBody?.addEventListener('click', async (e) => {
            const btn = e.target.closest('[data-save-prod]');
            if (!btn) return;

            const prodId = btn.dataset.saveProd;
            const row = btn.closest('tr');
            const canjeable = row.querySelector('.check-canjeable').checked;
            const puntosCanje = parseInt(row.querySelector('.input-puntos-canje').value, 10);
            const genera = row.querySelector('.check-genera-puntos').checked;

            if (canjeable && puntosCanje < 50) {
                showAdminToast('Los puntos mínimos para canjear un producto son 50.', true);
                return;
            }

            btn.disabled = true;
            btn.textContent = 'Guardando...';

            try {
                const resp = await fetch(`/api/admin/fidelidad/producto/${prodId}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
                    body: JSON.stringify({
                        canjeable_puntos: canjeable,
                        puntos_canje: puntosCanje,
                        genera_puntos: genera
                    })
                });
                const res = await resp.json();
                if (!resp.ok || !res.ok) throw new Error(res.error || 'Error al actualizar');
                showAdminToast('Configuración del producto actualizada.');
            } catch (err) {
                showAdminToast(err.message, true);
            } finally {
                btn.disabled = false;
                btn.textContent = 'Guardar';
            }
        });

        // Habilitar/deshabilitar input de puntos según switch
        prodTableBody?.addEventListener('change', (e) => {
            if (e.target.classList.contains('check-canjeable')) {
                const row = e.target.closest('tr');
                const numInput = row.querySelector('.input-puntos-canje');
                numInput.disabled = !e.target.checked;
                e.target.nextElementSibling.textContent = e.target.checked ? 'Sí' : 'No';
            } else if (e.target.classList.contains('check-genera-puntos')) {
                e.target.nextElementSibling.textContent = e.target.checked ? 'Sí' : 'No';
            }
        });

        loadConfigData();
    }
})();
