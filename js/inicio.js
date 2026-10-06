(() => {
    const contenedor = document.querySelector("[data-featured-products]");
    if (!contenedor) return;

    async function render() {
        contenedor.setAttribute("aria-busy", "true");
        try {
            const destacados = (await window.ProductStore.getAll({ vitrina: true })).slice(0, 3);
            contenedor.innerHTML = destacados.length
                ? destacados.map(window.ProductStore.renderCard).join("")
                : '<p class="empty-products">Pronto anunciaremos los postres fijos de nuestra vitrina.</p>';
        } catch (error) {
            contenedor.innerHTML = `<p class="empty-products">No se pudieron cargar los productos: ${window.ProductStore.escapeHtml(error.message)}</p>`;
        } finally {
            contenedor.removeAttribute("aria-busy");
        }
    }

    render();
})();
