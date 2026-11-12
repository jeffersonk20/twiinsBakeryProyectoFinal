(() => {
    // 1. Carrusel automático de imágenes del Home (cada 2500ms, sin controles manuales)
    async function initHeroCarousel() {
        const track = document.getElementById("carouselTrack");
        if (!track) return;

        try {
            const resp = await fetch("/api/home/carrusel");
            if (resp.ok) {
                const data = await resp.json();
                if (data.imagenes && data.imagenes.length > 0) {
                    track.innerHTML = "";
                    const maxImgs = data.imagenes.slice(0, 5);
                    maxImgs.forEach((item, idx) => {
                        const slide = document.createElement("div");
                        slide.className = `carousel-slide ${idx === 0 ? "active" : ""}`;
                        slide.style.backgroundImage = `linear-gradient(0deg, rgba(36, 16, 22, .46), transparent 60%), url('${item.url}')`;
                        track.appendChild(slide);
                    });
                }
            }
        } catch (e) {
            // Se mantiene el slide estático de respaldo existente en el DOM
        }

        const slides = track.querySelectorAll(".carousel-slide");
        if (slides.length <= 1) return;

        let currentIndex = 0;
        setInterval(() => {
            slides[currentIndex].classList.remove("active");
            currentIndex = (currentIndex + 1) % slides.length;
            slides[currentIndex].classList.add("active");
        }, 2500); // Exactamente 2500ms de transición
    }

    initHeroCarousel();

    // 2. Productos destacados de Vitrina
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
