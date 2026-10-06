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
            <td>${window.ProductStore.escapeHtml(product.categoria || "Sin categoría")}</td>
            <td>${window.ProductStore.formatPrice(product.precio)}</td>
            <td>${product.en_vitrina ? '<span class="status available">Sí</span>' : '<span class="status unavailable">No</span>'}</td>
            <td><span class="status ${product.disponible && product.categoria && product.tiene_imagen ? "available" : "unavailable"}">${product.disponible && product.categoria && product.tiene_imagen ? "Activo" : "Completar"}</span></td>
            <td><div class="row-actions"><button type="button" data-edit="${product.id}">Editar</button><button class="delete-action" type="button" data-delete="${product.id}">Eliminar</button></div></td>
        </tr>`).join("");
    }

    async function loadProducts() {
        list.innerHTML = "";
        document.querySelector("[data-empty-list]").hidden = true;
        try {
            products = await window.ProductStore.getAll({ admin: true });
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
        form.elements.disponible.value = String(product.disponible);
        form.elements.en_vitrina.checked = Boolean(product.en_vitrina);
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

        const producto = {
            id: form.elements.id.value,
            nombre: form.elements.nombre.value.trim(),
            categoria: form.elements.categoria.value,
            precio: Number(form.elements.precio.value),
            descripcion: form.elements.descripcion.value.trim(),
            disponible: form.elements.disponible.value === "true",
            en_vitrina: form.elements.en_vitrina.checked
        };
        const saveButton = document.querySelector("[data-save-button]");
        saveButton.disabled = true;
        try {
            await window.ProductStore.save(producto, imageFile);
            const listLoaded = await loadProducts();
            resetForm();
            if (listLoaded) {
                showMessage(producto.id ? "Producto actualizado y visible en la tienda." : "Producto agregado y visible en la tienda.");
            } else {
                showMessage("El producto se guardó, pero no se pudo actualizar la lista. Recarga la página.", true);
            }
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
        if (!product || !window.confirm(`¿Eliminar "${product.nombre}" del catálogo?`)) return;
        deleteButton.disabled = true;
        try {
            await window.ProductStore.remove(product.id);
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

    resetForm();
    loadProducts();
})();
