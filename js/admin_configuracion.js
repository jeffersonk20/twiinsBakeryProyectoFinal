(() => {
    const app = document.querySelector("[data-admin-settings]");
    if (!app) return;

    const dialog = document.querySelector("[data-delete-dialog]");
    const form = document.querySelector("[data-delete-form]");
    const message = app.querySelector("[data-admin-message]");

    const openDeleteBtn = app.querySelector("[data-open-delete]");
    if (openDeleteBtn && dialog && form) {
        openDeleteBtn.addEventListener("click", () => {
            form.reset();
            dialog.showModal();
        });
    }

    const cancelDeleteBtn = document.querySelector("[data-cancel-delete]");
    if (cancelDeleteBtn && dialog) {
        cancelDeleteBtn.addEventListener("click", () => dialog.close());
    }

    if (form) {
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
    }

    // ── GESTIÓN DE CARRUSEL DE IMÁGENES HOME CLIENTE ──
    const formCarrusel = document.getElementById("formCarruselHome");
    const inputCarrusel = document.getElementById("inputImagenesCarrusel");
    const carruselStatus = document.getElementById("carruselStatusText");
    const carruselPreviews = document.getElementById("carruselPreviewContainer");
    const btnGuardarCarrusel = document.getElementById("btnGuardarCarrusel");

    if (formCarrusel && inputCarrusel) {
        inputCarrusel.addEventListener("change", () => {
            const files = Array.from(inputCarrusel.files || []);
            carruselPreviews.innerHTML = "";

            if (files.length === 0) {
                carruselStatus.textContent = "Ningún archivo seleccionado";
                btnGuardarCarrusel.disabled = true;
                return;
            }

            if (files.length > 5) {
                carruselStatus.textContent = "Error: Solo se permiten de 1 a 5 imágenes.";
                carruselStatus.style.color = "#c62828";
                btnGuardarCarrusel.disabled = true;
                inputCarrusel.value = "";
                return;
            }

            const maxBytes = 20 * 1024 * 1024; // 20 MB
            const invalidFile = files.find(f => f.size > maxBytes || !f.type.startsWith("image/"));
            if (invalidFile) {
                carruselStatus.textContent = `Error: '${invalidFile.name}' supera 20MB o no es imagen válida.`;
                carruselStatus.style.color = "#c62828";
                btnGuardarCarrusel.disabled = true;
                inputCarrusel.value = "";
                return;
            }

            carruselStatus.textContent = `${files.length} imagen(es) lista(s) para subir`;
            carruselStatus.style.color = "var(--teal, #20b7b2)";
            btnGuardarCarrusel.disabled = false;

            files.forEach((file) => {
                const thumb = document.createElement("div");
                thumb.style.cssText = "width: 76px; height: 76px; border-radius: 12px; overflow: hidden; border: 2px solid var(--teal, #20b7b2); box-shadow: 0 4px 10px rgba(0,0,0,0.1);";
                const img = document.createElement("img");
                img.style.cssText = "width: 100%; height: 100%; object-fit: cover; display: block;";
                img.src = URL.createObjectURL(file);
                thumb.appendChild(img);
                carruselPreviews.appendChild(thumb);
            });
        });

        formCarrusel.addEventListener("submit", async (e) => {
            e.preventDefault();
            const files = inputCarrusel.files;
            if (!files || files.length === 0) return;

            const formData = new FormData();
            formData.append("csrf_token", app.dataset.csrfToken);
            Array.from(files).forEach(f => formData.append("imagenes", f));

            btnGuardarCarrusel.disabled = true;
            btnGuardarCarrusel.textContent = "Guardando en servidor…";

            try {
                const resp = await fetch("/api/admin/home/carrusel", {
                    method: "POST",
                    headers: {
                        "X-CSRF-Token": app.dataset.csrfToken
                    },
                    body: formData
                });
                const data = await resp.json();
                if (!resp.ok) throw new Error(data.error || "No se pudieron actualizar las imágenes.");

                message.textContent = data.mensaje || "Imágenes del carrusel actualizadas correctamente.";
                message.classList.remove("error");
                message.hidden = false;
                carruselStatus.textContent = "¡Cambios aplicados inmediatamente al cliente!";
                carruselStatus.style.color = "#286c50";
            } catch (err) {
                message.textContent = err.message || "Error al subir las imágenes.";
                message.classList.add("error");
                message.hidden = false;
            } finally {
                btnGuardarCarrusel.disabled = false;
                btnGuardarCarrusel.textContent = "Guardar imágenes en el servidor";
            }
        });
    }
})();
