#  TWIINS Bakery — Proyecto Final

Sistema web integral de comercio electrónico y gestión para la pastelería artesanal **TWIINS Bakery**, desarrollado con **Python (Flask)** en el backend, arquitectura de datos relacional (SQLite / MySQL), asistente conversacional inteligente con ciberseguridad avanzada y panel administrativo con control financiero.


##  Guía Rápida de Instalación y Ejecución

El proyecto está diseñado para funcionar **inmediatamente tras ser clonado**, con la base de datos `twins_bakery.db` (SQLite) lista, con el catálogo de productos activo y la cuenta de administrador configurada. **No contiene clientes de prueba previos**, permitiendo evaluar el sistema desde cero.

### 1. Clonar el repositorio
```bash
git clone <URL_DE_TU_REPOSITORIO>
cd twiinsBakeryProyectoFinal
```

### 2. Crear y activar entorno virtual (Recomendado)

**En Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

**En Windows (CMD):**
```cmd
python -m venv venv
venv\Scripts\activate.bat
```

**En Linux / macOS:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Instalar dependencias
Asegúrate de contar con Python 3.10 o superior:
```bash
pip install -r requirements.txt
```

### 4. Iniciar el servidor
```bash
python app.py
```

Al iniciarse, abre en tu navegador:
- **Tienda y Cliente:** [http://127.0.0.1:5000/](http://127.0.0.1:5000/)
- **Panel Administrativo:** [http://127.0.0.1:5000/admin/login](http://127.0.0.1:5000/admin/login)

---

## 🔑 Credenciales del Sistema

### 👤 Administrador Oficial:
- **Ruta de acceso:** `http://127.0.0.1:5000/admin/login`
- **Correo:** `twiinsbakery01@gmail.com`
- **Contraseña:** `bakeryTnt2006`

### 👥 Clientes:
La base de datos se entrega limpia sin clientes registrados para permitir una evaluación real del flujo de onboarding:
1. Dirígete a registrarte y crea un nuevo cliente.
2. Inicia sesión con las credenciales que acabas de crear.

---

##  Funcionalidades de la Aplicación

* **Catálogo y Vitrina Interactiva:** Exploración de pasteles artesanales, porciones, postres y bebidas en tiempo real con filtrado por categoría y buscador instantáneo.

* **Sistema Inteligente de Reservas y Pedidos:** Cálculo dinámico de precio según porciones seleccionadas, pagos en línea por Pasarela de Pagos Wompi (tarjeta débito y crédito, PSE), validación de reglas de negocio en calendario (mínimo 5 días de anticipación para pasteles personalizados vs. retiro el mismo día para vitrina) y opciones de pago de anticipo (50%) o total (100%).

* **Planificador de Eventos:** Cotizador interactivo para bodas y celebraciones con cálculo de porciones según número de invitados y canal de chat directo con la pastelería.

* **Panel de Control Administrativo:**
  * **Gestión de Reservas:** Seguimiento por código único y actualización de estados del pedido en tiempo real.

  * **Control de Inventario y Productos:** Creación y edición de productos con subida de fotografías y control de stock.

  * **Módulo Financiero de Ingresos:** Monitoreo de recaudación del día, últimos 7 días y mes en curso; registro de ingresos/gastos manuales; balances netos y confirmación de entrega de anticipos retenidos por cancelación.
  * **Centro de Mensajería:** Comunicación bidireccional en tiempo real con clientes para soporte y pedidos especiales.
* **Asistente Virtual con IA (TWINS IA):** Chatbot interactivo y contextual integrado en la tienda para recomendaciones de postres, alérgenos y consultas rápidas del catálogo.
* **Ciberseguridad:** Contraseñas hasheadas (`scrypt`), tokens CSRF por sesión, consultas parametrizadas contra inyección SQL y control estricto de precios en backend.

