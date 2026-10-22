(() => {
    const root = document.querySelector("[data-admin-chat]");
    const csrfToken = root ? root.dataset.csrfToken : "";
    const listBody = document.getElementById("convListBody");
    const activeTitle = document.getElementById("activeConvTitle");
    const activeSub = document.getElementById("activeConvSub");
    const feed = document.getElementById("adminMessagesFeed");
    const replyFooter = document.getElementById("replyFooter");
    const replyForm = document.getElementById("adminReplyForm");
    const replyInput = document.getElementById("adminReplyInput");
    const replyType = document.getElementById("replyTargetType");
    const replyId = document.getElementById("replyTargetId");
    const btnSend = document.getElementById("btnAdminSend");
    const tabButtons = document.querySelectorAll("[data-tab]");

    let activeType = null; // 'general' or 'evento'
    let activeId = null;
    let currentTab = "general";
    let conversations = { general: [], eventos: [] };
    let lastMsgCount = 0;

    function escapeHtml(value) {
        return String(value ?? "").replace(/[&<>"']/g, char => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;"
        })[char]);
    }

    function formatTime(isoString) {
        if (!isoString) return "";
        try {
            const date = new Date(String(isoString).replace(" ", "T"));
            if (Number.isNaN(date.getTime())) return isoString;
            return new Intl.DateTimeFormat("es", {
                hour: "numeric",
                minute: "numeric",
                hour12: true
            }).format(date);
        } catch {
            return "";
        }
    }

    async function loadConversations() {
        try {
            const res = await fetch("/api/admin/chats");
            if (!res.ok) throw new Error("Error al consultar conversaciones.");
            const data = await res.json();
            conversations.general = data.general || [];
            conversations.eventos = data.eventos || [];
            renderConversationList();
        } catch (err) {
            console.error("Error al cargar lista de chats:", err);
        }
    }

    function renderConversationList() {
        const list = currentTab === "general" ? conversations.general : conversations.eventos;

        if (list.length === 0) {
            listBody.innerHTML = `
                <div style="text-align:center; padding: 30px 10px; color: #a4b3b7; font-size: 11px;">
                    No hay conversaciones de ${currentTab === 'general' ? 'clientes' : 'eventos'}.
                </div>
            `;
            return;
        }

        listBody.innerHTML = list.map(item => {
            const isGeneral = currentTab === "general";
            const id = isGeneral ? item.id_chat : item.id_chat_evento;
            const title = isGeneral ? (item.cliente_nombre || item.cliente_correo) : item.titulo;
            const preview = item.ultimo_mensaje || (isGeneral ? "Chat con cliente" : "Coordinación de evento");
            const avatarInitial = (title.trim()[0] || "C").toUpperCase();
            const isActive = activeType === currentTab && String(activeId) === String(id);

            return `
                <button type="button" class="admin-conv-card ${isActive ? 'active' : ''}" data-type="${currentTab}" data-id="${id}">
                    <div class="card-avatar ${isGeneral ? '' : 'event-icon'}">
                        ${isGeneral ? avatarInitial : '🎉'}
                    </div>
                    <div class="card-text">
                        <strong>${escapeHtml(title)}</strong>
                        <p>${escapeHtml(preview)}</p>
                    </div>
                </button>
            `;
        }).join("");
    }

    async function openConversation(type, id, scrollDown = true) {
        activeType = type;
        activeId = id;
        replyType.value = type;
        replyId.value = id;
        replyFooter.hidden = false;

        // Header info
        const isGeneral = type === "general";
        const list = isGeneral ? conversations.general : conversations.eventos;
        const current = list.find(item => String(isGeneral ? item.id_chat : item.id_chat_evento) === String(id));

        if (current) {
            activeTitle.textContent = isGeneral ? (current.cliente_nombre || "Cliente") : current.titulo;
            activeSub.textContent = isGeneral ? (current.cliente_correo || "Chat General") : `Fecha evento: ${current.fecha_evento || 'Por definir'}`;
        }

        renderConversationList();

        try {
            const endpoint = isGeneral 
                ? `/api/admin/chat/${id}/mensajes` 
                : `/api/chat-evento/${id}/mensajes`;

            const res = await fetch(endpoint);
            if (!res.ok) throw new Error("No se pudieron cargar los mensajes.");
            const data = await res.json();
            const mensajes = data.mensajes || [];

            if (mensajes.length === 0) {
                feed.innerHTML = `
                    <div class="empty-feed-placeholder">
                        <span>👋</span>
                        <p>No hay mensajes en este chat aún. Escribe el primer mensaje a continuación.</p>
                    </div>
                `;
                return;
            }

            if (mensajes.length !== lastMsgCount) {
                feed.innerHTML = mensajes.map(m => {
                    const isAdmin = m.rol === "admin";
                    return `
                        <div class="msg-row ${isAdmin ? 'admin-msg' : 'client-msg'}">
                            <span class="msg-sender-tag">${isAdmin ? 'Administrador (Tú)' : 'Cliente'}</span>
                            <div class="msg-bubble-content">
                                ${escapeHtml(m.mensaje)}
                            </div>
                            <span class="msg-timestamp">${escapeHtml(formatTime(m.fecha_envio))}</span>
                        </div>
                    `;
                }).join("");

                lastMsgCount = mensajes.length;
                if (scrollDown) {
                    feed.scrollTop = feed.scrollHeight;
                }
            }
        } catch (err) {
            console.error("Error al cargar mensajes del chat:", err);
        }
    }

    // Tabs de conversación
    tabButtons.forEach(btn => {
        btn.addEventListener("click", () => {
            tabButtons.forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            currentTab = btn.dataset.tab;
            renderConversationList();
        });
    });

    // Clic en conversación
    listBody.addEventListener("click", (e) => {
        const card = e.target.closest("[data-id]");
        if (!card) return;
        lastMsgCount = 0;
        openConversation(card.dataset.type, card.dataset.id, true);
    });

    // Envío de respuesta
    if (replyForm) {
        replyForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const text = replyInput.value.trim();
            if (!text || !activeId || !activeType) return;

            btnSend.disabled = true;
            try {
                const endpoint = activeType === "general"
                    ? `/api/admin/chat/${activeId}/mensaje`
                    : `/api/chat-evento/${activeId}/mensaje`;

                const res = await fetch(endpoint, {
                    method: "POST",
                    headers: { 
                        "Content-Type": "application/json",
                        "X-CSRF-Token": csrfToken
                    },
                    body: JSON.stringify({ mensaje: text })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || "No se pudo enviar la respuesta.");

                replyInput.value = "";
                await openConversation(activeType, activeId, true);
                await loadConversations();
            } catch (err) {
                alert(err.message || "Error al enviar mensaje.");
            } finally {
                btnSend.disabled = false;
                replyInput.focus();
            }
        });
    }

    loadConversations().then(() => {
        // Si hay una conversación en la lista, abrir la primera por defecto
        if (conversations.general.length > 0) {
            openConversation("general", conversations.general[0].id_chat, true);
        } else if (conversations.eventos.length > 0) {
            currentTab = "eventos";
            tabButtons.forEach(b => b.classList.toggle("active", b.dataset.tab === "eventos"));
            renderConversationList();
            openConversation("eventos", conversations.eventos[0].id_chat_evento, true);
        }
    });

    // Polling del chat activo cada 3.5s
    setInterval(() => {
        if (activeType && activeId) {
            openConversation(activeType, activeId, false);
        }
    }, 3500);
})();
