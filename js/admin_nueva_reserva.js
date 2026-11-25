(() => {
    const page = document.querySelector("[data-new-reservation-page]");
    if (!page) return;

    const rows = Array.from(page.querySelectorAll(".product-row"));
    const searchInput = page.querySelector("[data-product-search]");
    const categoryBtns = Array.from(page.querySelectorAll(".category-tabs .tab-btn"));
    const hiddenProductId = page.querySelector("#form-producto-id");
    const qtyInput = page.querySelector("[data-qty-input]");
    const bannerTitle = page.querySelector("#form-product-name");
    const bannerPrice = page.querySelector("#form-product-price");
    const bannerImg = page.querySelector("[data-selected-image]");
    const countBadge = page.querySelector("[data-product-count]");
    const summaryTotal = page.querySelector("#summary-total");
    const summaryDeposit = page.querySelector("#summary-deposit");
    const timeSelect = page.querySelector("[data-time-select]");
    const dateInput = page.querySelector("[data-date-input]");
    const phoneInput = page.querySelector("[data-phone-input]");

    // Elementos de modalidad de venta (porciones vs completo)
    const wrapTipoVenta = page.querySelector("#wrap-tipo-venta");
    const radioPorciones = page.querySelector("#radio-tipo-porciones");
    const radioCompleto = page.querySelector("#radio-tipo-completo");
    const cardPorciones = page.querySelector("#card-tipo-porciones");
    const cardCompleto = page.querySelector("#card-tipo-completo");
    const tipoPorcionesDesc = page.querySelector("#tipo-porciones-desc");
    const tipoCompletoDesc = page.querySelector("#tipo-completo-desc");
    const labelCantidad = page.querySelector("#label-input-cantidad");
    const ayudaCantidad = page.querySelector("#cantidad-ayuda-admin");
    const labelFecha = page.querySelector("#label-input-fecha");
    const ayudaFecha = page.querySelector("#fecha-ayuda-admin");

    let selectedPrice = 0;
    let selectedProductId = hiddenProductId ? hiddenProductId.value : "";
    let activeCategory = "";
    let searchQuery = "";
    let currentProductData = null;

    // ── Horario del negocio ──────────────────────────────────────────
    // Lunes: 2:00 PM – 6:00 PM  |  Martes–Sábado: 10:00 AM – 6:00 PM
    // Domingo: cerrado
    function getAvailableHours(dayOfWeek) {
        // dayOfWeek: 0=Domingo, 1=Lunes, 2=Martes … 6=Sábado
        if (dayOfWeek === 0) return [];   // Domingo cerrado
        if (dayOfWeek === 1) {
            // Lunes 2:00 PM – 6:00 PM (en intervalos de 30 min)
            return ["2:00 PM", "2:30 PM", "3:00 PM", "3:30 PM",
                    "4:00 PM", "4:30 PM", "5:00 PM", "5:30 PM", "6:00 PM"];
        }
        // Martes–Sábado 10:00 AM – 6:00 PM
        return [
            "10:00 AM", "10:30 AM", "11:00 AM", "11:30 AM",
            "12:00 PM", "12:30 PM",  "1:00 PM",  "1:30 PM",
             "2:00 PM",  "2:30 PM",  "3:00 PM",  "3:30 PM",
             "4:00 PM",  "4:30 PM",  "5:00 PM",  "5:30 PM",  "6:00 PM"
        ];
    }

    function populateTimeSelect(dateStr) {
        if (!timeSelect) return;
        timeSelect.innerHTML = "";

        if (!dateStr) {
            timeSelect.innerHTML = '<option value="" disabled selected>Selecciona primero una fecha</option>';
            return;
        }

        // Parsear la fecha sin problemas de zona horaria
        const [y, m, d] = dateStr.split("-").map(Number);
        const dow = new Date(y, m - 1, d).getDay(); // 0=Dom … 6=Sáb

        const hours = getAvailableHours(dow);

        if (hours.length === 0) {
            timeSelect.innerHTML = '<option value="" disabled selected>Domingo – local cerrado</option>';
            return;
        }

        // Hora predeterminada: 3:00 PM si está disponible, si no la primera
        const defaultHour = hours.includes("3:00 PM") ? "3:00 PM" : hours[0];

        hours.forEach((h) => {
            const opt = document.createElement("option");
            opt.value = h;
            opt.textContent = h;
            if (h === defaultHour) opt.selected = true;
            timeSelect.appendChild(opt);
        });
    }

    // Inicializar horas con la fecha ya cargada en el input
    if (dateInput) {
        populateTimeSelect(dateInput.value);
        dateInput.addEventListener("change", () => populateTimeSelect(dateInput.value));
    }

    // ── Teléfono: solo dígitos + guión automático al 4to dígito ────────
    if (phoneInput) {
        phoneInput.addEventListener("input", (e) => {
            let raw = e.target.value.replace(/\D/g, ""); // quitar todo lo que no sea dígito
            if (raw.length > 8) raw = raw.slice(0, 8);   // máx 8 dígitos

            if (raw.length > 4) {
                e.target.value = raw.slice(0, 4) + "-" + raw.slice(4);
            } else {
                e.target.value = raw;
            }
        });

        // Evitar pegar caracteres no numéricos
        phoneInput.addEventListener("keydown", (e) => {
            const allowed = ["Backspace", "Delete", "ArrowLeft", "ArrowRight", "Tab", "Home", "End"];
            if (allowed.includes(e.key)) return;
            if (!/^\d$/.test(e.key)) e.preventDefault();
        });
    }

    function fmt(val) {
        return new Intl.NumberFormat("es-US", { style: "currency", currency: "USD" }).format(Number(val));
    }

    function updateSummary() {
        const esPorciones = currentProductData && currentProductData.seVendePorciones && radioPorciones && radioPorciones.checked;
        const maxLimit = esPorciones ? (currentProductData.numPorciones || 30) : 30;
        const qty = Math.max(1, Math.min(maxLimit, Number(qtyInput.value) || 1));
        const total = selectedPrice * qty;
        const deposit = total / 2;
        if (summaryTotal) summaryTotal.textContent = fmt(total);
        if (summaryDeposit) summaryDeposit.textContent = fmt(deposit);
    }

    function aplicarModoVenta() {
        if (!currentProductData) return;

        const { precio, seVendePorciones, numPorciones, precioPorcion, esBebida } = currentProductData;
        const esPorciones = seVendePorciones && radioPorciones && radioPorciones.checked;

        // Estilos de tarjetas de radio
        if (cardPorciones && cardCompleto) {
            if (esPorciones) {
                cardPorciones.style.borderColor = "#f23271";
                cardPorciones.style.background = "#fff5f8";
                cardCompleto.style.borderColor = "#e2e8f0";
                cardCompleto.style.background = "#ffffff";
            } else {
                cardPorciones.style.borderColor = "#e2e8f0";
                cardPorciones.style.background = "#ffffff";
                cardCompleto.style.borderColor = "#f23271";
                cardCompleto.style.background = "#fff5f8";
            }
        }

        const sinAnticipacion = esPorciones || esBebida;
        const fechaHoy = dateInput ? dateInput.dataset.fechaHoy : "";
        const fecha5dias = dateInput ? dateInput.dataset.fecha5dias : "";

        if (esPorciones) {
            selectedPrice = precioPorcion;
            if (bannerPrice) bannerPrice.textContent = `${fmt(precioPorcion)} / porción`;

            if (qtyInput) {
                qtyInput.max = String(Math.max(1, numPorciones));
                if (Number(qtyInput.value) > numPorciones) {
                    qtyInput.value = String(numPorciones);
                }
            }
            if (labelCantidad) labelCantidad.textContent = `Cantidad de porciones (Rinde hasta ${numPorciones})`;
            if (ayudaCantidad) {
                ayudaCantidad.style.display = "block";
                ayudaCantidad.textContent = `Ingresa de 1 a ${numPorciones} porciones.`;
            }
        } else {
            selectedPrice = precio;
            if (bannerPrice) bannerPrice.textContent = `Desde ${fmt(precio)}`;

            if (qtyInput) {
                qtyInput.max = "30";
            }
            if (labelCantidad) labelCantidad.textContent = "Cantidad";
            if (ayudaCantidad) ayudaCantidad.style.display = "none";
        }

        // Configuración de fecha mínima: hoy para porciones o bebidas; 5 días para lo demás
        if (dateInput) {
            if (sinAnticipacion) {
                dateInput.min = fechaHoy;
                if (labelFecha) labelFecha.textContent = "Fecha de retiro (Disponible hoy)";
                if (ayudaFecha) ayudaFecha.textContent = esPorciones
                    ? "Porciones de pastel disponibles para retiro a partir de hoy (sin restricción de 5 días)."
                    : "Bebidas disponibles para retiro a partir de hoy (sin restricción de 5 días).";
                if (!dateInput.value || dateInput.value < fechaHoy) {
                    dateInput.value = fechaHoy;
                }
            } else {
                dateInput.min = fecha5dias;
                if (labelFecha) labelFecha.textContent = "Fecha de retiro (mínimo 5 días)";
                if (ayudaFecha) ayudaFecha.textContent = "Las reservas de pasteles completos requieren al menos 5 días de anticipación.";
                if (!dateInput.value || dateInput.value < fecha5dias) {
                    dateInput.value = fecha5dias;
                }
            }
            populateTimeSelect(dateInput.value);
        }

        updateSummary();
    }

    if (radioPorciones) {
        radioPorciones.addEventListener("change", aplicarModoVenta);
    }
    if (radioCompleto) {
        radioCompleto.addEventListener("change", aplicarModoVenta);
    }

    function selectProduct(row) {
        if (!row) return;

        const id = row.dataset.id;
        const nombre = row.dataset.nombre;
        const precio = Number(row.dataset.precio);
        const imagen = row.dataset.imagen;
        const categoria = (row.dataset.categoria || "").trim();
        const seVendePorciones = row.dataset.seVendePorPorciones === "1";
        const numPorciones = Number(row.dataset.numeroPorciones) || 0;
        const precioPorcion = Number(row.dataset.precioPorcion) || 0;
        const esBebida = categoria.toLowerCase() === "bebidas";

        selectedProductId = id;
        currentProductData = {
            id, nombre, precio, imagen, categoria,
            seVendePorciones, numPorciones, precioPorcion, esBebida
        };
        if (hiddenProductId) hiddenProductId.value = id;

        // Actualizar filas
        rows.forEach((r) => {
            const isTarget = r.dataset.id === id;
            r.classList.toggle("is-selected", isTarget);
            const btn = r.querySelector(".row-select-btn");
            if (btn) btn.textContent = isTarget ? "✓ Seleccionado" : "Seleccionar";
        });

        // Actualizar banner
        if (bannerTitle) bannerTitle.textContent = nombre;
        if (bannerImg) {
            if (imagen) {
                bannerImg.innerHTML = `<img src="${imagen}" alt="${nombre}" id="form-img">`;
            } else {
                bannerImg.innerHTML = `<span class="cake-emoji" aria-hidden="true">🍰</span>`;
            }
        }

        // Configurar selector de tipo de venta si el pastel se vende por porciones
        if (seVendePorciones) {
            if (wrapTipoVenta) wrapTipoVenta.style.display = "block";
            if (tipoPorcionesDesc) tipoPorcionesDesc.textContent = `${fmt(precioPorcion)} c/u (Rinde hasta ${numPorciones})`;
            if (tipoCompletoDesc) tipoCompletoDesc.textContent = `${fmt(precio)} (entero)`;

            // Si es categoría Porciones de Pasteles, seleccionar porciones por defecto
            if (radioPorciones && radioCompleto) {
                if (categoria === "Porciones de Pasteles" || numPorciones > 0) {
                    radioPorciones.checked = true;
                }
            }
        } else {
            if (wrapTipoVenta) wrapTipoVenta.style.display = "none";
            if (radioCompleto) radioCompleto.checked = true;
        }

        // Pulso visual en el banner
        const banner = page.querySelector(".selected-product-banner");
        if (banner && banner.animate) {
            banner.animate([
                { opacity: 0.7, transform: "scale(0.98)" },
                { opacity: 1,   transform: "scale(1)" }
            ], { duration: 220, easing: "ease-out" });
        }

        aplicarModoVenta();
    }

    // Clic en fila o botón
    rows.forEach((row) => {
        row.addEventListener("click", () => selectProduct(row));
    });

    // Actualizar resumen al cambiar cantidad
    if (qtyInput) {
        qtyInput.addEventListener("input", updateSummary);
        qtyInput.addEventListener("change", () => {
            const esPorciones = currentProductData && currentProductData.seVendePorciones && radioPorciones && radioPorciones.checked;
            const maxLimit = esPorciones ? (currentProductData.numPorciones || 30) : 30;
            let val = Number(qtyInput.value) || 1;
            if (val > maxLimit) {
                qtyInput.value = String(maxLimit);
            } else if (val < 1) {
                qtyInput.value = "1";
            }
            updateSummary();
        });
    }

    // Filtro de búsqueda
    function applyFilters() {
        let visible = 0;
        rows.forEach((row) => {
            const nombre = (row.dataset.nombre || "").toLowerCase();
            const cat = (row.dataset.categoria || "").toLowerCase();
            const matchesCat = !activeCategory || cat === activeCategory.toLowerCase();
            const matchesSearch = !searchQuery || nombre.includes(searchQuery) || cat.includes(searchQuery);
            const show = matchesCat && matchesSearch;
            row.hidden = !show;
            if (show) visible++;
        });
        if (countBadge) countBadge.textContent = String(visible);
    }

    if (searchInput) {
        searchInput.addEventListener("input", (e) => {
            searchQuery = e.target.value.trim().toLowerCase();
            applyFilters();
        });
    }

    categoryBtns.forEach((btn) => {
        btn.addEventListener("click", () => {
            categoryBtns.forEach((b) => b.classList.remove("active"));
            btn.classList.add("active");
            activeCategory = btn.dataset.category || "";
            applyFilters();
        });
    });

    // Validación en el submit
    const form = page.querySelector("[data-reservation-form]");
    if (form) {
        form.addEventListener("submit", (e) => {
            if (!hiddenProductId.value) {
                e.preventDefault();
                alert("Por favor selecciona un producto antes de confirmar la reserva.");
                const firstVisible = rows.find((r) => !r.hidden);
                if (firstVisible) selectProduct(firstVisible);
                return;
            }

            // Validar límite de porciones si corresponde
            if (currentProductData && currentProductData.seVendePorciones && radioPorciones && radioPorciones.checked) {
                const maxP = currentProductData.numPorciones;
                const requested = Number(qtyInput.value) || 1;
                if (requested > maxP) {
                    e.preventDefault();
                    alert(`Este pastel solo rinde hasta ${maxP} porciones. Por favor ingresa una cantidad entre 1 y ${maxP}.`);
                    qtyInput.focus();
                    return;
                }
            }

            // Validar fecha mínima según modalidad
            if (dateInput && dateInput.value) {
                const chosen = new Date(dateInput.value + "T00:00:00");
                const minStr = dateInput.min;
                if (minStr) {
                    const minDate = new Date(minStr + "T00:00:00");
                    if (chosen < minDate) {
                        e.preventDefault();
                        alert(`La fecha de retiro no puede ser anterior al ${minStr}.`);
                        dateInput.focus();
                        return;
                    }
                }
            }

            // Validar hora disponible (el select no tendrá valor si es domingo)
            if (timeSelect && !timeSelect.value) {
                e.preventDefault();
                alert("El local está cerrado el día seleccionado. Por favor elige otra fecha.");
                dateInput && dateInput.focus();
                return;
            }

            // Validar correo electrónico
            const emailInput = form.querySelector("[data-email-input]");
            const emailVal = emailInput ? emailInput.value.trim() : "";
            if (emailVal) {
                // Regex que exige: texto@dominio.extension (extension mín 2 caracteres)
                const emailRegex = /^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$/;
                if (!emailRegex.test(emailVal)) {
                    e.preventDefault();
                    alert("El correo electrónico no es válido. Usa un formato como nombre@gmail.com o nombre@hotmail.com");
                    emailInput.focus();
                    return;
                }
            }

            // Validar teléfono: debe tener el formato 0000-0000
            if (phoneInput) {
                const phoneVal = phoneInput.value.trim();
                if (!/^\d{4}-\d{4}$/.test(phoneVal)) {
                    e.preventDefault();
                    alert("El teléfono debe tener el formato 0000-0000 (8 dígitos).");
                    phoneInput.focus();
                    return;
                }
            }
        });
    }

    // Preseleccionar el primer producto visible por defecto
    const initialRow = rows.find((r) => r.dataset.id === selectedProductId) || rows[0];
    if (initialRow) {
        selectProduct(initialRow);
    }
})();
