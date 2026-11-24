(() => {
    const grid = document.querySelector("[data-product-grid]");
    const filters = document.querySelector("[data-category-filters]");
    const searchInput = document.getElementById("catalogSearchInput");
    const searchClearBtn = document.getElementById("catalogSearchClear");
    if (!grid || !filters) return;

    let selectedCategory = "Todos";
    let searchQuery = "";
    let products = [];

    // Normaliza texto eliminando acentos/tildes y convirtiendo a minúsculas
    function normalizar(texto) {
        return String(texto || "")
            .normalize("NFD")
            .replace(/[\u0300-\u036f]/g, "")
            .toLowerCase()
            .trim();
    }

    // Detectar filtro inicial desde query params (ej. ?categoria=Postres+completos)
    const urlParams = new URLSearchParams(window.location.search);
    const paramCategory = urlParams.get("categoria");
    if (paramCategory) {
        selectedCategory = paramCategory;
        const targetBtn = filters.querySelector(`[data-category="${paramCategory}"]`);
        if (targetBtn) {
            filters.querySelectorAll("[data-category]").forEach((filter) => {
                const selected = filter === targetBtn;
                filter.classList.toggle("active", selected);
                filter.setAttribute("aria-pressed", String(selected));
            });
        }
    }

    function render() {
        const queryNorm = normalizar(searchQuery);
        const palabras = queryNorm.split(/\s+/).filter(Boolean);

        const filteredProducts = products.filter((producto) => {
            // Verificar existencia y disponibilidad
            const enExistencia = Boolean(
                producto.disponible &&
                (producto.stock === undefined || producto.stock > 0)
            );
            if (!enExistencia) return false;

            // Búsqueda interactiva en todo el catálogo (cualquier apartado)
            if (palabras.length > 0) {
                const textoCompleto = normalizar(
                    `${producto.nombre} ${producto.descripcion || ""} ${producto.categoria || ""}`
                );
                // Todas las palabras tecleadas deben coincidir en el producto
                return palabras.every((palabra) => textoCompleto.includes(palabra));
            }

            // Si no hay búsqueda de texto, filtrar según la categoría seleccionada
            if (selectedCategory === "Todos") return true;
            if (selectedCategory === "Porciones de Pasteles") {
                return producto.categoria === "Porciones de Pasteles" || producto.categoria === "Pasteles" || Boolean(producto.se_vende_por_porciones);
            }
            return producto.categoria === selectedCategory;
        });

        if (filteredProducts.length > 0) {
            grid.innerHTML = filteredProducts.map(window.ProductStore.renderCard).join("");
        } else {
            if (queryNorm) {
                grid.innerHTML = `
                    <div class="empty-products" style="text-align: center; padding: 45px 20px;">
                        <span style="font-size: 32px; display: block; margin-bottom: 8px;" aria-hidden="true">🔍</span>
                        <p style="margin: 0 0 6px; font-weight: 600; color: var(--ink);">
                            No encontramos ningún producto disponible que coincida con "${window.ProductStore.escapeHtml(searchQuery)}".
                        </p>
                        <p style="margin: 0 0 16px; font-size: 12px; color: var(--muted);">
                            Verifica la ortografía o intenta buscar con otro ingrediente o categoría.
                        </p>
                        <button type="button" class="filter" id="btnRestablecerBusqueda" style="display: inline-block; cursor: pointer;">
                            Ver todos los productos
                        </button>
                    </div>
                `;
                const resetBtn = document.getElementById("btnRestablecerBusqueda");
                if (resetBtn) {
                    resetBtn.addEventListener("click", () => {
                        if (searchInput) searchInput.value = "";
                        searchQuery = "";
                        if (searchClearBtn) searchClearBtn.style.display = "none";
                        render();
                    });
                }
            } else {
                grid.innerHTML = '<p class="empty-products">Todavía no hay productos disponibles en esta categoría.</p>';
            }
        }
    }

    // Filtrado por botones de categoría
    filters.addEventListener("click", (event) => {
        const button = event.target.closest("[data-category]");
        if (!button) return;

        selectedCategory = button.dataset.category;

        // Si se hace clic en una categoría, limpiar la búsqueda para mostrar los productos de esa categoría
        if (searchQuery) {
            searchQuery = "";
            if (searchInput) searchInput.value = "";
            if (searchClearBtn) searchClearBtn.style.display = "none";
        }

        filters.querySelectorAll("[data-category]").forEach((filter) => {
            const selected = filter === button;
            filter.classList.toggle("active", selected);
            filter.setAttribute("aria-pressed", String(selected));
        });

        render();
    });

    // Eventos para la búsqueda interactiva
    if (searchInput) {
        searchInput.addEventListener("input", (e) => {
            searchQuery = e.target.value;
            if (searchClearBtn) {
                searchClearBtn.style.display = searchQuery.trim() ? "inline-flex" : "none";
            }

            // Al escribir en la búsqueda, desmarcar categorías individuales y activar "Todos"
            if (searchQuery.trim()) {
                filters.querySelectorAll("[data-category]").forEach((btn) => {
                    const esTodos = btn.dataset.category === "Todos";
                    btn.classList.toggle("active", esTodos);
                    btn.setAttribute("aria-pressed", String(esTodos));
                });
                selectedCategory = "Todos";
            }

            render();
        });

        if (searchClearBtn) {
            searchClearBtn.addEventListener("click", () => {
                searchInput.value = "";
                searchQuery = "";
                searchClearBtn.style.display = "none";
                searchInput.focus();
                render();
            });
        }
    }

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
