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
        const esPorcion = Boolean(producto.se_vende_por_porciones || producto.categoria === "Porciones de Pasteles");
        const categoria = esPorcion ? "Porciones de Pasteles" : escapeHtml(producto.categoria || "Sin categoría");
        const imagen = escapeHtml(producto.imagen);
        const imagenMarkup = imagen
            ? `<img src="${imagen}" alt="${nombre}" loading="lazy">`
            : '<div class="product-image-placeholder" aria-hidden="true">🍰</div>';

        const precioHtml = (esPorcion && producto.precio_porcion)
            ? `<p class="price-portion">${formatPrice(producto.precio_porcion)} <small style="font-size: 11px; font-weight: normal; color: #64748b;">/ porción</small></p>`
            : `<p>${formatPrice(producto.precio)}</p>`;

        const extraInfo = (esPorcion && producto.numero_porciones)
            ? `<span style="display:block; font-size: 11px; color: #059669; font-weight: 600; margin-top: 2px;">🍰 Rinde ${producto.numero_porciones} porciones</span>`
            : '';

        return `<a class="product-card" href="/producto/${id}">
            <div class="product-card-image">${imagenMarkup}<span>${categoria}</span></div>
            <div class="product-card-info"><div><h3>${nombre}</h3>${precioHtml}${extraInfo}</div><span class="card-arrow" aria-hidden="true">↗</span></div>
        </a>`;
    }

    window.ProductStore = { getAll, escapeHtml, formatPrice, renderCard };
})();
