(() => {
    const shell = document.querySelector("[data-dashboard]");
    if (!shell) return;

    /* ─── helpers ──────────────────────────────────────────── */
    function fmt(n) { return Number(n).toLocaleString("es"); }

    const pad = (n) => String(n).padStart(2, "0");
    const formatDateLocal = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

    function setCard(selector, value, colorClass) {
        const el = shell.querySelector(selector);
        if (!el) return;
        el.textContent = fmt(value);
        if (colorClass) el.className = `stat-value ${colorClass}`;
    }

    /* ─── gráfica de barras ─────────────────────────────────── */
    function renderChart(semana) {
        const area = shell.querySelector("[data-chart-area]");
        if (!area) return;
        area.innerHTML = "";

        // Generar los últimos 7 días con fecha local exacta
        const hoy = new Date();
        const dias = [];
        for (let i = 6; i >= 0; i--) {
            const d = new Date(hoy);
            d.setDate(hoy.getDate() - i);
            dias.push(formatDateLocal(d));
        }

        const dataMap = {};
        semana.forEach(r => { dataMap[r.dia] = r.total; });

        const maxVal = Math.max(...dias.map(d => dataMap[d] || 0), 1);
        const nombres = ["Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"];

        dias.forEach((dia) => {
            const total = dataMap[dia] || 0;
            const heightPct = Math.max((total / maxVal) * 100, 4);
            const fechaParts = dia.split("-");
            const fechaObj = new Date(Number(fechaParts[0]), Number(fechaParts[1]) - 1, Number(fechaParts[2]));
            const nombreDia = nombres[fechaObj.getDay()];

            const col = document.createElement("div");
            col.className = "bar-col";
            col.title = `${dia}: ${total} reserva(s)`;

            if (total > 0) {
                const badge = document.createElement("span");
                badge.className = "bar-count-badge";
                badge.textContent = total;
                col.appendChild(badge);
            }

            const bar = document.createElement("div");
            bar.className = "bar";
            bar.style.height = "0";
            col.appendChild(bar);

            const label = document.createElement("span");
            label.className = "bar-label";
            label.textContent = nombreDia;
            col.appendChild(label);

            area.appendChild(col);

            // animación
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    bar.style.height = `${heightPct}%`;
                });
            });
        });
    }

    /* ─── carga de datos ────────────────────────────────────── */
    async function loadDashboard() {
        const loading = shell.querySelector("[data-loading]");
        if (loading) loading.hidden = false;

        try {
            const resp = await fetch("/api/admin/dashboard");
            if (!resp.ok) throw new Error("Error al cargar datos");
            const data = await resp.json();

            setCard("[data-stat-total]", data.total_reservas, "dark");
            setCard("[data-stat-hoy]", data.reservas_hoy, "pink");
            setCard("[data-stat-confirmadas]", data.confirmadas, "green");
            setCard("[data-stat-pendientes]", data.pendientes, "orange");
            setCard("[data-stat-listas]", data.listas, "blue");
            setCard("[data-stat-productos]", data.productos_activos, "teal");

            renderChart(data.reservas_semana || []);
        } catch (err) {
            console.error(err);
            const area = shell.querySelector("[data-chart-area]");
            if (area) area.innerHTML = `<p style="color:#a12a45;font-size:12px;padding:20px">No se pudieron cargar las métricas.</p>`;
        } finally {
            if (loading) loading.hidden = true;
        }
    }

    loadDashboard();
})();
