/**
 * TWINS BAKERY - ASISTENTE DE INTELIGENCIA ARTIFICIAL (FRONTEND)
 * Maneja la interacción asíncrona (fetch/AJAX), renderizado de mensajes,
 * seguridad de tokens (JWT / CSRF) y renderizado adaptativo por rol.
 */

(function () {
    'use strict';

    // Estado interno del chat
    const state = {
        isOpen: false,
        isLoading: false,
        rol: 'cliente',
        adminJwt: sessionStorage.getItem('twins_admin_jwt') || '',
        historial: [],
        csrfToken: '',
    };

    // Referencias a elementos del DOM
    let elements = {};

    /**
     * Extrae el token CSRF si existe en el DOM o metatags
     */
    function obtenerCsrfToken() {
        const inputCsrf = document.querySelector('input[name="csrf_token"]');
        if (inputCsrf && inputCsrf.value) {
            return inputCsrf.value;
        }
        const metaCsrf = document.querySelector('meta[name="csrf-token"]');
        if (metaCsrf && metaCsrf.getAttribute('content')) {
            return metaCsrf.getAttribute('content');
        }
        return '';
    }

    /**
     * Parser ligero y seguro de Markdown a HTML seguro
     */
    function formatearMensaje(texto) {
        if (!texto) return '';

        // 1. Escapar caracteres HTML para defensa contra XSS
        let limpio = texto
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');

        // 2. Títulos ### o ##
        limpio = limpio.replace(/^### (.*$)/gim, '<h4 style="margin:6px 0;color:#123F49;">$1</h4>');
        limpio = limpio.replace(/^## (.*$)/gim, '<h3 style="margin:8px 0;color:#123F49;">$1</h3>');

        // 3. Negritas **texto**
        limpio = limpio.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');

        // 4. Cursivas *texto*
        limpio = limpio.replace(/\*(.*?)\*/g, '<em>$1</em>');

        // 5. Viñetas de lista (- item o • item)
        const lineas = limpio.split('\n');
        let enLista = false;
        let resultado = [];

        for (let i = 0; i < lineas.length; i++) {
            let linea = lineas[i].trim();
            if (linea.startsWith('- ') || linea.startsWith('• ') || linea.startsWith('* ')) {
                if (!enLista) {
                    resultado.push('<ul style="margin:4px 0 6px 16px;padding:0;">');
                    enLista = true;
                }
                const itemTexto = linea.substring(2).trim();
                resultado.push(`<li style="margin-bottom:3px;">${itemTexto}</li>`);
            } else {
                if (enLista) {
                    resultado.push('</ul>');
                    enLista = false;
                }
                if (linea.length > 0) {
                    resultado.push(`<p style="margin:0 0 6px 0;">${linea}</p>`);
                }
            }
        }
        if (enLista) {
            resultado.push('</ul>');
        }

        return resultado.join('');
    }

    /**
     * Construye la estructura visual del widget en el DOM
     */
    function inyectarEstructuraDOM() {
        if (document.getElementById('twinsIaContainer')) return;

        const contenedor = document.createElement('div');
        contenedor.id = 'twinsIaContainer';
        contenedor.innerHTML = `
            <!-- BOTÓN FLOTANTE INTERACTIVO -->
            <button type="button" id="twinsIaTrigger" class="twins-ia-trigger" aria-label="Abrir Asistente Virtual TWINS Bakery" title="Asistente de Inteligencia Artificial">
                <div class="twins-ia-trigger-avatar">
                    <span class="twins-ia-pulse-ring"></span>
                    <span>🍰</span>
                </div>
                <div class="twins-ia-trigger-label">
                    <span class="twins-ia-trigger-title">Twins Asistente <span class="twins-ia-trigger-sparkle">✦ IA</span></span>
                    <span class="twins-ia-trigger-sub" id="twinsTriggerSub">Atención & Catálogo</span>
                </div>
            </button>

            <!-- VENTANA MODAL / CHAT DRAWER -->
            <aside id="twinsIaWindow" class="twins-ia-window" role="dialog" aria-modal="true" aria-labelledby="twinsIaTitle" hidden>
                <!-- HEADER -->
                <header class="twins-ia-header">
                    <div class="twins-ia-header-info">
                        <div class="twins-ia-header-avatar" id="twinsIaHeaderAvatar">🍰</div>
                        <div class="twins-ia-header-text">
                            <h3 id="twinsIaTitle">Twins Bakery <span style="color:var(--ia-mint-primary);font-size:0.8rem;">✦ IA</span></h3>
                            <div class="twins-ia-role-badge" id="twinsIaRoleBadge">Cliente</div>
                            <div class="twins-ia-header-status">
                                <span class="twins-ia-status-dot"></span>
                                <span id="twinsIaStatusLabel">En línea</span>
                            </div>
                        </div>
                    </div>
                    <div class="twins-ia-header-actions">
                        <button type="button" id="twinsIaBtnReset" class="twins-ia-btn-icon" title="Reiniciar conversación" aria-label="Reiniciar conversación">↺</button>
                        <button type="button" id="twinsIaBtnClose" class="twins-ia-btn-icon" title="Cerrar ventana" aria-label="Cerrar ventana">✕</button>
                    </div>
                </header>

                <!-- CHIPS DE CONSULTA RÁPIDA -->
                <nav class="twins-ia-chips-bar" id="twinsIaChipsBar" aria-label="Preguntas rápidas sugeridas">
                    <!-- Se cargan dinámicamente según el rol -->
                </nav>

                <!-- FEED DE MENSAJES -->
                <div class="twins-ia-messages" id="twinsIaMessages" role="log" aria-live="polite">
                    <!-- Mensaje inicial de bienvenida -->
                </div>

                <!-- FOOTER CON FORMULARIO -->
                <footer class="twins-ia-footer">
                    <form id="twinsIaForm" class="twins-ia-form" autocomplete="off">
                        <input 
                            type="text" 
                            id="twinsIaInput" 
                            class="twins-ia-input" 
                            placeholder="Pregunta sobre pasteles, precios o eventos…" 
                            maxlength="1000"
                            required
                        >
                        <button type="submit" id="twinsIaBtnSend" class="twins-ia-send-btn" title="Enviar consulta" aria-label="Enviar">
                            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                                <line x1="22" y1="2" x2="11" y2="13"></line>
                                <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
                            </svg>
                        </button>
                    </form>
                    <div class="twins-ia-security-note">
                        <svg viewBox="0 0 24 24" width="11" height="11" fill="currentColor">
                            <path d="M12 2L3 7v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V7l-9-5zm0 4a3 3 0 110 6 3 3 0 010-6z"/>
                        </svg>
                        <span>Protegido con RAG & Ciberseguridad TWINS</span>
                    </div>
                </footer>
            </aside>
        `;
        document.body.appendChild(contenedor);

        // Guardar referencias
        elements = {
            container: contenedor,
            trigger: document.getElementById('twinsIaTrigger'),
            window: document.getElementById('twinsIaWindow'),
            title: document.getElementById('twinsIaTitle'),
            roleBadge: document.getElementById('twinsIaRoleBadge'),
            headerAvatar: document.getElementById('twinsIaHeaderAvatar'),
            statusLabel: document.getElementById('twinsIaStatusLabel'),
            chipsBar: document.getElementById('twinsIaChipsBar'),
            messages: document.getElementById('twinsIaMessages'),
            form: document.getElementById('twinsIaForm'),
            input: document.getElementById('twinsIaInput'),
            btnSend: document.getElementById('twinsIaBtnSend'),
            btnClose: document.getElementById('twinsIaBtnClose'),
            btnReset: document.getElementById('twinsIaBtnReset'),
            triggerSub: document.getElementById('twinsTriggerSub'),
        };
    }

    /**
     * Obtiene la hora actual formateada (HH:MM)
     */
    function horaActual() {
        const ahora = new Date();
        return ahora.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    /**
     * Agrega una burbuja de mensaje al feed
     */
    function agregarMensajeDOM(rolEmisor, texto) {
        if (!elements.messages) return;

        const row = document.createElement('div');
        row.className = `twins-ia-message-row ${rolEmisor}`;

        const avatarIcon = rolEmisor === 'user' ? '👤' : (state.rol === 'administrador' ? '📊' : '🎂');
        const formattedHtml = formatearMensaje(texto);

        row.innerHTML = `
            <div class="twins-ia-msg-avatar">${avatarIcon}</div>
            <div class="twins-ia-msg-bubble">
                <div class="twins-ia-msg-content">${formattedHtml}</div>
                <span class="twins-ia-msg-time">${horaActual()}</span>
            </div>
        `;

        elements.messages.appendChild(row);
        elements.messages.scrollTop = elements.messages.scrollHeight;
    }

    /**
     * Muestra el indicador animado de escritura (Typing loader)
     */
    function mostrarCargando(textoLabel) {
        removerCargando();
        const row = document.createElement('div');
        row.id = 'twinsIaTypingRow';
        row.className = 'twins-ia-typing-row';
        row.innerHTML = `
            <div class="twins-ia-typing-dot"></div>
            <div class="twins-ia-typing-dot"></div>
            <div class="twins-ia-typing-dot"></div>
            <span class="twins-ia-typing-label">${textoLabel || 'Consultando base de datos…'}</span>
        `;
        elements.messages.appendChild(row);
        elements.messages.scrollTop = elements.messages.scrollHeight;
        state.isLoading = true;
        if (elements.btnSend) elements.btnSend.disabled = true;
    }

    /**
     * Elimina el indicador animado de escritura
     */
    function removerCargando() {
        const el = document.getElementById('twinsIaTypingRow');
        if (el) el.remove();
        state.isLoading = false;
        if (elements.btnSend) elements.btnSend.disabled = false;
    }

    /**
     * Genera el mensaje de bienvenida adaptado al rol del usuario
     */
    function cargarMensajeBienvenida() {
        elements.messages.innerHTML = '';
        state.historial = [];

        if (state.rol === 'administrador') {
            const bienvenidaAdmin = 
                "👋 **¡Bienvenido al Asistente Analítico de TWINS Bakery!**\n\n" +
                "Estoy conectado a la base de datos en modalidad de **Solo Lectura**. " +
                "Puedo ayudarte a revisar **estadísticas de ventas**, monitorear **inventario real** " +
                "y verificar el **estado de las reservas**.\n\n" +
                "⚠️ *Recordatorio de seguridad: Tengo restringido modificar o cancelar reservas directamente en el chat. " +
                "Para esas acciones utiliza los botones de tu panel.*";
            agregarMensajeDOM('ia', bienvenidaAdmin);
        } else {
            const bienvenidaCliente =
                "🍰 **¡Hola! Bienvenido a TWINS Bakery.**\n\n" +
                "Soy tu asistente virtual. Puedo orientarte sobre nuestros **pasteles artesanales**, " +
                "precios, sabores disponibles y paquetes para **eventos especiales** (bodas, graduaciones, baby shower).\n\n" +
                "💡 *Nota:* Todos nuestros pedidos se retiran en tienda física (no hacemos envíos a domicilio) " +
                "y las reservas se realizan manualmente en nuestro catálogo web. ¿En qué te puedo asesorar hoy?";
            agregarMensajeDOM('ia', bienvenidaCliente);
        }
    }

    /**
     * Carga y renderiza los chips de preguntas rápidas
     */
    function renderizarChips(chips) {
        if (!elements.chipsBar) return;
        elements.chipsBar.innerHTML = '';

        (chips || []).forEach(textoPregunta => {
            const chipBtn = document.createElement('button');
            chipBtn.type = 'button';
            chipBtn.className = 'twins-ia-chip';
            chipBtn.textContent = textoPregunta;
            chipBtn.addEventListener('click', () => {
                // Limpiar prefijo emoji si tiene
                const textoLimpio = textoPregunta.replace(/^[\uD800-\uDBFF\uDC00-\uDFFF\u2600-\u27BF\s]+/g, '').trim();
                enviarPregunta(textoLimpio || textoPregunta);
            });
            elements.chipsBar.appendChild(chipBtn);
        });
    }

    /**
     * Inicializa la configuración desde el backend (/api/ia/info)
     */
    async function cargarConfiguracionInicial() {
        try {
            const headers = { 'Accept': 'application/json' };
            if (state.adminJwt) {
                headers['Authorization'] = `Bearer ${state.adminJwt}`;
            }

            const res = await fetch('/api/ia/info', { headers });
            if (!res.ok) throw new Error(`HTTP error ${res.status}`);

            const data = await res.json();
            if (data.success) {
                state.rol = data.rol || 'cliente';

                // Actualizar UI según el rol
                if (state.rol === 'administrador') {
                    elements.roleBadge.textContent = 'Admin Analytics';
                    elements.roleBadge.classList.add('admin-mode');
                    elements.headerAvatar.textContent = '📊';
                    elements.triggerSub.textContent = 'Inteligencia de Negocios';
                    elements.input.placeholder = 'Consulta métricas, ventas o inventario…';

                    // Si es administrador pero no tiene JWT en storage, solicitarlo
                    if (!state.adminJwt) {
                        solicitarAdminJwt();
                    }
                } else {
                    elements.roleBadge.textContent = 'Cliente';
                    elements.roleBadge.classList.remove('admin-mode');
                    elements.headerAvatar.textContent = '🍰';
                    elements.triggerSub.textContent = 'Atención & Catálogo';
                    elements.input.placeholder = 'Pregunta sobre pasteles, precios o eventos…';
                }

                renderizarChips(data.prompts_rapidos);
                cargarMensajeBienvenida();
            }
        } catch (err) {
            console.warn('[TWINS IA] No se pudo obtener /api/ia/info:', err);
            cargarMensajeBienvenida();
        }
    }

    /**
     * Solicita un JWT administrativo al backend
     */
    async function solicitarAdminJwt() {
        try {
            const res = await fetch('/api/ia/token-admin', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRF-Token': state.csrfToken,
                },
            });
            if (res.ok) {
                const data = await res.json();
                if (data.success && data.token) {
                    state.adminJwt = data.token;
                    sessionStorage.setItem('twins_admin_jwt', data.token);
                }
            }
        } catch (e) {
            console.info('[TWINS IA] Sesión cliente regular o sin permisos admin.');
        }
    }

    /**
     * Envía la consulta del usuario al backend de Python
     */
    async function enviarPregunta(texto) {
        if (!texto || state.isLoading) return;

        const pregunta = texto.trim();
        if (!pregunta) return;

        // Limpiar input
        elements.input.value = '';

        // Agregar mensaje del usuario a la interfaz
        agregarMensajeDOM('user', pregunta);

        // Mostrar animación de carga
        const labelCarga = state.rol === 'administrador'
            ? 'Analizando métricas del negocio…'
            : 'Consultando pasteles disponibles…';
        mostrarCargando(labelCarga);

        try {
            const headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
            };

            // Incluir JWT si está autenticado como administrador
            if (state.adminJwt) {
                headers['Authorization'] = `Bearer ${state.adminJwt}`;
            }

            // Incluir CSRF token
            if (state.csrfToken) {
                headers['X-CSRF-Token'] = state.csrfToken;
            }

            const payload = {
                mensaje: pregunta,
                historial: state.historial.slice(-6),
            };

            const respuesta = await fetch('/api/ia/chat', {
                method: 'POST',
                headers: headers,
                body: JSON.stringify(payload),
            });

            removerCargando();

            if (!respuesta.ok) {
                if (respuesta.status === 403) {
                    agregarMensajeDOM('ia', '🛡️ **Acceso restringido:** No tienes los permisos necesarios para realizar esta consulta.');
                    return;
                }
                throw new Error(`Error en el servidor: HTTP ${respuesta.status}`);
            }

            const data = await respuesta.json();

            if (data.success && data.respuesta) {
                agregarMensajeDOM('ia', data.respuesta);

                // Guardar en el historial de conversación en memoria
                state.historial.push({ rol: 'usuario', texto: pregunta });
                state.historial.push({ rol: 'ia', texto: data.respuesta });

                // Truncar historial si excede
                if (state.historial.length > 12) {
                    state.historial = state.historial.slice(-12);
                }
            } else {
                agregarMensajeDOM('ia', data.error || 'No fue posible obtener una respuesta.');
            }

        } catch (error) {
            removerCargando();
            console.error('[TWINS IA Error]:', error);
            agregarMensajeDOM(
                'ia',
                '⚠️ Ocurrió un problema de conexión al consultar con el asistente. ' +
                'Por favor, revisa tu conexión a internet e inténtalo de nuevo.'
            );
        }
    }

    /**
     * Alterna la visibilidad de la ventana del chat
     */
    function toggleChat(forzarEstado) {
        state.isOpen = typeof forzarEstado === 'boolean' ? forzarEstado : !state.isOpen;

        if (state.isOpen) {
            elements.window.removeAttribute('hidden');
            // Forzar reflow para animación CSS
            void elements.window.offsetWidth;
            elements.window.classList.add('is-open');
            elements.input.focus();
        } else {
            elements.window.classList.remove('is-open');
            setTimeout(() => {
                if (!state.isOpen) {
                    elements.window.setAttribute('hidden', '');
                }
            }, 280);
        }
    }

    /**
     * Inicialización principal
     */
    function inicializar() {
        inyectarEstructuraDOM();
        state.csrfToken = obtenerCsrfToken();

        // Event Listeners
        elements.trigger.addEventListener('click', () => toggleChat());
        elements.btnClose.addEventListener('click', () => toggleChat(false));

        elements.btnReset.addEventListener('click', () => {
            if (confirm('¿Deseas reiniciar la conversación con el asistente?')) {
                cargarMensajeBienvenida();
            }
        });

        elements.form.addEventListener('submit', (e) => {
            e.preventDefault();
            enviarPregunta(elements.input.value);
        });

        // Cerrar con Escape
        window.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && state.isOpen) {
                toggleChat(false);
            }
        });

        // Cargar información inicial desde el servidor
        cargarConfiguracionInicial();
    }

    // Exponer API global
    window.TwinsIAChat = {
        init: inicializar,
        toggle: toggleChat,
        send: enviarPregunta,
    };

    // Auto-iniciar al cargar el DOM
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', inicializar);
    } else {
        inicializar();
    }
})();
