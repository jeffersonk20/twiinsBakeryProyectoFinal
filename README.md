# 🎂 TWIINS Bakery — Proyecto Final

Sistema web integral de comercio electrónico y gestión empresarial para la pastelería artesanal **TWIINS Bakery**, desarrollado con **Python (Flask)** en el backend, arquitectura de datos relacional (SQLite / MySQL), asistente conversacional inteligente con ciberseguridad avanzada y panel administrativo con control financiero.



##  Guía Específica para el Docente / Evaluador

Este proyecto está configurado para ejecutarse de forma **inmediata tras su clonación**. La base de datos SQLite local (`twins_bakery.db`) se entrega **limpia y lista para pruebas**:
* **Catálogo cargado:** 6 productos artesanales con fotografías, categorías y stock activo en vitrina.
* **0 Clientes y 0 Reservas previas:** Permite evaluar el flujo completo de registro de usuario y ciclo de compra desde cero.
* **1 Administrador oficial:** Listo para acceder al panel de control.


###  Instalación para las pruebas paso a paso:

#### 1. Clonar el repositorio
```bash
git clone <URL_DEL_REPOSITORIO>
cd twiinsBakeryProyectoFinal
```

#### 2. Configurar el archivo `.env`
Pega el archivo `.env` proporcionado directamente en la carpeta raíz del proyecto (al mismo nivel que `app.py`).


#### 3. Crear y activar el entorno virtual (Recomendado)

* **En Windows (PowerShell):**
  ```powershell
  python -m venv venv
  .\venv\Scripts\Activate.ps1
  ```
* **En Windows (CMD / Símbolo del Sistema):**
  ```cmd
  python -m venv venv
  venv\Scripts\activate.bat
  ```
* **En Linux / macOS:**
  ```bash
  python3 -m venv venv
  source venv/bin/activate
  ```

#### 4. Instalar dependencias
Requiere **Python 3.10 o superior**:
```bash
pip install -r requirements.txt
```

#### 5. Iniciar la aplicación
```bash
python app.py
```

## funciones

### 1. Experiencia del Cliente (Tienda Web)
1. **Vitrina y Catálogo (`/vitrina`):** Explora los postres y pasteles disponibles, prueba el buscador instantáneo y filtra por categorías (*Pasteles*, *Galletas*, *Bebidas*).
2. **Registro de Cliente (`/registro`):** Crea una cuenta de cliente nueva e inicia sesión. Verifica que la sesión se mantenga activa y segura.
3. **Reserva y Cotización Dinámica (`/reservar/<id>`):**
   * Selecciona un pastel y elige el número de porciones; observa el cálculo dinámico del precio en tiempo real.
   * Selecciona fecha de retiro (con validación de anticipación mínima).
   * Elige entre pagar anticipo (50%) o total (100%), acepta los términos legales y confirma la reserva.
4. **Programa de Fidelidad (`/fidelidad`):** Comprueba cómo las compras acumulan puntos canjeables por productos del catálogo.
5. **Asistente Virtual con IA (TWINS IA):** Abre el chatbot interactivo ubicado en la esquina inferior y consulta sobre ingredientes, alérgenos o recomendaciones de postres.

### 2. Gestión Administrativa (Panel de Control)

1. **Gestión de Reservas:** Visualiza el pedido recién creado por el cliente, verifica su anticipo y avanza su estado (`Confirmada` ➔ `En Preparación` ➔ `Lista` ➔ `Entregada`).
2. **Control de Inventario y Productos:** Edita un producto existente, ajusta el stock o agrega un nuevo producto con imagen.
3. **Módulo Financiero y Métricas:** Revisa la recaudación del día, saldos pendientes y el historial de transacciones.
4. **Programa de Fidelidad Administrativo:** Audita el saldo de puntos de los clientes y gestiona órdenes de canje.
5. **Centro de Mensajería:** Atiende mensajes y consultas de clientes en tiempo real.




