/**
 * TWIINS Bakery - Módulo de Fidelidad del Cliente
 * Gestión de progreso interactivo, canje de productos y actualización en tiempo real
 */
(() => {
    'use strict';

    const fidelityRoot = document.getElementById('fidelidadRoot');
    if (!fidelityRoot) return;

    const csrfToken = fidelityRoot.dataset.csrfToken || '';
    let currentPoints = parseInt(fidelityRoot.dataset.puntos || '0', 10);
    const minGoal = parseInt(fidelityRoot.dataset.metaMinima || '50', 10);

    // Elementos del indicador circular
    const progressFill = document.getElementById('progressCircleFill');
    const pointsNumberEl = document.getElementById('pointsNumberDisplay');
    const heroContainer = document.getElementById('fidelityHeroContainer');
    const motivationMessageEl = document.getElementById('motivationMessageDisplay');

    // Modales
    const confirmModal = document.getElementById('modalConfirmarCanje');
    const successModal = document.getElementById('modalExitoCanje');
    const errorModal = document.getElementById('modalErrorCanje');

    let selectedProduct = null;

    // Radio de la circunferencia: r = 110, Circunferencia = 2 * PI * 110 ≈ 691.15
    const CIRCUMFERENCE = 2 * Math.PI * 110;

    /**
     * Actualiza el indicador circular y el mensaje motivacional según el saldo
     */
    function updateProgressUI(points) {
        currentPoints = points;
        if (pointsNumberEl) {
            pointsNumberEl.textContent = points;
        }

        const percentage = Math.min(1, Math.max(0, points / minGoal));
        const offset = CIRCUMFERENCE * (1 - percentage);

        if (progressFill) {
            progressFill.style.strokeDasharray = `${CIRCUMFERENCE} ${CIRCUMFERENCE}`;
            progressFill.style.strokeDashoffset = offset;
        }

        if (points >= minGoal) {
            heroContainer?.classList.remove('state-muted');
            heroContainer?.classList.add('state-unlocked');

            if (motivationMessageEl) {
                motivationMessageEl.innerHTML = `<strong>¡Felicidades!</strong> Ya has alcanzado la cantidad mínima de puntos para canjear un postre de vitrina. También puedes seguir acumulando más puntos para obtener mayores beneficios y realizar más canjes en el futuro.`;
            }
        } else {
            heroContainer?.classList.remove('state-unlocked');
            heroContainer?.classList.add('state-muted');

            if (motivationMessageEl) {
                if (points === 0) {
                    motivationMessageEl.textContent = `Comienza hoy a acumular puntos y obtén tu primer postre gratis de nuestra vitrina.`;
                } else {
                    const faltan = minGoal - points;
                    motivationMessageEl.innerHTML = `Tienes <strong>${points}</strong> de <strong>${minGoal}</strong> puntos. Te faltan <strong>${faltan}</strong> puntos adicionales para obtener tu primer postre gratis de nuestra vitrina.`;
                }
            }
        }

        // Actualizar botones de canje según el saldo actual
        document.querySelectorAll('[data-canjear-btn]').forEach((btn) => {
            const req = parseInt(btn.dataset.puntosRequeridos || '50', 10);
            if (points < req) {
                btn.disabled = true;
                const faltan = req - points;
                btn.textContent = `Faltan ${faltan} pts`;
                btn.title = `Necesitas ${req} puntos. Te faltan ${faltan} puntos adicionales.`;
            } else {
                btn.disabled = false;
                btn.textContent = 'Canjear postre';
                btn.title = '¡Tienes los puntos necesarios! Haz clic para canjear.';
            }
        });
    }

    /**
     * Modal helpers
     */
    function openModal(modal) {
        if (!modal) return;
        modal.classList.add('is-visible');
        modal.setAttribute('aria-hidden', 'false');
    }

    function closeModal(modal) {
        if (!modal) return;
        modal.classList.remove('is-visible');
        modal.setAttribute('aria-hidden', 'true');
    }

    // Inicializar listeners de botones de canje
    document.querySelectorAll('[data-canjear-btn]').forEach((btn) => {
        btn.addEventListener('click', (e) => {
            const prodId = btn.dataset.productoId;
            const prodNombre = btn.dataset.productoNombre;
            const reqPoints = parseInt(btn.dataset.puntosRequeridos || '50', 10);

            // Verificación del saldo
            if (currentPoints < reqPoints) {
                const faltan = reqPoints - currentPoints;
                showErrorModal(
                    'Puntos insuficientes',
                    `No posees los puntos necesarios para este postre. Requiere ${reqPoints} puntos y tienes ${currentPoints}. Necesitas acumular ${faltan} puntos adicionales para canjearlo.`
                );
                return;
            }

            selectedProduct = {
                id: prodId,
                nombre: prodNombre,
                puntos: reqPoints
            };

            // Rellenar modal de confirmación
            document.getElementById('confirmProdNombre').textContent = prodNombre;
            document.getElementById('confirmPuntosReq').textContent = `${reqPoints} pts`;
            document.getElementById('confirmSaldoActual').textContent = `${currentPoints} pts`;
            document.getElementById('confirmSaldoRestante').textContent = `${currentPoints - reqPoints} pts`;

            // Configurar fecha de retiro sugerida (mañana a las 14:00)
            const dateInput = document.getElementById('canjeFechaRetiro');
            if (dateInput) {
                const manana = new Date();
                manana.setDate(manana.getDate() + 1);
                dateInput.value = manana.toISOString().split('T')[0];
                dateInput.min = new Date().toISOString().split('T')[0];
            }

            openModal(confirmModal);
        });
    });

    // Cancelar modal confirmación
    document.getElementById('btnCancelarCanje')?.addEventListener('click', () => {
        closeModal(confirmModal);
        selectedProduct = null;
    });

    // Confirmar canje mediante petición AJAX
    document.getElementById('btnConfirmarCanjeAction')?.addEventListener('click', async () => {
        if (!selectedProduct) return;

        const btn = document.getElementById('btnConfirmarCanjeAction');
        btn.disabled = true;
        btn.textContent = 'Procesando canje...';

        const fechaRetiro = document.getElementById('canjeFechaRetiro')?.value;

        try {
            const resp = await fetch('/api/fidelidad/canjear', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': csrfToken
                },
                body: JSON.stringify({
                    producto_id: selectedProduct.id,
                    fecha_retiro: fechaRetiro
                })
            });

            const data = await resp.json();

            if (!resp.ok || !data.ok) {
                throw new Error(data.error || 'No se pudo procesar el canje de puntos.');
            }

            closeModal(confirmModal);

            // Mostrar modal de éxito con los 4 datos mínimos solicitados:
            // Producto canjeado, Puntos utilizados, Puntos restantes, Fecha del canje
            document.getElementById('successProdNombre').textContent = data.producto;
            document.getElementById('successPuntosUsados').textContent = `-${data.puntos_utilizados} pts`;
            document.getElementById('successPuntosRestantes').textContent = `${data.puntos_restantes} pts`;
            document.getElementById('successFechaCanje').textContent = data.fecha_canje;
            if (document.getElementById('successCodigoCanje')) {
                document.getElementById('successCodigoCanje').textContent = data.codigo_reserva || 'TB-CANJE';
            }

            openModal(successModal);

            // Actualizar inmediatamente el saldo y la UI
            updateProgressUI(data.puntos_restantes);

            // Agregar fila al historial de movimientos
            agregarFilaHistorial({
                fecha: data.fecha_canje,
                tipo: 'Canje de producto',
                puntos: `-${data.puntos_utilizados}`,
                saldo: data.puntos_restantes,
                motivo: `Canje de producto: -${data.puntos_utilizados} puntos (${data.producto})`
            });

        } catch (err) {
            closeModal(confirmModal);
            showErrorModal('Error al canjear', err.message);
        } finally {
            btn.disabled = false;
            btn.textContent = 'Confirmar canje';
            selectedProduct = null;
        }
    });

    // Cerrar modal éxito
    document.getElementById('btnCerrarExitoCanje')?.addEventListener('click', () => {
        closeModal(successModal);
    });

    // Cerrar modal error
    document.getElementById('btnCerrarErrorCanje')?.addEventListener('click', () => {
        closeModal(errorModal);
    });

    function showErrorModal(titulo, desc) {
        document.getElementById('errorModalTitulo').textContent = titulo;
        document.getElementById('errorModalDesc').textContent = desc;
        openModal(errorModal);
    }

    function agregarFilaHistorial(mov) {
        const tbody = document.getElementById('historialPuntosBody');
        const emptyRow = document.getElementById('historialEmptyRow');
        if (emptyRow) {
            emptyRow.remove();
        }
        if (!tbody) return;

        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><strong>${mov.fecha}</strong></td>
            <td>${mov.motivo}</td>
            <td><span class="pts-badge pts-sub">${mov.puntos} pts</span></td>
            <td><strong>${mov.saldo} pts</strong></td>
        `;
        tbody.prepend(tr);
    }

    // Inicializar UI al cargar
    updateProgressUI(currentPoints);
})();
