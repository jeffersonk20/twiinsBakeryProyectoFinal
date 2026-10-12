(() => {
    async function getAll({ vitrina = false } = {}) {
        const endpoint = `/api/productos${vitrina ? "?vitrina=1" : ""}`;
        const response = await fetch(endpoint);
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

    window.ProductStore = { getAll, escapeHtml, formatPrice, renderCard };
})();
