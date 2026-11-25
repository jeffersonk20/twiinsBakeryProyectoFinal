(() => {
    const page = document.querySelector("[data-reservation-app]");
    if (!page) return;

    const quantity = page.querySelector("[data-quantity]");
    const deposit = page.querySelector("[data-deposit-amount]");
    const wompiBox = page.querySelector("#wompiAmountBox");
    const wompiAnticipoPriceEl = page.querySelector("[data-wompi-anticipo-price]");
    const wompiTotalPriceEl = page.querySelector("[data-wompi-total-price]");
    const wompiChargeTypes = page.querySelectorAll('input[name="tipo_cobro_tarjeta"]');
    const date = page.querySelector("[data-date]");
    const timeSelect = page.querySelector("[data-time]");
    const phoneInput = page.querySelector("#telefono");
    const submitButton = page.querySelector("[data-payment-submit]");
    const paymentMethods = page.querySelectorAll('input[name="metodo_pago"]');
    let productPrice = 0;

    const isSinAnticipacion = date && date.dataset.sinAnticipacion === "1";
    let minimumDate = "";
    if (isSinAnticipacion) {
        const hoy = new Date();
        minimumDate = new Date(hoy.getTime() - hoy.getTimezoneOffset() * 60_000)
            .toISOString()
            .slice(0, 10);
    } else {
        const fechaLimite = new Date();
        fechaLimite.setDate(fechaLimite.getDate() + 5);
        minimumDate = new Date(fechaLimite.getTime() - fechaLimite.getTimezoneOffset() * 60_000)
            .toISOString()
            .slice(0, 10);
    }
    if (date) {
        date.min = minimumDate;
        if (!date.value || date.value < minimumDate) {
            date.value = minimumDate;
        }
    }

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
                isSinAnticipacion
                    ? "La fecha no puede ser anterior a hoy"
                    : "La fecha debe ser con al menos 5 días de anticipación",
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

    function getSelectedWompiChargeType() {
        const checked = page.querySelector('input[name="tipo_cobro_tarjeta"]:checked');
        return checked ? checked.value : "ANTICIPO_50";
    }

    function getMaxQuantity() {
        return Math.max(1, Number(quantity.max) || 30);
    }

    function validateQuantity() {
        const maxLimit = getMaxQuantity();
        const val = Number(quantity.value);
        if (val > maxLimit) {
            quantity.setCustomValidity(`Este pastel solo rinde hasta ${maxLimit} porciones. Ingresa una cantidad entre 1 y ${maxLimit}.`);
            quantity.reportValidity();
            return false;
        } else if (val < 1) {
            quantity.setCustomValidity("Debes ingresar al menos 1.");
            quantity.reportValidity();
            return false;
        } else {
            quantity.setCustomValidity("");
            return true;
        }
    }

    function updateSubmitButtonText() {
        const selectedMethod = page.querySelector('input[name="metodo_pago"]:checked');
        if (!selectedMethod || selectedMethod.value !== "WOMPI") {
            submitButton.firstChild.textContent = "Confirmar reserva ";
            return;
        }

        const maxLimit = getMaxQuantity();
        const selectedQuantity = Math.max(1, Math.min(maxLimit, Number(quantity.value) || 1));
        const total = Math.round(productPrice * selectedQuantity * 100) / 100;
        const anticipo = Math.round(productPrice * selectedQuantity * 50) / 100;
        const chargeType = getSelectedWompiChargeType();

        if (chargeType === "TOTAL_100") {
            submitButton.firstChild.textContent = `Pagar total (${window.ProductStore.formatPrice(total)}) en Wompi `;
        } else {
            submitButton.firstChild.textContent = `Pagar anticipo (${window.ProductStore.formatPrice(anticipo)}) en Wompi `;
        }
    }

    function updateDeposit() {
        if (productPrice <= 0) return;
        const maxLimit = getMaxQuantity();
        const selectedQuantity = Math.max(1, Math.min(maxLimit, Number(quantity.value) || 1));
        const anticipo = Math.round(productPrice * selectedQuantity * 50) / 100;
        const total = Math.round(productPrice * selectedQuantity * 100) / 100;

        deposit.textContent = window.ProductStore.formatPrice(anticipo);
        if (wompiAnticipoPriceEl) {
            wompiAnticipoPriceEl.textContent = window.ProductStore.formatPrice(anticipo);
        }
        if (wompiTotalPriceEl) {
            wompiTotalPriceEl.textContent = window.ProductStore.formatPrice(total);
        }
        updateSubmitButtonText();
    }

    quantity.addEventListener("input", () => {
        validateQuantity();
        updateDeposit();
    });
    quantity.addEventListener("change", () => {
        const maxLimit = getMaxQuantity();
        let val = Number(quantity.value);
        if (val > maxLimit) {
            quantity.value = maxLimit;
        } else if (val < 1) {
            quantity.value = 1;
        }
        validateQuantity();
        updateDeposit();
    });
    date.addEventListener("input", updateAvailableTimes);
    date.addEventListener("change", updateAvailableTimes);
    phoneInput.addEventListener("input", formatPhone);
    updateAvailableTimes();

    const consentWrap = document.getElementById("consentWrap") || page.querySelector(".consent-checkbox-wrap");
    const consentCheck = document.getElementById("acepto_terminos_reserva");

    paymentMethods.forEach((method) => {
        method.addEventListener("change", () => {
            const isWompi = method.value === "WOMPI";
            if (wompiBox) {
                wompiBox.style.display = isWompi ? "block" : "none";
            }
            if (consentWrap) {
                consentWrap.style.display = isWompi ? "none" : "flex";
            }
            if (consentCheck) {
                consentCheck.required = !isWompi;
                if (isWompi) {
                    consentCheck.setCustomValidity("");
                }
            }
            updateSubmitButtonText();
        });
    });

    wompiChargeTypes.forEach((radio) => {
        radio.addEventListener("change", updateSubmitButtonText);
    });

    const reservationForm = page.querySelector("form");
    const reservaOverlay = document.getElementById("solicitudOverlay");
    let isSubmittingReserva = false;

    reservationForm.addEventListener("submit", (event) => {
        if (!validateQuantity()) {
            event.preventDefault();
            return;
        }

        if (!date.value || !timeSelect.value) {
            event.preventDefault();
            if (!date.value) date.reportValidity();
            else timeSelect.reportValidity();
            return;
        }
        if (date.value < minimumDate) {
            date.setCustomValidity(
                isSinAnticipacion
                    ? "La fecha de retiro no puede ser anterior a hoy."
                    : "El pedido debe reservarse con al menos 5 días de anticipación."
            );
            date.reportValidity();
            event.preventDefault();
            return;
        } else {
            date.setCustomValidity("");
        }

        const selectedMethod = page.querySelector('input[name="metodo_pago"]:checked');
        const isWompi = selectedMethod && selectedMethod.value === "WOMPI";


        // Para pago con Wompi
        if (isWompi) {
            if (isSubmittingReserva) {
                event.preventDefault();
                return;
            }
            isSubmittingReserva = true;
            if (submitButton) {
                submitButton.disabled = true;
                submitButton.style.opacity = "0.7";
                submitButton.textContent = "Conectando con Wompi...";
            }
            if (reservaOverlay) {
                reservaOverlay.classList.add("visible");
            }
            return;
        }

        // ── PAGO EN EFECTIVO (Presencial en tienda) ──
        if (consentCheck && !consentCheck.checked) {
            consentCheck.reportValidity();
            event.preventDefault();
            return;
        }

        if (isSubmittingReserva) return;

        event.preventDefault();
        isSubmittingReserva = true;

        if (submitButton) {
            submitButton.disabled = true;
        }
        if (reservaOverlay) {
            reservaOverlay.classList.add("visible");
        }

        setTimeout(() => {
            reservationForm.submit();
        }, 2200);
    });

    window.ProductStore.getAll()
        .then((products) => products.find((item) => String(item.id) === page.dataset.productId))
        .then((product) => {
            if (!product) throw new Error("Este producto ya no está disponible para reservar.");
            const isPortion = Boolean(product.se_vende_por_porciones || product.categoria === "Porciones de Pasteles");
            productPrice = (isPortion && product.precio_porcion) ? Number(product.precio_porcion) : Number(product.precio);
            const maxPortions = (isPortion && product.numero_porciones) ? Number(product.numero_porciones) : 30;
            quantity.max = String(maxPortions);
            quantity.setAttribute("max", String(maxPortions));

            page.querySelector("[data-reservation-name]").textContent = product.nombre;
            page.querySelector("[data-reservation-category]").textContent = isPortion ? "Porciones de Pasteles" : (product.categoria || "Pastelería artesanal");
            let desc = product.descripcion;
            if (isPortion && product.numero_porciones) {
                desc += `\n\n🍰 Venta por porciones: Este pastel rinde hasta ${product.numero_porciones} porciones. Puedes apartar desde 1 hasta ${product.numero_porciones} porciones.`;
            }
            page.querySelector("[data-reservation-description]").textContent = desc;
            const priceEl = page.querySelector("[data-reservation-price]");
            if (isPortion && product.precio_porcion) {
                priceEl.innerHTML = `${window.ProductStore.formatPrice(product.precio_porcion)} <small style="font-size:12px;font-weight:normal;color:#64748b;">/ porción individual</small>`;
            } else {
                priceEl.textContent = window.ProductStore.formatPrice(product.precio);
            }
            const quantityLabel = page.querySelector('label[for="cantidad"]');
            if (quantityLabel && isPortion && product.numero_porciones) {
                quantityLabel.innerHTML = `Cantidad de porciones <small style="color:#059669;font-weight:600;">(Rinde máx. ${maxPortions} porciones)</small>`;
            }
            let ayudaPorciones = document.getElementById("cantidad-ayuda-porciones");
            if (isPortion && product.numero_porciones) {
                if (!ayudaPorciones) {
                    ayudaPorciones = document.createElement("small");
                    ayudaPorciones.id = "cantidad-ayuda-porciones";
                    ayudaPorciones.style.cssText = "color:#64748b; font-size:11.5px; display:block; margin-top:4px;";
                    quantity.parentNode.appendChild(ayudaPorciones);
                }
                ayudaPorciones.textContent = `Este pastel rinde hasta ${maxPortions} porciones. Puedes elegir entre 1 y ${maxPortions} porciones.`;
            }
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
