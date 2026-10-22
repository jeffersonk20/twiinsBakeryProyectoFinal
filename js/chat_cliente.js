(() => {
    const feed = document.getElementById("clientChatFeed");
    const form = document.getElementById("clientChatForm");
    const input = document.getElementById("clientMsgInput");
    const btnSend = document.getElementById("btnSendClient");
    const eventChatsList = document.getElementById("eventChatsList");

    let lastCount = 0;

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

    async function loadClientMessages(scrollDown = false) {
        try {
            const res = await fetch("/api/chat/mensajes");
            if (!res.ok) throw new Error("No se pudieron consultar los mensajes.");
            const data = await res.json();
            const mensajes = data.mensajes || [];

            if (mensajes.length === 0) {
                feed.innerHTML = `
                    <div style="text-align: center; margin: auto; color: #8c999e; font-size: 12px;">
                        <p style="font-size: 26px; margin-bottom: 6px;">💬</p>
                        <strong>¡Bienvenido al chat de TWINS Bakery!</strong>
                        <p style="margin-top: 4px;">Envíanos cualquier consulta sobre tus pedidos, reservas o dudas generales.</p>
                    </div>
                `;
                return;
            }

            if (mensajes.length !== lastCount) {
                feed.innerHTML = mensajes.map(msg => {
                    const isMine = msg.rol === "cliente";
                    const senderLabel = isMine ? "Tú" : "TWINS Bakery";

                    return `
                        <div class="client-msg-row ${isMine ? 'mine' : 'theirs'}">
                            <span class="client-msg-sender">${senderLabel}</span>
                            <div class="client-msg-bubble">
                                ${escapeHtml(msg.mensaje)}
                            </div>
                            <span class="client-msg-time">${escapeHtml(formatTime(msg.fecha_envio))}</span>
                        </div>
                    `;
                }).join("");

                lastCount = mensajes.length;
                if (scrollDown) {
                    feed.scrollTop = feed.scrollHeight;
                }
            }
        } catch (err) {
            console.error("Error al cargar mensajes:", err);
        }
    }

    async function loadClientEventChats() {
        if (!eventChatsList) return;
        try {
            const res = await fetch("/api/cliente/chats-eventos");
            if (!res.ok) return;
            const data = await res.json();
            const chats = data.chats || [];

            if (chats.length === 0) {
                eventChatsList.innerHTML = `
                    <p style="font-size: 10px; color: #a4b3b7; padding: 4px 10px; margin: 0;">
                        No tienes eventos activos.
                    </p>
                `;
                return;
            }

            eventChatsList.innerHTML = chats.map(c => `
                <a href="/chat/evento/${c.id_chat_evento}" class="event-chat-link">
                    <span>🎉</span>
                    <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                        ${escapeHtml(c.titulo)}
                    </span>
                </a>
            `).join("");
        } catch (err) {
            console.error("Error al consultar chats de eventos del cliente:", err);
        }
    }

    if (form) {
        form.addEventListener("submit", async (e) => {
            e.preventDefault();
            const text = input.value.trim();
            if (!text) return;

            btnSend.disabled = true;
            try {
                const res = await fetch("/api/chat/mensaje", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ mensaje: text })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.error || "No se pudo enviar el mensaje.");

                input.value = "";
                await loadClientMessages(true);
            } catch (err) {
                alert(err.message || "Error al enviar el mensaje.");
            } finally {
                btnSend.disabled = false;
                input.focus();
            }
        });
    }

    loadClientMessages(true);
    loadClientEventChats();
    setInterval(() => loadClientMessages(false), 3500);
})();
