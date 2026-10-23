(() => {
    const page = document.querySelector("[data-reservation-app]");
    if (!page) return;

    const quantity = page.querySelector("[data-quantity]");
    const deposit = page.querySelector("[data-deposit-amount]");
    const date = page.querySelector("[data-date]");
    const timeSelect = page.querySelector("[data-time]");
    const phoneInput = page.querySelector("#telefono");
    const submitButton = page.querySelector("[data-payment-submit]");
    const paymentMethods = page.querySelectorAll('input[name="metodo_pago"]');
    let productPrice = 0;

    const fechaLimite = new Date();
    fechaLimite.setDate(fechaLimite.getDate() + 5);
    const minimumDate = new Date(fechaLimite.getTime() - fechaLimite.getTimezoneOffset() * 60_000)
        .toISOString()
        .slice(0, 10);
    date.min = minimumDate;

    function updateAvailableTimes() {
        const selectedDate = date.value
            ? new Date(`${date.value}T12:00:00`)
            : null;
        const day = selectedDate && !Number.isNaN(selectedDate.getTime())
            ? selectedDate.getDay()
            : undefined;
        timeSelect.replaceChildren(new Option(
            day === 0 ? "TWINS Bakery está cerrado los domingos" : "Selecciona una hora",
            "",
        ));
        timeSelect.disabled = day === undefined || day === 0;

        if (day === 0) {
            date.setCustomValidity("TWINS Bakery está cerrado los domingos. Selecciona otro día.");
            return;
        }
        date.setCustomValidity("");
        if (day === undefined) return;

        if (date.value < minimumDate) {
            timeSelect.replaceChildren(new Option(
                "La fecha debe ser con al menos 5 días de anticipación",
                "",
            ));
            timeSelect.disabled = true;
            return;
        }

        const openingHour = day === 1 ? 14 : 10;
        for (let hour = openingHour; hour < 18; hour += 1) {
            const hour12 = hour % 12 || 12;
            const period = hour < 12 ? "a. m." : "p. m.";
            const value = `${String(hour).padStart(2, "0")}:00`;
            timeSelect.add(new Option(`${hour12}:00 ${period}`, value));
        }
        timeSelect.disabled = false;
    }

    function formatPhone() {
        const digits = phoneInput.value.replace(/\D/g, "").slice(0, 8);
        phoneInput.value = digits.length >= 4
            ? `${digits.slice(0, 4)}-${digits.slice(4)}`
            : digits;
    }

    function updateDeposit() {
        if (productPrice <= 0) return;
        const selectedQuantity = Math.max(1, Math.min(30, Number(quantity.value) || 1));
        const amount = Math.round(productPrice * selectedQuantity * 50) / 100;
        deposit.textContent = window.ProductStore.formatPrice(amount);
    }

    quantity.addEventListener("input", updateDeposit);
    date.addEventListener("input", updateAvailableTimes);
    date.addEventListener("change", updateAvailableTimes);
    phoneInput.addEventListener("input", formatPhone);
    updateAvailableTimes();
    paymentMethods.forEach((method) => {
        method.addEventListener("change", () => {
            submitButton.firstChild.textContent = method.value === "WOMPI"
                ? "Continuar a Wompi "
                : "Confirmar reserva ";
        });
    });

    page.querySelector("form").addEventListener("submit", (event) => {
        if (!date.value || !timeSelect.value) {
            event.preventDefault();
            if (!date.value) date.reportValidity();
            else timeSelect.reportValidity();
            return;
        }
        if (date.value < minimumDate) {
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
