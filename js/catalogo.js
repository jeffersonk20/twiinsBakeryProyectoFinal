(() => {
    const grid = document.querySelector("[data-product-grid]");
    const filters = document.querySelector("[data-category-filters]");
    if (!grid || !filters) return;

    let selectedCategory = "Todos";
    let products = [];

    function render() {
        const filteredProducts = products.filter((producto) => (
            selectedCategory === "Todos" || producto.categoria === selectedCategory
        ));
        grid.innerHTML = filteredProducts.length
            ? filteredProducts.map(window.ProductStore.renderCard).join("")
            : '<p class="empty-products">Todavía no hay productos disponibles en esta categoría.</p>';
    }

    filters.addEventListener("click", (event) => {
        const button = event.target.closest("[data-category]");
        if (!button) return;
        selectedCategory = button.dataset.category;
        filters.querySelectorAll("[data-category]").forEach((filter) => {
            const selected = filter === button;
            filter.classList.toggle("active", selected);
            filter.setAttribute("aria-pressed", String(selected));
        });
        render();
    });

    async function loadProducts() {
        grid.setAttribute("aria-busy", "true");
        try {
            products = await window.ProductStore.getAll();
            render();
        } catch (error) {
            grid.innerHTML = `<p class="empty-products">No se pudieron cargar los productos: ${window.ProductStore.escapeHtml(error.message)}</p>`;
        } finally {
            grid.removeAttribute("aria-busy");
        }
    }

    loadProducts();
})();
