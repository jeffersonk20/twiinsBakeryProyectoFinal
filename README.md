# 🍰 TWINS Bakery — Proyecto Final

Sistema web integral para la pastelería artesanal **TWINS Bakery**, desarrollado con **Python (Flask)** en el backend, arquitectura de datos relacional y asistente conversacional inteligente con ciberseguridad avanzada.

---

## 🚀 Guía Rápida de Instalación y Ejecución

El proyecto está diseñado para funcionar **inmediatamente tras ser clonado**, ya que incluye la base de datos SQLite preconfigurada con productos, imágenes y categorías de prueba.

### 1. Clonar el repositorio
```bash
git clone <URL_DEL_REPOSITORIO>
cd twiinsBakeryProyectoFinal
```

### 2. Instalar las dependencias de Python
Asegúrate de tener Python 3.10 o superior instalado:
```bash
pip install -r requirements.txt
```

### 3. Ejecutar la aplicación
Ejecuta el servidor backend:
```bash
python app.py
```

Al iniciarse, la consola mostrará un enlace interactivo al que puedes hacer clic directamente:
- **Tienda y Cliente:** [http://127.0.0.1:5000/](http://127.0.0.1:5000/)
- **Panel Administrativo:** [http://127.0.0.1:5000/admin/login](http://127.0.0.1:5000/admin/login)

---

## 🗄️ Base de Datos

* **Motor activo por defecto:** **SQLite** (`twins_bakery.db`). No requiere instalar MySQL ni configuraciones adicionales.
* **Compatibilidad MySQL:** También soporta conexión directa a MySQL en la nube (Aiven Cloud) configurando las variables en el archivo `.env`.
* **Reinicializar la Base de Datos (Opcional):**
  Si en algún momento deseas restablecer las tablas y recargar los productos iniciales con stock y fotos:
  ```bash
  python inicializar_bd.py
  ```

---

## 🔑 Credenciales de Acceso para Pruebas

### Panel de Administrador:
- **Ruta:** `/admin/login`
- **Correo:** `admin@twinsbakery.com`
- **Contraseña:** `Admin1234!`
- *(Token de configuración inicial si se requiere restablecer el admin: `twins_bakery_admin_token_2026_super_seguro_token_32chars`)*

### Cliente de Pruebas:
Puedes registrar una nueva cuenta en `/registro` o iniciar sesión con:
- **Ruta:** `/login`
- **Correo:** `cliente@gmail.com`
- **Contraseña:** `Cliente1234!`

---

## 🛡️ Características Principales
1. **Backend 100% en Python:** Toda la lógica de reservas, pagos, inventario y autenticación corre en el servidor.
2. **Cero filtración de datos sensibles:** Contraseñas hasheadas (`werkzeug.security`), tokens seguros con el módulo nativo `secrets`, y validación contra IDOR.
3. **Asistente Virtual con IA (TWINS IA):** Opera en modo estricto de solo lectura con aislamiento de contexto RAG y respuesta híbrida (Google Gemini 1.5 Flash o motor local seguro).
4. **Seguimiento de Reservas:** Flujo con cálculo de anticipo (50%), códigos únicos de entrega y seguimiento de estados.
5. **Chat en Tiempo Real:** Comunicación directa cliente-administrador y chats dedicados por evento.
