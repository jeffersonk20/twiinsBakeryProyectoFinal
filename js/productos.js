(() => {
    async function getAll({ admin = false } = {}) {
        const response = await fetch(admin ? "/api/admin/productos" : "/api/productos");
        return readResponse(response);
    }

    async function save(producto, imageFile) {
        const formData = new FormData();
        formData.append("nombre", producto.nombre);
        formData.append("categoria", producto.categoria);
        formData.append("precio", String(producto.precio));
        formData.append("descripcion", producto.descripcion);
        formData.append("disponible", String(producto.disponible));
        if (imageFile) formData.append("imagen", imageFile);

        const isEditing = Boolean(producto.id);
        const csrfToken = document.querySelector("[data-admin-app]")?.dataset.csrfToken;
        const response = await fetch(
            isEditing ? `/api/admin/productos/${encodeURIComponent(producto.id)}` : "/api/admin/productos",
            {
                method: isEditing ? "PUT" : "POST",
                headers: csrfToken ? { "X-CSRF-Token": csrfToken } : {},
                body: formData
            }
        );
        return readResponse(response);
    }

    async function remove(id) {
        const csrfToken = document.querySelector("[data-admin-app]")?.dataset.csrfToken;
        const response = await fetch(`/api/admin/productos/${encodeURIComponent(id)}`, {
            method: "DELETE",
            headers: csrfToken ? { "X-CSRF-Token": csrfToken } : {}
        });
        return readResponse(response);
    }

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

    function escapeHtml(value) {
        return String(value).replace(/[&<>"']/g, (character) => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;"
        })[character]);
    }

    function formatPrice(price) {
        return new Intl.NumberFormat("es-US", {
            style: "currency",
            currency: "USD"
        }).format(Number(price));
    }

    function renderCard(producto) {
        const id = encodeURIComponent(producto.id);
        const nombre = escapeHtml(producto.nombre);
        const categoria = escapeHtml(producto.categoria || "Sin categoría");
        const imagen = escapeHtml(producto.imagen);
        const imagenMarkup = imagen
            ? `<img src="${imagen}" alt="${nombre}" loading="lazy">`
            : '<div class="product-image-placeholder" aria-hidden="true">🍰</div>';
        return `<a class="product-card" href="/producto/${id}">
            <div class="product-card-image">${imagenMarkup}<span>${categoria}</span></div>
            <div class="product-card-info"><div><h3>${nombre}</h3><p>${formatPrice(producto.precio)}</p></div><span class="card-arrow" aria-hidden="true">↗</span></div>
        </a>`;
    }

    window.ProductStore = { getAll, save, remove, escapeHtml, formatPrice, renderCard };
})();
