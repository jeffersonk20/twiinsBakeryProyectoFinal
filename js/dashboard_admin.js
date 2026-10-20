(() => {
    const shell = document.querySelector("[data-dashboard]");
    if (!shell) return;

    /* ─── helpers ──────────────────────────────────────────── */
    function fmt(n) { return Number(n).toLocaleString("es"); }

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

        // Generar los últimos 7 días
        const hoy = new Date();
        const dias = [];
        for (let i = 6; i >= 0; i--) {
            const d = new Date(hoy);
            d.setDate(hoy.getDate() - i);
            dias.push(d.toISOString().slice(0, 10));
        }

        const dataMap = {};
        semana.forEach(r => { dataMap[r.dia] = r.total; });

        const maxVal = Math.max(...dias.map(d => dataMap[d] || 0), 1);
        const nombres = ["Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"];

        dias.forEach((dia, idx) => {
            const total = dataMap[dia] || 0;
            const heightPct = Math.max((total / maxVal) * 100, 3);
            const fechaObj = new Date(dia + "T12:00:00");
            const nombreDia = nombres[fechaObj.getDay()];

            const col = document.createElement("div");
            col.className = "bar-col";
            col.title = `${dia}: ${total} reserva(s)`;

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

            setCard("[data-stat-hoy]", data.reservas_hoy, "pink");
            setCard("[data-stat-pendientes]", data.pendientes, "orange");
            setCard("[data-stat-productos]", data.productos_activos, "teal");
            setCard("[data-stat-listas]", data.listas, "blue");

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
