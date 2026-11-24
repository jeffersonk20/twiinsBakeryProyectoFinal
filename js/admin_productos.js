(() => {
    const form = document.querySelector("[data-product-form]");
    const list = document.querySelector("[data-admin-products]");
    if (!form || !list) return;

    const fileInput = document.querySelector("#product-image");
    const preview = document.querySelector("[data-image-preview]");
    const message = document.querySelector("[data-admin-message]");
    const imageError = document.querySelector("[data-image-error]");
    const MAX_IMAGE_SIZE = 1_200_000;
    let products = [];

    async function readResponse(response) {
        let result;
        try {
            result = await response.json();
        } catch {
            throw new Error("El servidor devolvió una respuesta que no se pudo interpretar.");
        }
        if (!response.ok) {
            throw new Error(result.error || "No se pudo completar la operación.");
        }
        return result;
    }

    async function loadAdminProducts() {
        return readResponse(await fetch("/api/admin/productos"));
    }

    async function saveProduct(producto, imageFile) {
        const formData = new FormData();
        formData.append("nombre", producto.nombre);
        formData.append("categoria", producto.categoria);
        formData.append("precio", String(producto.precio));
        formData.append("descripcion", producto.descripcion);
        formData.append("stock", String(producto.stock));
        formData.append("disponible", String(producto.disponible));
        formData.append("en_vitrina", String(producto.en_vitrina));
        formData.append("canjeable_puntos", String(producto.canjeable_puntos));
        formData.append("puntos_canje", String(producto.puntos_canje));
        formData.append("genera_puntos", String(producto.genera_puntos));
        formData.append("se_vende_por_porciones", String(producto.se_vende_por_porciones));
        formData.append("numero_porciones", String(producto.numero_porciones || ""));
        formData.append("precio_porcion", String(producto.precio_porcion !== null && producto.precio_porcion !== undefined ? producto.precio_porcion : ""));
        if (imageFile) formData.append("imagen", imageFile);

        const isEditing = Boolean(producto.id);
        const csrfToken = document.querySelector("[data-admin-app]").dataset.csrfToken;
        const response = await fetch(
            isEditing ? `/api/admin/productos/${encodeURIComponent(producto.id)}` : "/api/admin/productos",
            {
                method: isEditing ? "PUT" : "POST",
                headers: { "X-CSRF-Token": csrfToken },
                body: formData
            }
        );
        return readResponse(response);
    }

    async function deleteProduct(id) {
        const csrfToken = document.querySelector("[data-admin-app]").dataset.csrfToken;
        const response = await fetch(`/api/admin/productos/${encodeURIComponent(id)}`, {
            method: "DELETE",
            headers: { "X-CSRF-Token": csrfToken }
        });
        return readResponse(response);
    }

    function showMessage(text, isError = false) {
        message.textContent = text;
        message.classList.toggle("error", isError);
        message.hidden = false;
    }

    function setPreview(source) {
        preview.replaceChildren();
        if (!source) {
            const icon = document.createElement("span");
            icon.setAttribute("aria-hidden", "true");
            icon.textContent = "🍰";
            const label = document.createElement("p");
            label.textContent = "Vista previa del producto";
            preview.append(icon, label);
            return;
        }
        const image = document.createElement("img");
        image.src = source;
        image.alt = "Vista previa del producto";
        preview.append(image);
    }

    function renderList() {
        document.querySelector("[data-product-count]").textContent = products.length;
        document.querySelector("[data-empty-list]").hidden = products.length > 0;
        list.innerHTML = products.map((product) => `<tr>
            <td><div class="table-product">${product.tiene_imagen ? `<img src="${window.ProductStore.escapeHtml(product.imagen)}" alt="">` : '<span class="table-image-placeholder" aria-hidden="true">🍰</span>'}<strong>${window.ProductStore.escapeHtml(product.nombre)}</strong></div></td>
            <td>${window.ProductStore.escapeHtml(product.categoria || "Sin categoría")}${product.se_vende_por_porciones ? `<br><small style="color:#059669;font-weight:600;display:inline-block;margin-top:4px;">🍰 ${product.numero_porciones} porc. · $${Number(product.precio_porcion).toFixed(2)} c/u</small>` : ''}</td>
            <td>${window.ProductStore.formatPrice(product.precio)}</td>
            <td>${product.stock}</td>
            <td>${product.en_vitrina ? '<span class="status available">Sí</span>' : '<span class="status unavailable">No</span>'}${product.canjeable_puntos ? `<br><small style="color:#db2777;font-weight:600;display:inline-block;margin-top:4px;">🎁 ${product.puntos_canje || 50} pts</small>` : ''}</td>
            <td><span class="status ${product.disponible && product.stock > 0 && product.categoria && product.tiene_imagen ? "available" : "unavailable"}">${product.stock === 0 || !product.disponible ? "Agotado" : product.categoria && product.tiene_imagen ? "Activo" : "Completar"}</span></td>
            <td><div class="row-actions"><button type="button" data-edit="${product.id}">Editar</button><button class="delete-action" type="button" data-delete="${product.id}">Eliminar</button></div></td>
        </tr>`).join("");
    }

    async function loadProducts() {
        list.innerHTML = "";
        document.querySelector("[data-empty-list]").hidden = true;
        try {
            products = await loadAdminProducts();
            renderList();
            return true;
        } catch (error) {
            showMessage(`No se pudieron cargar los productos: ${error.message}`, true);
            return false;
        }
    }

    function resetForm() {
        form.reset();
        form.elements.id.value = "";
        fileInput.required = true;
        fileInput.value = "";
        document.querySelector("[data-form-heading]").textContent = "Nuevo producto";
        document.querySelector("[data-save-button]").textContent = "Guardar producto";
        imageError.hidden = true;
        message.hidden = true;
        setPreview("");
        if (form.elements.canjeable_puntos) form.elements.canjeable_puntos.checked = false;
        if (form.elements.puntos_canje) form.elements.puntos_canje.value = 50;
        if (form.elements.genera_puntos) form.elements.genera_puntos.checked = true;
        const fieldCanje = document.getElementById("field-puntos-canje");
        if (fieldCanje) fieldCanje.style.display = "none";
        if (form.elements.se_vende_por_porciones) form.elements.se_vende_por_porciones.checked = false;
        if (form.elements.numero_porciones) form.elements.numero_porciones.value = "";
        if (form.elements.precio_porcion) form.elements.precio_porcion.value = "";
        const fieldsPorciones = document.getElementById("fields-porciones");
        if (fieldsPorciones) fieldsPorciones.style.display = "none";
    }

    function editProduct(id) {
        const product = products.find((item) => String(item.id) === id);
        if (!product) {
            showMessage("No se encontró el producto seleccionado. Actualiza la lista e inténtalo de nuevo.", true);
            return;
        }
        form.elements.id.value = product.id;
        form.elements.nombre.value = product.nombre;
        form.elements.categoria.value = product.categoria || "";
        form.elements.precio.value = product.precio;
        form.elements.descripcion.value = product.descripcion;
        form.elements.stock.value = product.stock;
        form.elements.disponible.value = String(product.disponible);
        form.elements.en_vitrina.checked = Boolean(product.en_vitrina);
        if (form.elements.canjeable_puntos) {
            form.elements.canjeable_puntos.checked = Boolean(product.canjeable_puntos);
        }
        if (form.elements.puntos_canje) {
            form.elements.puntos_canje.value = product.puntos_canje || 50;
        }
        if (form.elements.genera_puntos) {
            form.elements.genera_puntos.checked = product.genera_puntos !== undefined ? Boolean(product.genera_puntos) : true;
        }
        const fieldCanje = document.getElementById("field-puntos-canje");
        if (fieldCanje) {
            fieldCanje.style.display = product.canjeable_puntos ? "block" : "none";
        }
        const seVendePorciones = Boolean(product.se_vende_por_porciones);
        if (form.elements.se_vende_por_porciones) {
            form.elements.se_vende_por_porciones.checked = seVendePorciones;
        }
        if (form.elements.numero_porciones) {
            form.elements.numero_porciones.value = product.numero_porciones || "";
        }
        if (form.elements.precio_porcion) {
            form.elements.precio_porcion.value = product.precio_porcion !== null && product.precio_porcion !== undefined ? product.precio_porcion : "";
        }
        const fieldsPorciones = document.getElementById("fields-porciones");
        if (fieldsPorciones) {
            fieldsPorciones.style.display = seVendePorciones ? "block" : "none";
        }
        fileInput.value = "";
        fileInput.required = !product.tiene_imagen;
        document.querySelector("[data-form-heading]").textContent = "Editar producto";
        document.querySelector("[data-save-button]").textContent = "Guardar cambios";
        setPreview(product.imagen);
        message.hidden = true;
        document.querySelector(".editor-panel").scrollIntoView({ behavior: "smooth", block: "start" });
    }

    fileInput.addEventListener("change", () => {
        imageError.hidden = true;
        const file = fileInput.files[0];
        if (!file) return;
        if (!["image/jpeg", "image/png", "image/webp"].includes(file.type)) {
            imageError.textContent = "Selecciona una imagen JPG, PNG o WEBP.";
            imageError.hidden = false;
            fileInput.value = "";
            return;
        }
        if (file.size > MAX_IMAGE_SIZE) {
            imageError.textContent = "La imagen supera el límite de 1.2 MB.";
            imageError.hidden = false;
            fileInput.value = "";
            return;
        }
        const reader = new FileReader();
        reader.onload = () => setPreview(reader.result);
        reader.onerror = () => {
            imageError.textContent = "No se pudo leer la imagen seleccionada.";
            imageError.hidden = false;
        };
        reader.readAsDataURL(file);
    });

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        imageError.hidden = true;
        const imageFile = fileInput.files[0];
        if (!form.reportValidity()) return;
        if (!form.elements.id.value && !imageFile) {
            showMessage("Selecciona una imagen para el producto.", true);
            return;
        }

        const canjeable = form.elements.canjeable_puntos ? form.elements.canjeable_puntos.checked : false;
        let puntosCanje = 50;
        if (canjeable) {
            puntosCanje = Number(form.elements.puntos_canje ? form.elements.puntos_canje.value : 50);
            if (puntosCanje < 50) {
                showMessage("La cantidad mínima para configurar un producto canjeable es de 50 puntos.", true);
                return;
            }
        }
        const generaPuntos = form.elements.genera_puntos ? form.elements.genera_puntos.checked : true;
        const seVendePorciones = form.elements.se_vende_por_porciones ? form.elements.se_vende_por_porciones.checked : false;
        let numeroPorciones = null;
        let precioPorcion = null;
        if (seVendePorciones) {
            numeroPorciones = Number(form.elements.numero_porciones ? form.elements.numero_porciones.value : 0);
            if (!numeroPorciones || numeroPorciones < 1) {
                showMessage("Indica en cuántas porciones se divide el pastel (mínimo 1).", true);
                return;
            }
            precioPorcion = Number(form.elements.precio_porcion ? form.elements.precio_porcion.value : 0);
            if (!precioPorcion || precioPorcion <= 0) {
                showMessage("Indica un precio válido mayor a 0 para cada porción.", true);
                return;
            }
        }

        const producto = {
            id: form.elements.id.value,
            nombre: form.elements.nombre.value.trim(),
            categoria: form.elements.categoria.value,
            precio: Number(form.elements.precio.value),
            descripcion: form.elements.descripcion.value.trim(),
            stock: Number(form.elements.stock.value),
            disponible: form.elements.disponible.value === "true",
            en_vitrina: form.elements.en_vitrina.checked,
            se_vende_por_porciones: seVendePorciones,
            numero_porciones: numeroPorciones,
            precio_porcion: precioPorcion,
            canjeable_puntos: canjeable,
            puntos_canje: puntosCanje,
            genera_puntos: generaPuntos
        };
        const saveButton = document.querySelector("[data-save-button]");
        saveButton.disabled = true;
        try {
            await saveProduct(producto, imageFile);
            sessionStorage.setItem(
                "admin_producto_msg",
                producto.id
                    ? "¡Producto e imagen actualizados con éxito!"
                    : "¡Producto agregado con éxito!"
            );
            window.location.reload();
            return;
        } catch (error) {
            showMessage(`No se pudo guardar el producto: ${error.message}`, true);
        } finally {
            saveButton.disabled = false;
        }
    });

    list.addEventListener("click", async (event) => {
        const editButton = event.target.closest("[data-edit]");
        if (editButton) {
            editProduct(editButton.dataset.edit);
            return;
        }
        const deleteButton = event.target.closest("[data-delete]");
        if (!deleteButton) return;
        const product = products.find((item) => String(item.id) === deleteButton.dataset.delete);
        if (!product || !window.confirm(`¿Eliminar "${product.nombre}" del catálogo? El historial de reservas conservará los datos del producto.`)) return;
        deleteButton.disabled = true;
        try {
            await deleteProduct(product.id);
            if (await loadProducts()) {
                showMessage("Producto eliminado del catálogo.");
            } else {
                showMessage("El producto se eliminó, pero no se pudo actualizar la lista. Recarga la página.", true);
            }
        } catch (error) {
            showMessage(`No se pudo eliminar el producto: ${error.message}`, true);
            deleteButton.disabled = false;
        }
    });

    document.querySelectorAll("[data-reset-form]").forEach((button) => {
        button.addEventListener("click", resetForm);
    });

    const inputCanjeable = document.getElementById("input-canjeable-puntos");
    const fieldPuntosCanje = document.getElementById("field-puntos-canje");
    if (inputCanjeable && fieldPuntosCanje) {
        inputCanjeable.addEventListener("change", () => {
            fieldPuntosCanje.style.display = inputCanjeable.checked ? "block" : "none";
            const numInput = document.getElementById("product-puntos-canje");
            if (numInput) {
                numInput.required = inputCanjeable.checked;
                if (inputCanjeable.checked && (!numInput.value || Number(numInput.value) < 50)) {
                    numInput.value = 50;
                }
            }
        });
    }

    const inputPorciones = document.getElementById("input-se-vende-porciones");
    const fieldsPorciones = document.getElementById("fields-porciones");
    const numPorcionesInput = document.getElementById("product-num-porciones");
    const precioPorcionInput = document.getElementById("product-precio-porcion");
    if (inputPorciones && fieldsPorciones) {
        inputPorciones.addEventListener("change", () => {
            const checked = inputPorciones.checked;
            fieldsPorciones.style.display = checked ? "block" : "none";
            if (numPorcionesInput) numPorcionesInput.required = checked;
            if (precioPorcionInput) precioPorcionInput.required = checked;
            if (checked && categorySelect && (!categorySelect.value || categorySelect.value === "Pasteles")) {
                categorySelect.value = "Porciones de Pasteles";
            }
        });
    }

    const categorySelect = document.getElementById("product-category");
    const generaCheck = document.getElementById("input-genera-puntos");
    if (categorySelect && generaCheck) {
        categorySelect.addEventListener("change", () => {
            if (categorySelect.value === "Bebidas" || categorySelect.value === "Eventos") {
                // Por regla del negocio, las bebidas individuales y eventos no acumulan puntos por defecto
                generaCheck.checked = false;
            } else {
                generaCheck.checked = true;
            }
        });
    }

    resetForm();
    loadProducts();

    const savedMsg = sessionStorage.getItem("admin_producto_msg");
    if (savedMsg) {
        showMessage(savedMsg);
        sessionStorage.removeItem("admin_producto_msg");
    }
})();
