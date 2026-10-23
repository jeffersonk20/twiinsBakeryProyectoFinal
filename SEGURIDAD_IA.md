# 🛡️ Arquitectura de Seguridad y Asistente IA RAG — TWINS Bakery

Este documento detalla la arquitectura, las medidas de ciberseguridad, el cifrado de datos personales (PII), la defensa de base de datos y la implementación del flujo **RAG (Retrieval-Augmented Generation)** integrado con la **API de Google Gemini (Google AI Studio)** para la pastelería **TWINS Bakery** (operación sin pedidos a domicilio).

---

## 📐 1. Arquitectura del Sistema y Flujo de Datos

```
┌────────────────────────────────────────────────────────────────────────┐
│                        NAVEGADOR DEL USUARIO                           │
│  [UI de Chat Twins IA] (Color Institucional #B1F2D2 / Vanilla CSS/JS)  │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Peticiones Asíncronas (fetch / AJAX)
                                    │ Forzado HTTPS / TLS
                                    │ Encabezados: X-CSRF-Token / Bearer JWT
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                       BACKEND EN PYTHON (FLASK)                        │
│                 Proxy Seguro & Controlador de Lógica                   │
│                                                                        │
│ 1. Autenticación y Verificación de Rol:                                │
│    - Token JWT (HMAC-SHA256) o Sesión Criptográfica de Flask           │
│    - Roles Aislados: "Cliente" vs "Administrador"                      │
│                                                                        │
│ 2. Pipeline de Sanitización y Ciberdefensa (ia_seguridad.py):          │
│    - Sanitización XSS (Escape de etiquetas y caracteres de control)    │
│    - Detección de SQL Injection (SQLi)                                 │
│    - Detección de Prompt Injection & Jailbreaks                        │
│    - Filtro de Moderación contra Lenguaje Ofensivo                     │
│                                                                        │
│ 3. Aislamiento Físico de Contexto RAG (ia_database.py / ia_rag.py):    │
│    - Consultas SQL ejecutadas con conexión STRICT READ-ONLY            │
│    - Rol Cliente: Consulta ÚNICAMENTE tabla PRODUCTO (Sin stock núm.)  │
│    - Rol Administrador: Consulta analítica de métricas y existencias   │
│                                                                        │
│ 4. Construcción Dinámica de System Prompts:                            │
│    - Inyección de reglas inviolables (Hard Rules)                      │
│                                                                        │
│ 5. Cliente Proxy Gemini (ia_gemini.py):                                │
│    - Transmisión HTTPS directa a Google AI Studio                      │
│    - Credencial enviada en encabezado 'x-goog-api-key'                 │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
          ┌─────────────────────────┴─────────────────────────┐
          │                                                   │
          ▼                                                   ▼
┌───────────────────────────────────┐       ┌───────────────────────────────────┐
│     BASE DE DATOS SQL LOCAL       │       │    GOOGLE AI STUDIO (GEMINI)      │
│  - Conexión de SOLO LECTURA       │       │  - Endpoint HTTPS TLS v1.3        │
│  - SQLite: mode=ro & query_only=ON│       │  - Modelo: gemini-1.5-flash       │
│  - MySQL: DB_RO_USER (Solo SELECT)│       │  - System Instructions nativas    │
│  - PII Cifrado con AES (Fernet)   │       │  - Safety Settings activados      │
└───────────────────────────────────┘       └───────────────────────────────────┘
```

---

## 🔒 2. Medidas de Seguridad, Cifrado y Prevención de Fugas (Data Leakage)

### A. Gestión Estricta de Credenciales (`.env`)
- La clave `GEMINI_API_KEY` y las credenciales de base de datos se cargan **exclusivamente a través de variables de entorno**.
- **Jamás** se exponen claves de API al navegador ni en el código fuente.
- El archivo `.gitignore` previene que `.env` sea versionado en repositorios Git.

### B. Cifrado Simétrico de Datos Personales (PII)
- Ubicado en [ia_cifrado.py](file:///c:/Users/Daniel's%20laptop/Desktop/twinsbakery/twiinsBakeryProyectoFinal/ia_asistente/ia_cifrado.py).
- Utiliza **Fernet** de la librería `cryptography`, garantizando:
  - Cifrado simétrico AES-128 en modo CBC.
  - Firma e integridad mediante HMAC-SHA256.
  - Generación de claves aleatorias o derivación determinista mediante **PBKDF2-HMAC-SHA256** a partir de `SECRET_KEY`.
- Se implementan funciones de enmascaramiento (`enmascarar_correo`, `enmascarar_telefono`, `enmascarar_nombre`) para evitar fugas inadvertidas en respuestas de texto.

### C. Defensa de Base de Datos y Principio de Menor Privilegio (PoLP)
- Implementado en [ia_database.py](file:///c:/Users/Daniel's%20laptop/Desktop/twinsbakery/twiinsBakeryProyectoFinal/ia_asistente/ia_database.py).
- **Prohibido el uso de usuario admin/root de la base de datos para el flujo de la IA.**
- **En MySQL / MariaDB / Cloud DB:**
  - El backend utiliza `DB_RO_USER` y `DB_RO_PASSWORD`, usuarios a los que en el motor de BD solo se les otorga permiso `GRANT SELECT`.
  - Se ejecuta `SET SESSION TRANSACTION READ ONLY;` al inicio de cada conexión.
- **En SQLite (entorno local):**
  - La conexión se abre forzando el modo de solo lectura mediante URI: `file:{path}?mode=ro`. A nivel de kernel C de SQLite, cualquier intento de escritura genera una excepción física inmediata (`OperationalError: attempt to write a readonly database`).
  - Se activa `PRAGMA query_only = ON;`.
  - Cada sentencia SQL pasa por el analizador `_validar_consulta_solo_lectura()`, el cual verifica que la consulta inicie con `SELECT` o `WITH` y rechaza tajantemente palabras como `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, etc.

### D. Aislamiento Físico de Contexto (Matemáticamente Imposible de Filtrar)
Para evitar que un Prompt Injection o una alucinación del LLM extraiga datos sensibles:
- **Si el usuario es "Cliente":**
  - El código en Python **no ejecuta ninguna consulta SQL contra las tablas `CLIENTE`, `RESERVA`, `PAGO`, `ADMINISTRADOR` o `CHAT`**.
  - La consulta SQL se limita estrictamente a la tabla `PRODUCTO`:
    ```sql
    SELECT id_producto, nombre, categoria, precio, descripcion, disponible
    FROM PRODUCTO
    WHERE disponible = 1
    ```
  - **El conteo numérico de stock jamás se incluye en el contexto del cliente:** El valor se transforma internamente en una categoría booleana: `"Disponible"` o `"Agotado"`.
  - Como los datos sensibles nunca entran a la memoria del proceso ni al prompt del cliente, **es matemáticamente imposible que la IA filtre datos de otros clientes o reservas.**

### E. Sanitización y Detección de Inyecciones
- Ubicado en [ia_seguridad.py](file:///c:/Users/Daniel's%20laptop/Desktop/twinsbakery/twiinsBakeryProyectoFinal/ia_asistente/ia_seguridad.py).
- **Defensa contra XSS:** Se escapan todas las entidades HTML (`<`, `>`, `&`, `"`, `'`), impidiendo ataques de Cross-Site Scripting.
- **Defensa contra SQLi:** Detección de patrones maliciosos (`UNION SELECT`, `' OR '1'='1`, `DROP TABLE`). Todas las consultas internas usan parámetros tipados (parameterized queries).
- **Defensa contra Prompt Injection:** Detección de ataques de jailbreak (`ignore previous instructions`, `system prompt`, `modo desarrollador`, `dan mode`).

### F. Forzado de Conexión Segura (TLS/HTTPS)
- La comunicación del navegador con el backend fuerza HTTPS mediante encabezados HTTP:
  - `Strict-Transport-Security: max-age=31536000; includeSubDomains`
  - `X-Content-Type-Options: nosniff`
  - `X-Frame-Options: SAMEORIGIN`
- La comunicación entre Python y Google AI Studio se realiza estrictamente vía HTTPS con validación TLS estricta (`verify=True`).

---

## 👥 3. Lógica de Negocio y Reglas por Rol (System Prompts)

### Rol 1: VISTA CLIENTE
| Regla | Implementación |
| :--- | :--- |
| **Alcance** | Exclusivamente consultas sobre catálogo de pasteles, porciones, precios, recomendaciones y paquetes de eventos. |
| **Privacidad de Inventario** | La IA tiene **estrictamente prohibido dar cifras numéricas de stock**. Solo informa si el producto está **"Disponible"** o **"Agotado"**. |
| **Gestión de Reservas** | La IA **NO puede tomar reservas**. Debe indicar amablemente al cliente que utilice el sistema manual en el catálogo web o contacte directamente a la pastelería (`pedidos@twinsbakery.com`, WhatsApp `+503 2234-5678`). |
| **Cero Alucinaciones** | Prohibido inventar productos o precios fuera del contexto oficial inyectado. Si no existe, indica que no está en el menú. |
| **Moderación** | Ante insultos o lenguaje soez, la IA **corta la conversación inmediatamente**, exige un trato respetuoso y se niega a brindar información. |
| **Bloqueo PII** | Prohibido revelar nombres de otros clientes o detalles de pedidos. |
| **Sin Envíos a Domicilio** | Aclara siempre que todos los retiros se realizan en la pastelería física. |

### Rol 2: VISTA ADMINISTRADOR
| Regla | Implementación |
| :--- | :--- |
| **Autenticación Fuerte** | Verificación criptográfica mediante **JWT firmado con HMAC-SHA256** en el encabezado `Authorization: Bearer <token>` o sesión de Flask con flag `es_admin == True`. |
| **Alcance Analítico (Read-Only)** | La IA recibe estadísticas completas de ventas, total recaudado por anticipos, desglose de reservas por estado, **existencias numéricas reales** y listado de reservas recientes. |
| **Restricción de Modificación (Hard Rule Inviolable)** | **La IA tiene terminantemente prohibido ejecutar acciones en base de datos.** Si el administrador solicita crear, modificar o cancelar una reserva, o alterar inventario por el chat, la IA **se niega rotundamente** y le indica realizar la acción manualmente en los módulos del panel administrativo. |

---

## 🎨 4. Interfaz de Usuario (UI/UX)

- **Color Primario Institucional:** Código HEX `#B1F2D2` (utilizado en el botón flotante, aros de pulso interactivo, chips de consulta, detalles de mensajes y botones de envío).
- **Botón Flotante Interactivo:** Ubicado en la esquina inferior derecha con animación de pulso y acceso rápido.
- **Modal Desplegable (Drawer):**
  - Encabezado con estado en línea (`En línea`), avatar y badge de rol (`Cliente` o `Admin Analytics`).
  - Barra de **chips interactivos con preguntas rápidas** contextuales según el rol.
  - Feed de mensajes con formato de texto enriquecido (Markdown ligero seguro).
  - Indicador animado de respuesta (Typing loader con esferas color `#B1F2D2`).
  - Totalmente adaptativo a dispositivos móviles y pantallas de escritorio.

---

## 🚀 5. Guía de Puesta en Marcha

### 1. Variables en el archivo `.env`:
```ini
# API de Google AI Studio (obtén tu clave en https://aistudio.google.com/)
GEMINI_API_KEY=tu_clave_gemini_aqui
GEMINI_MODEL=gemini-1.5-flash

# Llave de cifrado de PII (opcional, se autoderiva si está vacía)
IA_ENCRYPTION_KEY=
JWT_SECRET_KEY=clave_secreta_para_firmar_jwt

# Credenciales de base de datos de solo lectura
DB_RO_USER=twins_ro_user
DB_RO_PASSWORD=tu_password_segura
```

### 2. Ejecución de Pruebas Automatizadas de Seguridad:
Para validar el aislamiento de roles, moderación, detección de inyecciones y la Hard Rule administrativa:
```powershell
python -c "import app; client = app.app.test_client(); print(client.get('/api/ia/info').get_json())"
```
