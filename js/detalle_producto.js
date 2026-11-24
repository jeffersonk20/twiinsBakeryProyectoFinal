(() => {
    const page = document.querySelector("[data-product-detail]");
    if (!page) return;

    async function loadProduct() {
        try {
            const product = (await window.ProductStore.getAll()).find((item) => (
                String(item.id) === page.dataset.productId
            ));
            if (!product) {
                page.querySelector(".detail-card").hidden = true;
                page.querySelector("[data-product-missing]").hidden = false;
                return;
            }

            const isPortion = Boolean(product.se_vende_por_porciones || product.categoria === "Porciones de Pasteles");
            document.title = `${product.nombre} | TWINS Bakery`;
            page.querySelector("[data-detail-name]").textContent = product.nombre;
            page.querySelectorAll("[data-detail-category]").forEach((element) => {
                element.textContent = isPortion ? "Porciones de Pasteles" : product.categoria;
            });
            const priceEl = page.querySelector("[data-detail-price]");
            if (isPortion && product.precio_porcion) {
                priceEl.innerHTML = `${window.ProductStore.formatPrice(product.precio_porcion)} <span style="font-size: 14px; font-weight: normal; color: #64748b;">/ porción individual</span>`;
            } else {
                priceEl.textContent = window.ProductStore.formatPrice(product.precio);
            }
            let desc = product.descripcion;
            if (isPortion && product.numero_porciones) {
                desc += `\n\n🍰 Venta por porciones: Este delicioso pastel se divide en ${product.numero_porciones} porciones individuales. Puedes apartar desde una sola porción o las que desees para tu ocasión.`;
            }
            page.querySelector("[data-detail-description]").textContent = desc;
            const reserveBtn = page.querySelector("[data-reserve-link]");
            if (reserveBtn && isPortion) {
                reserveBtn.innerHTML = 'Pedir porción(es) <span aria-hidden="true">→</span>';
            }
            const image = page.querySelector("[data-detail-image]");
            image.src = product.imagen;
            image.alt = product.nombre;
        } catch (error) {
            page.querySelector(".detail-card").hidden = true;
            const missing = page.querySelector("[data-product-missing]");
            missing.hidden = false;
            missing.querySelector("h1").textContent = "No se pudo cargar el producto";
            missing.querySelector("p").textContent = error.message;
        }
    }

    loadProduct();
})();
