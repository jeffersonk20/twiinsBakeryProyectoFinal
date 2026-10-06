(() => {
    const grid = document.querySelector("[data-product-grid]");
    if (!grid) return;

    async function loadVitrina() {
        grid.setAttribute("aria-busy", "true");
        try {
            const products = await window.ProductStore.getAll({ vitrina: true });
            grid.innerHTML = products.length
                ? products.map(window.ProductStore.renderCard).join("")
                : '<p class="empty-products">Todavía no hay postres en la vitrina.</p>';
        } catch (error) {
            grid.innerHTML = `<p class="empty-products">No se pudo cargar la vitrina: ${window.ProductStore.escapeHtml(error.message)}</p>`;
        } finally {
            grid.removeAttribute("aria-busy");
        }
    }

    loadVitrina();
})();
