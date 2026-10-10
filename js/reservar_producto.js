(() => {
    const page = document.querySelector("[data-reservation-app]");
    if (!page) return;

    const quantity = page.querySelector("[data-quantity]");
    const deposit = page.querySelector("[data-deposit-amount]");
    const date = page.querySelector("[data-date]");
    const hourInput = page.querySelector("#hora-12");
    const minuteInput = page.querySelector("#minutos");
    const periodInput = page.querySelector("#periodo");
    const formattedTime = page.querySelector("#hora");
    const submitButton = page.querySelector("[data-payment-submit]");
    const paymentMethods = page.querySelectorAll('input[name="metodo_pago"]');
    let productPrice = 0;

    const fechaLimite = new Date();
    fechaLimite.setDate(fechaLimite.getDate() + 5);
    const minimumDate = new Date(fechaLimite.getTime() - fechaLimite.getTimezoneOffset() * 60_000)
        .toISOString()
        .slice(0, 10);
    date.min = minimumDate;

    function updateDeposit() {
        if (productPrice <= 0) return;
        const selectedQuantity = Math.max(1, Math.min(30, Number(quantity.value) || 1));
        const amount = Math.round(productPrice * selectedQuantity * 50) / 100;
        deposit.textContent = window.ProductStore.formatPrice(amount);
    }

    quantity.addEventListener("input", updateDeposit);
    date.addEventListener("change", () => date.setCustomValidity(""));
    paymentMethods.forEach((method) => {
        method.addEventListener("change", () => {
            submitButton.firstChild.textContent = method.value === "WOMPI"
                ? "Continuar a Wompi "
                : "Confirmar reserva ";
        });
    });

    page.querySelector("form").addEventListener("submit", (event) => {
        const hour = Number(hourInput.value);
        const minute = Number(minuteInput.value);
        if (!hourInput.value || hour < 1 || hour > 12 || !minuteInput.value || minute < 0 || minute > 59) {
            event.preventDefault();
            (hour < 1 || hour > 12 ? hourInput : minuteInput).reportValidity();
            return;
        }
        const hour24 = (hour % 12) + (periodInput.value === "PM" ? 12 : 0);
        formattedTime.value = `${String(hour24).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
        const requestedDate = new Date(`${date.value}T${formattedTime.value}:00`);
        const minimumPickup = new Date(Date.now() + 5 * 24 * 60 * 60 * 1000);
        if (!date.value || requestedDate < minimumPickup) {
            date.setCustomValidity("El pedido debe reservarse con al menos 5 días de anticipación.");
            date.reportValidity();
            event.preventDefault();
        } else {
            date.setCustomValidity("");
        }
    });

    window.ProductStore.getAll()
        .then((products) => products.find((item) => String(item.id) === page.dataset.productId))
        .then((product) => {
            if (!product) throw new Error("Este producto ya no está disponible para reservar.");
            productPrice = Number(product.precio);
            page.querySelector("[data-reservation-name]").textContent = product.nombre;
            page.querySelector("[data-reservation-category]").textContent = product.categoria || "Pastelería artesanal";
            page.querySelector("[data-reservation-description]").textContent = product.descripcion;
            page.querySelector("[data-reservation-price]").textContent = window.ProductStore.formatPrice(product.precio);
            const imageContainer = page.querySelector("[data-reservation-image]");
            if (product.imagen) {
                const image = document.createElement("img");
                image.src = product.imagen;
                image.alt = product.nombre;
                imageContainer.replaceChildren(image);
            }
            updateDeposit();
        })
        .catch((error) => {
            page.querySelector("[data-reservation-name]").textContent = "No se pudo cargar el producto";
            page.querySelector("[data-reservation-description]").textContent = error.message;
            page.querySelector("form").querySelectorAll("input, button").forEach((element) => {
                element.disabled = true;
            });
        });
})();
