(() => {
    const app = document.querySelector("[data-admin-settings]");
    if (!app) return;

    const dialog = document.querySelector("[data-delete-dialog]");
    const form = document.querySelector("[data-delete-form]");
    const message = app.querySelector("[data-admin-message]");

    app.querySelector("[data-open-delete]").addEventListener("click", () => {
        form.reset();
        dialog.showModal();
    });
    document.querySelector("[data-cancel-delete]").addEventListener("click", () => dialog.close());

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        try {
            const response = await fetch("/api/admin/usuario", {
                method: "DELETE",
                headers: {
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-CSRF-Token": app.dataset.csrfToken
                },
                body: new URLSearchParams(new FormData(form))
            });
            let result;
            try {
                result = await response.json();
            } catch {
                throw new Error("El servidor devolvió una respuesta que no se pudo interpretar.");
            }
            if (!response.ok) throw new Error(result.error || "No se pudo eliminar el usuario administrador.");
            window.location.assign("/admin/login");
        } catch (error) {
            message.textContent = error.message || "No se pudo conectar con el servidor.";
            message.classList.add("error");
            message.hidden = false;
        }
    });
})();
