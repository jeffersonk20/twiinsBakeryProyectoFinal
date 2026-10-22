(() => {
    const container = document.querySelector("[data-chat-evento-id]");
    if (!container) return;

    const chatEventoId = container.dataset.chatEventoId;
    const esAdmin = container.dataset.esAdmin === "true";
    const feed = document.getElementById("chatFeed");
    const form = document.getElementById("chatForm");
    const input = document.getElementById("mensajeInput");
    const btnEnviar = document.getElementById("btnEnviar");

    let lastMessageCount = 0;

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

    async function loadMessages(scrollDown = false) {
        try {
            const res = await fetch(`/api/chat-evento/${chatEventoId}/mensajes`);
            if (!res.ok) throw new Error("No se pudieron cargar los mensajes.");
            const data = await res.json();
            const mensajes = data.mensajes || [];

            if (mensajes.length === 0) {
                feed.innerHTML = `
                    <div class="empty-chat-state">
                        <p style="font-size: 24px; margin-bottom: 8px;">🎂</p>
                        <strong>¡Comienza la conversación!</strong>
                        <p style="margin-top: 4px;">Escribe un mensaje para coordinar los detalles del evento.</p>
                    </div>
                `;
                return;
            }

            if (mensajes.length !== lastMessageCount) {
                feed.innerHTML = mensajes.map(msg => {
                    const isMe = (esAdmin && msg.rol === "admin") || (!esAdmin && msg.rol === "cliente");
                    const senderLabel = msg.rol === "admin" ? "TWINS Bakery (Admin)" : "Cliente";
                    const bubbleClass = msg.rol === "admin" ? "bubble-admin" : "bubble-cliente";

                    return `
                        <div class="message-row ${isMe ? 'is-me' : 'is-other'}">
                            <span class="message-sender">${senderLabel}</span>
                            <div class="message-bubble ${bubbleClass}">
                                ${escapeHtml(msg.mensaje)}
                            </div>
                            <span class="message-time">${escapeHtml(formatTime(msg.fecha_envio))}</span>
                        </div>
                    `;
                }).join("");

                lastMessageCount = mensajes.length;
                if (scrollDown) {
                    feed.scrollTop = feed.scrollHeight;
                }
            }
        } catch (err) {
            console.error("Error al cargar mensajes:", err);
        }
    }

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const texto = input.value.trim();
        if (!texto) return;

        btnEnviar.disabled = true;
        try {
            const res = await fetch(`/api/chat-evento/${chatEventoId}/mensaje`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({ mensaje: texto })
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.error || "No se pudo enviar el mensaje.");

            input.value = "";
            await loadMessages(true);
        } catch (err) {
            alert(err.message || "Error al enviar mensaje.");
        } finally {
            btnEnviar.disabled = false;
            input.focus();
        }
    });

    // Carga inicial y sondeo periódico cada 3 segundos
    loadMessages(true);
    setInterval(() => loadMessages(false), 3000);
})();
