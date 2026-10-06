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

            document.title = `${product.nombre} | TWINS Bakery`;
            page.querySelector("[data-detail-name]").textContent = product.nombre;
            page.querySelectorAll("[data-detail-category]").forEach((element) => {
                element.textContent = product.categoria;
            });
            page.querySelector("[data-detail-price]").textContent = window.ProductStore.formatPrice(product.precio);
            page.querySelector("[data-detail-description]").textContent = product.descripcion;
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
