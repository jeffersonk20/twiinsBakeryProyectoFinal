
from flask import (
    Flask,
    abort,
    jsonify,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    send_from_directory,
    send_file,
    has_request_context,
)

from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.exceptions import HTTPException
# pyrefly: ignore[missing-import]
from conexion import obtener_conexion, SQLiteConnectionWrapper
# pyrefly: ignore[missing-import]
from inicializar_bd import inicializar_base_datos
from dotenv import load_dotenv
import os
import sys
import logging
import re
import socket
from functools import wraps
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from io import BytesIO
from datetime import date, datetime, time, timedelta
import hashlib
import hmac
import secrets
import time as time_module
from urllib.parse import urlsplit
import requests
import mysql.connector
# pyrefly: ignore[missing-import]
from servicios_correo import (
    enviar_correo_bienvenida,
    enviar_correo_inicio_sesion,
    enviar_correo_inicio_sesion_admin,
    enviar_correo_reserva_creada,
    enviar_correo_reserva_aceptada,
    enviar_correo_reserva_lista,
    enviar_correo_evento_aceptado,
    enviar_correo_evento_rechazado,
    enviar_correo_reserva_rechazada,
    enviar_correo_codigo_verificacion,
    enviar_correo_recuperacion_contrasena,
    enviar_correo_contrasena_actualizada,
    enviar_correo_pago_tarjeta_recibido,
)

load_dotenv()

APP_MODE = os.getenv("APP_MODE", "combined").strip().lower()
if APP_MODE not in {"combined", "customer", "admin"}:
    raise RuntimeError("APP_MODE debe ser combined, customer o admin.")


def _normalizar_url_publica(valor):
    valor = valor.strip().rstrip("/")
    if not valor:
        return ""
    url = urlsplit(valor if "://" in valor else f"http://{valor}")
    host = (url.hostname or "").lower()
    es_local = host in ("localhost", "127.0.0.1") or host.endswith(".localhost")
    if es_local:
        puerto_str = f":{url.port}" if url.port else ""
        return f"{url.scheme or 'http'}://{host}{puerto_str}"
    if (
        url.scheme not in ("https", "http")
        or not url.netloc
        or url.path
        or url.query
        or url.fragment
    ):
        raise RuntimeError("Las URL públicas deben ser válidas y no incluir rutas.")
    return f"{url.scheme}://{url.netloc}"


CLIENT_URL = _normalizar_url_publica(os.getenv("CLIENT_URL", ""))
if APP_MODE == "admin" and not CLIENT_URL:
    raise RuntimeError("Falta configurar CLIENT_URL para el servicio de administración.")

app = Flask(
    __name__,
    template_folder="html",
    static_folder=None
)

# ==============================================================================
# CONFIGURACIÓN UNIFICADA DE LOGS Y AUDITORÍA DE SERVIDOR
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
    force=True,
)

# Garantizar visibilidad de logs de la aplicación y componentes
app.logger.setLevel(logging.INFO)
logging.getLogger("werkzeug").setLevel(logging.INFO)
logging.getLogger("twins_bakery_db").setLevel(logging.INFO)
logging.getLogger("twins_bakery_correo").setLevel(logging.INFO)

# Clave privada para las sesiones (con autogeneración para evaluación inmediata si falta .env)
_secret_key = (os.getenv("SECRET_KEY") or "").strip()
if not _secret_key:
    if os.path.exists(".env.example") and not os.path.exists(".env"):
        import shutil
        try:
            shutil.copy(".env.example", ".env")
            load_dotenv()
            _secret_key = (os.getenv("SECRET_KEY") or "").strip()
            app.logger.info("Archivo .env generado automáticamente a partir de .env.example.")
        except Exception:
            pass
    if not _secret_key:
        _secret_key = "twins_bakery_default_dev_key_2026_evaluacion_segura"
        app.logger.warning("SECRET_KEY no detectada. Usando clave de desarrollo para evaluación.")
app.secret_key = _secret_key
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
)

@app.before_request
def _asegurar_sesion_permanente():
    session.permanent = True

@app.before_request
def _marcar_tiempo_inicio():
    request._tiempo_inicio_peticion = time_module.perf_counter()

@app.after_request
def _registrar_peticion_http(response):
    duracion_ms = 0.0
    if hasattr(request, "_tiempo_inicio_peticion"):
        duracion_ms = (time_module.perf_counter() - request._tiempo_inicio_peticion) * 1000.0

    es_estatico = request.path.startswith("/static/")
    # Registrar todas las rutas operativas, y los estáticos solo en caso de advertencia/error
    if not es_estatico or response.status_code >= 400:
        app.logger.info(
            "[HTTP] %s %s -> %s (%0.1f ms)",
            request.method,
            request.path,
            response.status_code,
            duracion_ms,
        )
    return response

# ==============================================================================
# INTEGRACIÓN DEL ASISTENTE DE IA (GEMINI RAG CON AISLAMIENTO POR ROL)
# ==============================================================================
try:
    # pyrefly: ignore[missing-import]
    from ia_asistente import ia_bp
    app.register_blueprint(ia_bp)
except Exception as err:
    app.logger.warning("No se pudo cargar el módulo ia_asistente: %s", err)

app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 MB para admitir carrusel y fotos de perfil de hasta 20 MB

CATEGORIAS_PRODUCTO = {"Porciones de Pasteles", "Pasteles", "Cupcakes", "Galletas", "Bebidas", "Postres completos"}
ESTADOS_RESERVA = {
    "PENDIENTE_PAGO",
    "CONFIRMADA",
    "EN_PREPARACION",
    "LISTA",
    "ENTREGADA",
    "CANCELADA",
}
WOMPI_CLIENT_ID = os.getenv("WOMPI_CLIENT_ID", "")
WOMPI_CLIENT_SECRET = os.getenv("WOMPI_CLIENT_SECRET", "")
URL_BASE_TUWEB = _normalizar_url_publica(os.getenv("URL_BASE_TUWEB", "")) or "http://localhost:5000"
WOMPI_TOKEN_URL = "https://id.wompi.sv/connect/token"
WOMPI_PAYMENT_LINK_URL = "https://api.wompi.sv/EnlacePago"
WOMPI_TOKEN = {"valor": None, "expira": 0}
TIPOS_IMAGEN = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
}


def _asegurar_columna_correo_reserva():
    """Garantiza que la columna 'correo' exista en RESERVA para SQLite y MySQL."""
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor()
        try:
            # Comprobación para SQLite
            cursor.execute("PRAGMA table_info(RESERVA)")
            columnas = [col[1] for col in cursor.fetchall()]
            if columnas and "correo" not in columnas:
                cursor.execute("ALTER TABLE RESERVA ADD COLUMN correo TEXT NULL")
                if hasattr(conexion, "commit"):
                    conexion.commit()
        except Exception:
            try:
                # Comprobación para MySQL
                cursor.execute(
                    """
                    SELECT COLUMN_NAME
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'RESERVA' AND COLUMN_NAME = 'correo'
                    """
                )
                if not cursor.fetchone():
                    cursor.execute("ALTER TABLE RESERVA ADD COLUMN correo VARCHAR(150) NULL AFTER nombre_cliente")
                    if hasattr(conexion, "commit"):
                        conexion.commit()
            except Exception as e_mysql:
                app.logger.warning("No se pudo verificar columna correo en MySQL: %s", e_mysql)
    except Exception as err:
        app.logger.warning("No se pudo verificar o agregar columna correo en RESERVA: %s", err)
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


try:
    _asegurar_columna_correo_reserva()
except Exception:
    pass


def _asegurar_tabla_verificacion_correo():
    """Garantiza la columna correo_verificado en CLIENTE y la tabla CODIGO_VERIFICACION."""
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor()
        # Verificar columna correo_verificado en SQLite
        try:
            cursor.execute("PRAGMA table_info(CLIENTE)")
            cols_cliente = [c[1] for c in cursor.fetchall()]
            if cols_cliente and "correo_verificado" not in cols_cliente:
                cursor.execute("ALTER TABLE CLIENTE ADD COLUMN correo_verificado BOOLEAN NOT NULL DEFAULT 1")
                if hasattr(conexion, "commit"):
                    conexion.commit()

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS CODIGO_VERIFICACION (
                id_codigo INTEGER PRIMARY KEY AUTOINCREMENT,
                correo TEXT NOT NULL,
                codigo TEXT NOT NULL,
                tipo TEXT NOT NULL DEFAULT 'REGISTRO',
                intentos INTEGER NOT NULL DEFAULT 0,
                usado BOOLEAN NOT NULL DEFAULT 0,
                expira_en TIMESTAMP NOT NULL,
                fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_codigo_correo ON CODIGO_VERIFICACION (correo, usado);")
            if hasattr(conexion, "commit"):
                conexion.commit()
        except Exception:
            # Fallback para MySQL
            try:
                cursor.execute(
                    """
                    SELECT COLUMN_NAME
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'CLIENTE' AND COLUMN_NAME = 'correo_verificado'
                    """
                )
                if not cursor.fetchone():
                    cursor.execute("ALTER TABLE CLIENTE ADD COLUMN correo_verificado BOOLEAN NOT NULL DEFAULT TRUE")
                    if hasattr(conexion, "commit"):
                        conexion.commit()

                cursor.execute("""
                CREATE TABLE IF NOT EXISTS CODIGO_VERIFICACION (
                    id_codigo INT AUTO_INCREMENT PRIMARY KEY,
                    correo VARCHAR(150) NOT NULL,
                    codigo VARCHAR(10) NOT NULL,
                    tipo VARCHAR(30) NOT NULL DEFAULT 'REGISTRO',
                    intentos INT NOT NULL DEFAULT 0,
                    usado BOOLEAN NOT NULL DEFAULT FALSE,
                    expira_en DATETIME NOT NULL,
                    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_codigo_correo (correo, usado)
                ) ENGINE=InnoDB;
                """)
                if hasattr(conexion, "commit"):
                    conexion.commit()
            except Exception as e_mysql:
                app.logger.warning("No se pudo verificar CODIGO_VERIFICACION en MySQL: %s", e_mysql)
    except Exception as err:
        app.logger.warning("No se pudo verificar CODIGO_VERIFICACION: %s", err)
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


try:
    _asegurar_tabla_verificacion_correo()
except Exception:
    pass


def _asegurar_esquema_perfil_y_carrusel():
    """Garantiza columnas de foto de perfil en CLIENTE y la tabla CARRUSEL_HOME para SQLite y MySQL."""
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor()
        # 1. Comprobación y creación para SQLite
        try:
            cursor.execute("PRAGMA table_info(CLIENTE)")
            cols_cliente = [c[1] for c in cursor.fetchall()]
            if cols_cliente and "foto_perfil" not in cols_cliente:
                cursor.execute("ALTER TABLE CLIENTE ADD COLUMN foto_perfil BLOB NULL")
            if cols_cliente and "tipo_foto_perfil" not in cols_cliente:
                cursor.execute("ALTER TABLE CLIENTE ADD COLUMN tipo_foto_perfil TEXT NULL")

            cursor.execute("""
            CREATE TABLE IF NOT EXISTS CARRUSEL_HOME (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                imagen BLOB NOT NULL,
                tipo_imagen TEXT NOT NULL,
                orden INTEGER DEFAULT 0,
                fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """)
            if hasattr(conexion, "commit"):
                conexion.commit()
        except Exception:
            # 2. Comprobación y creación para MySQL
            try:
                cursor.execute(
                    """
                    SELECT COLUMN_NAME
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'CLIENTE' AND COLUMN_NAME = 'foto_perfil'
                    """
                )
                if not cursor.fetchone():
                    cursor.execute("ALTER TABLE CLIENTE ADD COLUMN foto_perfil LONGBLOB NULL")

                cursor.execute(
                    """
                    SELECT COLUMN_NAME
                    FROM INFORMATION_SCHEMA.COLUMNS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'CLIENTE' AND COLUMN_NAME = 'tipo_foto_perfil'
                    """
                )
                if not cursor.fetchone():
                    cursor.execute("ALTER TABLE CLIENTE ADD COLUMN tipo_foto_perfil VARCHAR(50) NULL")

                cursor.execute("""
                CREATE TABLE IF NOT EXISTS CARRUSEL_HOME (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    imagen LONGBLOB NOT NULL,
                    tipo_imagen VARCHAR(50) NOT NULL,
                    orden INT DEFAULT 0,
                    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ) ENGINE=InnoDB;
                """)
                if hasattr(conexion, "commit"):
                    conexion.commit()
            except Exception as e_mysql:
                app.logger.warning("No se pudo verificar esquema perfil/carrusel en MySQL: %s", e_mysql)
    except Exception as err:
        app.logger.warning("No se pudo verificar esquema perfil/carrusel: %s", err)
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


try:
    _asegurar_esquema_perfil_y_carrusel()
except Exception:
    pass

# Inicializar automáticamente las tablas y el admin en la base de datos si no existen
try:
    app.logger.info("Verificando e inicializando estructura de la base de datos...")
    inicializar_base_datos()
    app.logger.info("Base de datos verificada e inicializada con éxito.")
except Exception as _err_bd_init:
    app.logger.warning("Aviso durante la inicialización de la base de datos: %s", _err_bd_init)


# Dominios de correo autorizados para evitar correos ficticios
DOMINIOS_CORREO_PERMITIDOS = {
    "gmail.com",
    "googlemail.com",
    "hotmail.com",
    "outlook.com",
    "live.com",
    "msn.com",
    "yahoo.com",
    "yahoo.es",
    "ymail.com",
    "icloud.com",
}


def es_correo_valido(correo: str) -> tuple[bool, str]:
    """Valida formato y dominio permitido del correo para clientes."""
    if not correo or "@" not in correo:
        return False, "Ingresa un correo electrónico válido."

    correo_limpio = correo.strip().lower()
    partes = correo_limpio.split("@")
    if len(partes) != 2:
        return False, "Formato de correo electrónico inválido."

    usuario, dominio = partes[0].strip(), partes[1].strip()

    if not usuario or len(usuario) < 3:
        return False, "El nombre de usuario del correo debe tener al menos 3 caracteres."

    if not re.match(r"^[a-zA-Z0-9_.+-]+$", usuario):
        return False, "El correo contiene caracteres no permitidos."

    if usuario.startswith(".") or usuario.endswith(".") or ".." in usuario:
        return False, "El formato del correo es inválido."

    if dominio not in DOMINIOS_CORREO_PERMITIDOS:
        return False, (
            "Para evitar correos inventados, solo se permiten proveedores autorizados "
            "como Google (@gmail.com), Microsoft (@hotmail.com, @outlook.com), "
            "Yahoo (@yahoo.com) o Apple (@icloud.com)."
        )

    return True, ""



@app.before_request
def separar_sitios():
    if APP_MODE == "combined":
        return None

    es_ruta_admin = request.path.startswith(("/admin", "/api/admin"))
    if APP_MODE == "admin":
        if request.path == "/":
            return redirect(url_for("admin_login"))
        # Permitir rutas estáticas y endpoints del Asistente de IA en modo admin
        if es_ruta_admin or request.path.startswith(("/static/", "/api/ia/")):
            return None
        abort(404)

    if es_ruta_admin:
        abort(404)
    return None


@app.template_filter("primer_nombre")
def _filtro_primer_nombre(valor):
    """Extrae el primer nombre de forma segura evitando excepciones por cadenas vacías o espacios."""
    if not valor or not isinstance(valor, str):
        return "Cliente"
    tokens = valor.strip().split()
    return tokens[0] if tokens else "Cliente"


@app.context_processor
def urls_entre_sitios():
    nom = session.get("nombre_cliente", "")
    tokens = nom.strip().split() if isinstance(nom, str) and nom.strip() else []
    nombre_seguro = tokens[0] if tokens else "Cliente"
    return {
        "client_home_url": CLIENT_URL or url_for("index"),
        "client_catalog_url": (
            f"{CLIENT_URL}/catalogo" if CLIENT_URL else url_for("catalogo")
        ),
        "cliente_primer_nombre": nombre_seguro,
    }


def _cliente_activo(cliente_id):
    if not cliente_id:
        return False
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor()
        cursor.execute(
            "SELECT id_cliente FROM CLIENTE WHERE id_cliente = %s",
            (cliente_id,),
        )
        return cursor.fetchone() is not None
    except Exception:
        return False
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


def cliente_requerido(view):
    @wraps(view)
    def vista_protegida(*args, **kwargs):
        id_cli = session.get("id_cliente")
        if not id_cli:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Inicia sesión para continuar."}), 401
            return redirect(url_for("login"))
        if not _cliente_activo(id_cli):
            session.pop("id_cliente", None)
            session.pop("nombre_cliente", None)
            session.pop("correo_cliente", None)
            if request.path.startswith("/api/"):
                return jsonify({"error": "Tu sesión ha caducado. Inicia sesión nuevamente."}), 401
            flash("Tu sesión anterior no es válida. Inicia sesión para continuar.", "info")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return vista_protegida


def administrador_requerido(view):
    @wraps(view)
    def vista_protegida(*args, **kwargs):
        if not session.get("es_admin"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Inicia sesión como administrador."}), 401
            return redirect(url_for("admin_login"))
        try:
            if not _administrador_activo(session.get("id_admin")):
                session.clear()
                if request.path.startswith("/api/"):
                    return jsonify({"error": "La cuenta administradora ya no existe. Inicia sesión otra vez."}), 401
                return redirect(url_for("admin_login"))
        except mysql.connector.Error:
            app.logger.exception("No se pudo validar la sesión de administrador.")
            if request.path.startswith("/api/"):
                return jsonify({"error": "No se pudo validar el acceso administrativo."}), 503
            return "No se pudo validar el acceso administrativo. Revisa la conexión e inténtalo otra vez.", 503
        if not session.get("csrf_token"):
            session["csrf_token"] = secrets.token_urlsafe(32)
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            token_esperado = session.get("csrf_token", "")
            token_recibido = (
                request.headers.get("X-CSRF-Token")
                or request.form.get("csrf_token", "")
            )
            if not token_esperado or not hmac.compare_digest(token_esperado, token_recibido):
                return jsonify({"error": "La sesión de seguridad venció. Recarga el panel e inténtalo otra vez."}), 403
        return view(*args, **kwargs)

    return vista_protegida


def _csrf_valido():
    token_esperado = session.get("csrf_token", "")
    token_recibido = (
        request.headers.get("X-CSRF-Token")
        or request.form.get("csrf_token", "")
    )
    return bool(
        token_esperado
        and token_recibido
        and hmac.compare_digest(token_esperado, token_recibido)
    )


def _contar_administradores():
    conexion = obtener_conexion()
    cursor = None
    try:
        cursor = conexion.cursor()
        cursor.execute("SELECT COUNT(*) FROM ADMINISTRADOR")
        return int(cursor.fetchone()[0])
    finally:
        if cursor:
            cursor.close()
        if conexion.is_connected():
            conexion.close()


def _administrador_activo(admin_id):
    if not admin_id:
        return False
    conexion = obtener_conexion()
    cursor = None
    try:
        cursor = conexion.cursor()
        cursor.execute(
            "SELECT id_admin FROM ADMINISTRADOR WHERE id_admin = %s",
            (admin_id,),
        )
        return cursor.fetchone() is not None
    finally:
        if cursor:
            cursor.close()
        if conexion.is_connected():
            conexion.close()


def _normalizar_reserva(registro):
    return {
        "id": registro["id_reserva"],
        "codigo": registro["codigo"],
        "cliente": registro["nombre_cliente"],
        "correo": registro["correo"],
        "telefono": registro["telefono"],
        "producto": registro["nombre_producto"],
        "cantidad": registro["cantidad"],
        "precio_unitario": float(registro["precio_unitario"]),
        "total": float(registro["total"]),
        "anticipo_requerido": float(registro["anticipo_requerido"]),
        "monto_pagado": float(registro["monto_pagado"]),
        "fecha_retiro": registro["fecha_retiro"].isoformat(sep=" ", timespec="minutes"),
        "estado": registro["estado"],
        "metodo_pago": registro["metodo_pago"],
        "pago_estado": registro["pago_estado"],
        "es_canje_fidelidad": bool(registro.get("es_canje_fidelidad", False)),
        "puntos_usados": int(registro.get("puntos_usados", 0) or 0),
    }


def _notificar_reserva_confirmada(reserva_id):
    """Consulta los datos de la reserva y notifica al cliente que fue aceptada y confirmada."""
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT r.codigo, r.nombre_cliente,
                   COALESCE(NULLIF(r.correo, ''), c.correo, '') AS correo,
                   r.total, r.monto_pagado, r.fecha_retiro,
                   d.nombre_producto, d.cantidad
            FROM RESERVA r
            LEFT JOIN CLIENTE c ON c.id_cliente = r.id_cliente
            JOIN DETALLE_RESERVA d ON d.id_reserva = r.id_reserva
            WHERE r.id_reserva = %s
            ORDER BY d.id_detalle ASC
            LIMIT 1
            """,
            (reserva_id,),
        )
        datos = cursor.fetchone()
        if datos and datos.get("correo"):
            enviar_correo_reserva_aceptada(
                destinatario=datos["correo"],
                nombre=datos["nombre_cliente"],
                codigo=datos["codigo"],
                nombre_producto=datos["nombre_producto"],
                cantidad=datos["cantidad"],
                total=datos["total"],
                monto_pagado=datos["monto_pagado"],
                fecha_retiro=datos["fecha_retiro"],
            )
    except Exception as err:
        app.logger.warning("No se pudo notificar la reserva confirmada %s: %s", reserva_id, err)
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


def _notificar_reserva_lista(reserva_id):
    """Consulta los datos de la reserva y notifica al cliente que su pedido ya está listo para retirar."""
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT r.codigo, r.nombre_cliente,
                   COALESCE(NULLIF(r.correo, ''), c.correo, '') AS correo,
                   r.total, r.monto_pagado, r.fecha_retiro,
                   d.nombre_producto, d.cantidad
            FROM RESERVA r
            LEFT JOIN CLIENTE c ON c.id_cliente = r.id_cliente
            JOIN DETALLE_RESERVA d ON d.id_reserva = r.id_reserva
            WHERE r.id_reserva = %s
            ORDER BY d.id_detalle ASC
            LIMIT 1
            """,
            (reserva_id,),
        )
        datos = cursor.fetchone()
        if datos and datos.get("correo"):
            enviar_correo_reserva_lista(
                destinatario=datos["correo"],
                nombre=datos["nombre_cliente"],
                codigo=datos["codigo"],
                nombre_producto=datos["nombre_producto"],
                cantidad=datos["cantidad"],
                total=datos["total"],
                monto_pagado=datos["monto_pagado"],
                fecha_retiro=datos["fecha_retiro"],
            )
            return True
        return False
    except Exception as err:
        app.logger.warning("No se pudo notificar la reserva lista %s: %s", reserva_id, err)
        return False
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


def _notificar_reserva_rechazada(reserva_id, motivo=None):
    """Consulta los datos de la reserva y notifica al cliente que fue rechazada o cancelada."""
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT r.codigo, r.nombre_cliente,
                   COALESCE(NULLIF(r.correo, ''), c.correo, '') AS correo,
                   r.total, r.fecha_retiro,
                   d.nombre_producto, d.cantidad
            FROM RESERVA r
            LEFT JOIN CLIENTE c ON c.id_cliente = r.id_cliente
            JOIN DETALLE_RESERVA d ON d.id_reserva = r.id_reserva
            WHERE r.id_reserva = %s
            ORDER BY d.id_detalle ASC
            LIMIT 1
            """,
            (reserva_id,),
        )
        datos = cursor.fetchone()
        if datos and datos.get("correo"):
            enviar_correo_reserva_rechazada(
                destinatario=datos["correo"],
                nombre=datos["nombre_cliente"],
                codigo=datos["codigo"],
                nombre_producto=datos["nombre_producto"],
                cantidad=datos["cantidad"],
                total=datos["total"],
                fecha_retiro=datos["fecha_retiro"],
                motivo=motivo,
            )
            return True
        return False
    except Exception as err:
        app.logger.warning("No se pudo notificar la reserva rechazada %s: %s", reserva_id, err)
        return False
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


def _wompi_configurada():
    if not (WOMPI_CLIENT_ID and WOMPI_CLIENT_SECRET):
        return False
    base_url = urlsplit(URL_BASE_TUWEB)
    return bool(
        base_url.netloc
        and (base_url.scheme in ("https", "http"))
    )


def _obtener_ip_local():
    """Detecta la IP local de la computadora en la red Wi-Fi/Ethernet."""
    try:
        ip = socket.gethostbyname(socket.gethostname())
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    return "localhost"


def obtener_token():
    if WOMPI_TOKEN["valor"] and time_module.time() < WOMPI_TOKEN["expira"] - 60:
        return WOMPI_TOKEN["valor"]
    if not WOMPI_CLIENT_ID or not WOMPI_CLIENT_SECRET:
        raise ValueError("Falta configurar WOMPI_CLIENT_ID y WOMPI_CLIENT_SECRET.")
    respuesta = requests.post(
        WOMPI_TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "audience": "wompi_api",
            "client_id": WOMPI_CLIENT_ID,
            "client_secret": WOMPI_CLIENT_SECRET,
        },
        timeout=15,
    )
    respuesta.raise_for_status()
    datos = respuesta.json()
    if (
        not isinstance(datos, dict)
        or not isinstance(datos.get("access_token"), str)
        or not datos["access_token"]
        or not isinstance(datos.get("expires_in"), (int, float))
        or datos["expires_in"] <= 0
    ):
        raise ValueError("Wompi devolvió una respuesta OAuth inválida.")
    WOMPI_TOKEN["valor"] = datos["access_token"]
    WOMPI_TOKEN["expira"] = time_module.time() + datos["expires_in"]
    return WOMPI_TOKEN["valor"]


def crear_enlace_pago(pedido_id, monto, nombre_producto):
    if not _wompi_configurada():
        raise ValueError("Configura las credenciales WOMPI_CLIENT_ID y WOMPI_CLIENT_SECRET en .env.")
    monto = Decimal(str(monto)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if monto <= 0 or not pedido_id or not nombre_producto:
        raise ValueError("Los datos del enlace de pago no son válidos.")

    correo_comercio = os.getenv("MAIL_USERNAME", "jeffersonk20castillo@gmail.com").strip()
    if has_request_context():
        # Tomar la URL base exacta de la petición actual (ej. http://127.0.0.1:5000 o https://dominio.com)
        url_base = request.host_url.rstrip("/")
    else:
        url_base = URL_BASE_TUWEB.strip().rstrip("/") if URL_BASE_TUWEB else "http://localhost:5000"

    # Wompi (Azure WAF) bloquea IPs en urlRedirect (ej. http://127.0.0.1:5000 devuelve 403 Forbidden).
    # Reemplazamos 127.0.0.1 por localhost para que la pasarela lo acepte sin problemas.
    if "127.0.0.1" in url_base:
        url_base = url_base.replace("://127.0.0.1", "://localhost")

    base_split = urlsplit(url_base)
    host = (base_split.hostname or "").lower()
    es_local = host in ("localhost", "127.0.0.1") or host.endswith(".localhost")

    configuracion = {
        "notificarTransaccionCliente": True,
        "emailsNotificacion": correo_comercio,
        "urlRedirect": f"{url_base}/pago/resultado",
    }

    # Solo incluir urlWebhook si es un dominio público real en internet (no localhost)
    if not es_local and base_split.scheme == "https":
        configuracion["urlWebhook"] = f"{url_base}/webhook/wompi"

    payload = {
        "identificadorEnlaceComercio": str(pedido_id),
        "monto": float(monto),
        "nombreProducto": str(nombre_producto)[:100],
        "configuracion": configuracion,
    }
    respuesta = requests.post(
        WOMPI_PAYMENT_LINK_URL,
        json=payload,
        headers={"Authorization": f"Bearer {obtener_token()}"},
        timeout=15,
    )
    if not respuesta.ok:
        app.logger.error("Error respuesta Wompi: %s - %s", respuesta.status_code, respuesta.text)
    respuesta.raise_for_status()
    enlace = respuesta.json()
    if (
        not isinstance(enlace, dict)
        or not isinstance(enlace.get("idEnlace"), (str, int))
        or not isinstance(enlace.get("urlEnlace"), str)
    ):
        raise ValueError("Wompi devolvió un enlace de pago inválido.")
    url_pago = urlsplit(enlace["urlEnlace"])
    if url_pago.scheme != "https" or not url_pago.netloc:
        raise ValueError("Wompi devolvió una URL de pago no segura.")
    return enlace


def consultar_estado_enlace_wompi(id_enlace):
    """Consulta la API de Wompi para saber si un enlace de pago ya fue completado exitosamente."""
    if not (WOMPI_CLIENT_ID and WOMPI_CLIENT_SECRET) or not id_enlace:
        return {"pagado": False, "transacciones": []}
    try:
        token = obtener_token()
        url = f"{WOMPI_PAYMENT_LINK_URL}/{id_enlace}"
        res = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
        if res.ok:
            datos = res.json()

            # Desempaquetar si viene envuelto
            if isinstance(datos, dict) and "data" in datos and isinstance(datos["data"], dict):
                payload = datos["data"]
            elif isinstance(datos, dict) and "resultado" in datos and isinstance(datos["resultado"], dict):
                payload = datos["resultado"]
            else:
                payload = datos if isinstance(datos, dict) else {}

            pagos_exitosos = int(payload.get("cantidadPagosExitosos") or payload.get("cantidadPagos") or 0)
            esta_pagado_flag = bool(payload.get("estaPagado") or payload.get("esPagado") or payload.get("pagado"))

            # Revisar transaccionCompra (última transacción registrada en Wompi)
            tc = payload.get("transaccionCompra") or {}
            tc_exitosa = bool(
                tc and (
                    tc.get("resultadoTransaccion") in (0, "0", "ExitosaAprobada", "Aprobada")
                    or tc.get("idTransaccion")
                    or tc.get("esAprobada") is True
                    or tc.get("codigoAutorizacion")
                )
            )

            # Revisar lista de transacciones
            transacciones = payload.get("transacciones") or []
            tx_exitosa = any(
                isinstance(t, dict) and (
                    t.get("resultadoTransaccion") in (0, "0", "ExitosaAprobada", "Aprobada")
                    or t.get("esAprobada") is True
                    or t.get("idTransaccion")
                    or t.get("codigoAutorizacion")
                )
                for t in transacciones
            )

            pagado = bool(pagos_exitosos > 0 or esta_pagado_flag or tc_exitosa or tx_exitosa)

            return {
                "pagado": pagado,
                "pagos_exitosos": pagos_exitosos,
                "transacciones": transacciones,
                "datos": payload,
            }
        else:
            app.logger.warning("Error respuesta Wompi GET EnlacePago %s: %s - %s", id_enlace, res.status_code, res.text)
    except Exception as e:
        app.logger.warning("Error al consultar estado de enlace Wompi %s: %s", id_enlace, e)
    return {"pagado": False, "transacciones": []}


def _acreditar_puntos_fidelidad_si_corresponde(cursor, conexion, reserva_id):
    """
    Calcula y acredita puntos de fidelidad para una reserva completamente pagada o entregada.
    Reglas:
    - 1 punto por cada $1 dólar gastado (sólo parte entera, ej. $20.99 -> 20 pts, $1.50 -> 1 pt).
    - Excluye pedidos de Eventos y bebidas individuales sin promoción.
    - Se acredita una única vez por pedido (evita duplicidades comprobando puntos_otorgados).
    - Los canjes de fidelidad (es_canje_fidelidad = 1) no generan puntos.
    """
    try:
        cursor.execute(
            """
            SELECT id_reserva, codigo, id_cliente, correo, total, monto_pagado,
                   estado, COALESCE(es_canje_fidelidad, 0) AS es_canje_fidelidad,
                   COALESCE(puntos_otorgados, 0) AS puntos_otorgados
            FROM RESERVA
            WHERE id_reserva = %s
            """,
            (reserva_id,),
        )
        res = cursor.fetchone()
        if not res:
            return 0

        # Si ya se otorgaron puntos, evitar duplicidad
        puntos_otorgados = res.get("puntos_otorgados") if isinstance(res, dict) else res[8]
        if puntos_otorgados:
            return 0

        # Si es un canje de fidelidad, no acumula puntos
        es_canje = res.get("es_canje_fidelidad") if isinstance(res, dict) else res[7]
        if es_canje:
            return 0

        total = Decimal(str((res.get("total") if isinstance(res, dict) else res[4]) or 0))
        pagado = Decimal(str((res.get("monto_pagado") if isinstance(res, dict) else res[5]) or 0))
        estado = str((res.get("estado") if isinstance(res, dict) else res[6]) or "")

        # Debe estar 100% pagada o entregada con pago total
        if pagado < total and estado != "ENTREGADA":
            return 0

        # Obtener o resolver id_cliente
        id_cliente = res.get("id_cliente") if isinstance(res, dict) else res[2]
        correo_res = res.get("correo") if isinstance(res, dict) else res[3]
        if not id_cliente and correo_res:
            cursor.execute(
                "SELECT id_cliente FROM CLIENTE WHERE LOWER(correo) = LOWER(%s) LIMIT 1",
                (str(correo_res).strip(),),
            )
            cli_row = cursor.fetchone()
            if cli_row:
                id_cliente = cli_row["id_cliente"] if isinstance(cli_row, dict) else cli_row[0]
                cursor.execute("UPDATE RESERVA SET id_cliente = %s WHERE id_reserva = %s", (id_cliente, reserva_id))

        if not id_cliente:
            return 0

        # Calcular subtotal de productos participantes
        cursor.execute(
            """
            SELECT d.precio_unitario, d.cantidad, d.nombre_producto,
                   p.categoria, COALESCE(p.genera_puntos, 1) AS genera_puntos
            FROM DETALLE_RESERVA d
            LEFT JOIN PRODUCTO p ON d.id_pastel = p.id_producto
            WHERE d.id_reserva = %s
            """,
            (reserva_id,),
        )
        detalles = cursor.fetchall() or []

        subtotal_valido = Decimal("0.00")
        if detalles:
            for item in detalles:
                cat = str((item.get("categoria") if isinstance(item, dict) else item[3]) or "").upper()
                gen = item.get("genera_puntos") if isinstance(item, dict) else item[4]
                es_bebida = any(b in cat for b in ["BEBIDA", "SODA", "REFRESCO", "ENLATADA", "EMBOTELLADA"])
                es_evento = "EVENTO" in cat or "EVENTOS" in cat

                if es_evento:
                    continue
                if es_bebida and not gen:
                    continue
                if gen is False or gen == 0:
                    continue

                pu = Decimal(str((item.get("precio_unitario") if isinstance(item, dict) else item[0]) or 0))
                cant = int((item.get("cantidad") if isinstance(item, dict) else item[1]) or 1)
                subtotal_valido += pu * cant
        else:
            subtotal_valido = total

        monto_para_puntos = min(subtotal_valido, pagado)
        puntos_ganados = int(monto_para_puntos)

        if puntos_ganados <= 0:
            cursor.execute("UPDATE RESERVA SET puntos_otorgados = 1 WHERE id_reserva = %s", (reserva_id,))
            return 0

        cursor.execute(
            "SELECT COALESCE(puntos_fidelidad, 0) AS puntos_fidelidad FROM CLIENTE WHERE id_cliente = %s",
            (id_cliente,),
        )
        cli = cursor.fetchone()
        saldo_actual = (cli.get("puntos_fidelidad") or 0) if isinstance(cli, dict) else (cli[0] if cli else 0)
        nuevo_saldo = int(saldo_actual) + puntos_ganados

        cursor.execute(
            "UPDATE CLIENTE SET puntos_fidelidad = %s WHERE id_cliente = %s",
            (nuevo_saldo, id_cliente),
        )

        cursor.execute(
            "UPDATE RESERVA SET puntos_otorgados = 1, fecha_puntos = NOW() WHERE id_reserva = %s",
            (reserva_id,),
        )

        codigo_res = res.get("codigo") if isinstance(res, dict) else res[1]
        desc = f"Compra completada: +{puntos_ganados} puntos (Pedido #{codigo_res})"
        cursor.execute(
            """
            INSERT INTO HISTORIAL_PUNTOS (
                id_cliente, id_reserva, tipo, puntos, descripcion, saldo_resultante,
                fecha_registro, fecha, motivo, tipo_movimiento
            ) VALUES (%s, %s, 'ACUMULACION', %s, %s, %s, NOW(), NOW(), %s, 'ACUMULACION')
            """,
            (id_cliente, reserva_id, puntos_ganados, desc, nuevo_saldo, desc),
        )

        app.logger.info(
            "Puntos acreditados con éxito: +%d puntos a cliente %s por reserva %s (Nuevo saldo: %d)",
            puntos_ganados, id_cliente, codigo_res, nuevo_saldo
        )
        return puntos_ganados
    except Exception as e:
        app.logger.warning("No se pudieron acreditar puntos de fidelidad para reserva %s: %s", reserva_id, e)
        return 0


def _marcar_pago_aprobado(datos_webhook):
    enlace = datos_webhook.get("EnlacePago")
    if not isinstance(enlace, dict):
        return False
    referencia = str(enlace.get("IdentificadorEnlaceComercio", "")).strip()
    try:
        monto_pagado = Decimal(str(datos_webhook.get("Monto", ""))).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
    except (InvalidOperation, ValueError):
        return False
    if (
        not referencia
        or len(referencia) > 100
        or not monto_pagado.is_finite()
        or monto_pagado <= 0
    ):
        return False

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT p.id_pago, p.id_reserva, p.monto, p.estado AS pago_estado
            FROM PAGO p
            JOIN RESERVA r ON r.id_reserva = p.id_reserva
            WHERE p.referencia = %s AND p.metodo_pago = 'WOMPI'
            FOR UPDATE
            """,
            (referencia,),
        )
        pago = cursor.fetchone()
        if not pago:
            conexion.rollback()
            return False
        monto_esperado = Decimal(str(pago["monto"])).quantize(Decimal("0.01"))
        if monto_pagado != monto_esperado:
            conexion.rollback()
            return False
        if pago["pago_estado"] == "PAGADO":
            conexion.commit()
            return True
        if pago["pago_estado"] != "PENDIENTE":
            conexion.rollback()
            return False

        cursor.execute(
            """
            UPDATE PAGO SET estado = 'PAGADO', fecha_pago = NOW()
            WHERE id_pago = %s AND estado = 'PENDIENTE'
            """,
            (pago["id_pago"],),
        )
        if cursor.rowcount != 1:
            conexion.rollback()
            return False

        cursor.execute(
            """
            UPDATE RESERVA
            SET monto_pagado = monto_pagado + %s,
                estado = CASE
                    WHEN monto_pagado + %s >= anticipo_requerido
                         AND estado = 'PENDIENTE_PAGO' THEN 'CONFIRMADA'
                    ELSE estado
                END
            WHERE id_reserva = %s
            """,
            (pago["monto"], pago["monto"], pago["id_reserva"]),
        )
        _acreditar_puntos_fidelidad_si_corresponde(cursor, conexion, pago["id_reserva"])
        conexion.commit()
        _notificar_reserva_confirmada(pago["id_reserva"])
        return True
    except mysql.connector.Error:
        if conexion:
            conexion.rollback()
        app.logger.exception("No se pudo registrar la confirmación de pago de Wompi El Salvador.")
        raise
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


# ==========================================
# ARCHIVOS CSS E IMÁGENES
# ==========================================

@app.route("/static/<path:filename>")
def static_files(filename):
    if APP_MODE == "customer" and filename.startswith(("css/admin_", "js/admin_")):
        abort(404)

    # Solo permitir archivos estáticos de la aplicación
    if filename.startswith("css/"):
        carpeta = "css"
        archivo = filename[4:]

    elif filename.startswith("img/"):
        carpeta = "img"
        archivo = filename[4:]

    elif filename.startswith("js/"):
        carpeta = "js"
        archivo = filename[3:]

    else:
        return "Archivo no permitido", 404

    return send_from_directory(carpeta, archivo)


@app.route("/img/<path:archivo>")
@app.route("/assets/<path:archivo>")
def imagenes_estaticas_directas(archivo):
    """Permite el acceso a imágenes con rutas absolutas como /img/logo.png o /assets/logo.png."""
    return send_from_directory("img", archivo)


# ==========================================
# PANTALLA DE BIENVENIDA / INICIO
# ==========================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/inicio")
@cliente_requerido
def inicio():
    return render_template("inicio.html", nombre_cliente=session.get("nombre_cliente"))


@app.route("/catalogo")
@cliente_requerido
def catalogo():
    return render_template("home.html")


@app.route("/vitrina")
@cliente_requerido
def vitrina():
    return render_template("vitrina.html")


@app.route("/producto/<producto_id>")
@cliente_requerido
def detalle_producto(producto_id):
    return render_template("detalle_producto.html", producto_id=producto_id)


# ==========================================
# RUTAS LEGALES Y POLÍTICAS (EL SALVADOR)
# ==========================================
@app.route("/politica-privacidad")
def politica_privacidad():
    return render_template("politica_privacidad.html")


@app.route("/terminos-condiciones")
def terminos_condiciones():
    return render_template("terminos_condiciones.html")


@app.route("/politica-retiro-reembolsos")
def politica_retiro_reembolsos():
    return render_template("politica_retiro_reembolsos.html")


# ==========================================
# SECCIÓN DE EVENTOS Y CELEBRACIONES
# ==========================================

EVENTOS_DISPONIBLES = {
    "cumpleanos": {
        "tipo": "cumpleanos",
        "tipo_label": "Cumpleaños",
        "nombre": "Celebración de Cumpleaños",
        "titulo": "Cumpleaños Inolvidables",
        "descripcion_corta": "Pasteles personalizados, cupcakes temáticos y detalles dulces para celebrar un año más de vida.",
        "descripcion": "Haz que cada cumpleaños sea una fiesta inolvidable con nuestros pasteles temáticos personalizados, cupcakes a juego y mesas de postres diseñadas para deleitar a todos tus invitados.",
        "imagen": "https://crumblegf.com/wp-content/uploads/2022/09/IMG_7836-scaled.jpg",
        "incluye": [
            "Pastel personalizado con diseño a elección",
            "Docena de cupcakes decorados en temática",
            "Galletas personalizadas con glaseado real",
            "Velas especiales y topper decorativo",
            "Asesoría personalizada en sabores y rellenos",
        ],
        "condiciones": [
            "Reserva con un mínimo de 5 días de anticipación",
            "Anticipo del 50% al confirmar la solicitud",
            "Cancelaciones permitidas hasta 48 horas antes",
        ],
    },
    "bodas": {
        "tipo": "bodas",
        "tipo_label": "Bodas",
        "nombre": "Pastelería para Bodas",
        "titulo": "Bodas de Ensueño",
        "descripcion_corta": "Pasteles de varios pisos de diseño elegante y estaciones de postres finos para el gran día.",
        "descripcion": "El momento más especial de tu vida merece un pastel extraordinario. Diseñamos pasteles nupciales de pisos elegantes con flores naturales o comestibles, macarons finos y estaciones dulces completas.",
        "imagen": "https://i.pinimg.com/originals/81/20/10/812010c47bf072b813c0bab59b86d100.jpg",
        "incluye": [
            "Pastel de bodas de 2 o 3 niveles con acabados finos",
            "Mesa de degustación previa para la pareja",
            "Mesa de mini postres artesanales (macarons, vasitos dulces)",
            "Montaje y entrega puntual en el lugar del evento",
            "Soporte y base para el pastel incluidos en préstamo",
        ],
        "condiciones": [
            "Reserva recomendada con 15 a 30 días de anticipación",
            "Anticipo del 50% para apartar la fecha",
            "Prueba de degustación programada previamente",
        ],
    },
    "graduaciones": {
        "tipo": "graduaciones",
        "tipo_label": "Graduaciones",
        "nombre": "Celebración de Graduación",
        "titulo": "Logros & Graduaciones",
        "descripcion_corta": "Celebra metas alcanzadas con pasteles temáticos de birretes, diplomas y postres de gala.",
        "descripcion": "Celebra la culminación de un gran esfuerzo académico con nuestros paquetes de graduación. Pasteles con detalles de birrete, pergaminos comestibles y bocadillos dulces para compartir con familia y amigos.",
        "imagen": "https://i.pinimg.com/736x/c9/01/b0/c901b0b6f95d5dba9ff31fb0753ce636.jpg",
        "incluye": [
            "Pastel con temática de carrera universitaria o colegio",
            "Birretes y diplomas en fondant comestible",
            "Docena de galletas decoradas alusivas a la graduación",
            "Caja especial para transporte seguro",
            "Topper personalizado con el nombre del graduado",
        ],
        "condiciones": [
            "Reserva con un mínimo de 5 días de anticipación",
            "Anticipo del 50% para confirmación del pedido",
            "Horarios de retiro coordinados según la ceremonia",
        ],
    },
    "baby-shower": {
        "tipo": "baby-shower",
        "tipo_label": "Baby Shower",
        "nombre": "Baby Showers & Revelación",
        "titulo": "Baby Shower & Revelación de Género",
        "descripcion_corta": "Pasteles de revelación con relleno sorpresa, colores pastel y detalles tiernos.",
        "descripcion": "Damos la bienvenida al nuevo integrante de la familia con ternura y dulzura. Especialistas en pasteles de revelación de sexo (gender reveal) con rellenos sorpresa, tonos pasteles y mini postres temáticos.",
        "imagen": "https://i.pinimg.com/736x/5e/c6/a4/5ec6a4ad29c3cf91ff0922369052a1d1.jpg",
        "incluye": [
            "Pastel temático en tonos pastel o efecto sorpresa",
            "Relleno secreto para revelación (azul o rosa)",
            "Cupcakes a juego con decoraciones tiernas",
            "Galletas con figuras de biberones, mamelucos y sonajeros",
            "Asesoría para coordinar con organizadores del evento",
        ],
        "condiciones": [
            "Reserva con un mínimo de 5 días de anticipación",
            "Para revelación: entrega del resultado en sobre cerrado",
            "Anticipo del 50% al momento de apartar fecha",
        ],
    },
    "aniversarios": {
        "tipo": "aniversarios",
        "tipo_label": "Aniversarios",
        "nombre": "Aniversarios Especiales",
        "titulo": "Aniversarios & Fechas Románticas",
        "descripcion_corta": "Pasteles corazón, cajas de postres gourmet y detalles románticos para celebrar el amor.",
        "descripcion": "Celebra otro año juntos con una experiencia dulce inolvidable. Creamos pasteles estilo vintage lambeth en forma de corazón, fresas cubiertas de chocolate belga y postres íntimos para dos o para toda la familia.",
        "imagen": "https://i.pinimg.com/originals/7a/fd/b0/7afdb01b692ad27113fc297aab34477e.jpg",
        "incluye": [
            "Pastel vintage en forma de corazón o diseño romántico",
            "Caja de fresas bañadas en chocolate fino",
            "Mensaje personalizado en glaseado o placa de chocolate",
            "Empaque de lujo listo para regalo",
            "Tarjeta con dedicatoria personalizada",
        ],
        "condiciones": [
            "Reserva con un mínimo de 3 a 5 días de anticipación",
            "Anticipo del 50% requerido",
            "Opción de entrega coordinada sorpresa",
        ],
    },
    "mesa-de-postres": {
        "tipo": "mesa-de-postres",
        "tipo_label": "Mesa de postres",
        "nombre": "Mesa de Postres para Eventos",
        "titulo": "Mesas de Postres & Candy Bar",
        "descripcion_corta": "Montajes elegantes y variados de bocadillos dulces, mini pasteles y postres para tus eventos.",
        "descripcion": "Sorprende a tus invitados con una mesa de postres espectacular diseñada a la medida. Seleccionamos y montamos una variedad de postres miniatura, vasitos gourmet, tartaletas, macarons y pasteles que lucirán increíbles en tu celebración.",
        "imagen": "https://images.unsplash.com/photo-1535141192574-5d4897c13136?auto=format&fit=crop&w=600&q=80",
        "incluye": [
            "Selección de 4 a 6 variedades de postres individuales o miniaturas",
            "Montaje y ambientación temática con bases y vajilla en préstamo",
            "Cartelitos identificadores personalizados con el nombre de cada postre",
            "Opciones sin gluten o reducidas en azúcar bajo solicitud",
            "Asesoría en cálculo de porciones y sabores según cantidad de invitados",
        ],
        "condiciones": [
            "Reservas con mínimo 15 días de anticipación",
            "Anticipo del 50% al momento de apartar fecha",
            "Coordinación de horario de montaje con 3 días de antelación",
        ],
    },
}


@app.route("/eventos")
@cliente_requerido
def eventos():
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    id_cliente = session.get("id_cliente")
    mis_eventos = []
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT s.id_solicitud, s.tipo_evento, s.num_invitados, s.presupuesto_estimado,
                   s.fecha_evento, s.lugar_evento, s.servicios, s.estado, s.fecha_solicitud,
                   ce.id_chat_evento
            FROM SOLICITUD_PLANIFICACION s
            LEFT JOIN CHAT_EVENTO ce ON ce.id_solicitud = s.id_solicitud
            WHERE s.id_cliente = %s
            ORDER BY s.fecha_solicitud DESC, s.id_solicitud DESC
            """,
            (id_cliente,),
        )
        mis_eventos = cursor.fetchall()
    except Exception as err:
        app.logger.warning("No se pudieron cargar los eventos del cliente: %s", err)
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()

    return render_template(
        "eventos.html",
        mis_eventos=mis_eventos,
        csrf_token=session["csrf_token"],
    )


@app.route("/eventos/<int:id_solicitud>/cancelar", methods=["POST"])
@cliente_requerido
def cancelar_evento_cliente(id_solicitud):
    if not _csrf_valido():
        flash("La sesión de seguridad venció. Vuelve a intentarlo.", "error")
        return redirect(url_for("eventos"))

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        conexion.start_transaction()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id_solicitud, estado, tipo_evento
            FROM SOLICITUD_PLANIFICACION
            WHERE id_solicitud = %s AND id_cliente = %s
            FOR UPDATE
            """,
            (id_solicitud, session["id_cliente"]),
        )
        solicitud = cursor.fetchone()
        if not solicitud:
            conexion.rollback()
            abort(404)
        if solicitud["estado"] == "CANCELADA":
            conexion.rollback()
            flash("Esta solicitud de evento ya estaba cancelada.", "info")
            return redirect(url_for("eventos"))

        cursor.execute(
            "UPDATE SOLICITUD_PLANIFICACION SET estado = 'CANCELADA' WHERE id_solicitud = %s",
            (id_solicitud,),
        )
        conexion.commit()
        flash("El evento ha sido cancelado con éxito.", "success")
        return redirect(url_for("eventos"))
    except Exception as err:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al cancelar evento %s: %s", id_solicitud, err)
        flash("No se pudo cancelar el evento. Inténtalo de nuevo.", "error")
        return redirect(url_for("eventos"))
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/eventos/<tipo>")
@cliente_requerido
def evento_detalle(tipo):
    evento = EVENTOS_DISPONIBLES.get(tipo)
    if not evento:
        flash("La categoría de evento seleccionada no existe.", "error")
        return redirect(url_for("eventos"))
    return render_template("evento_detalle.html", evento=evento)


@app.route("/ver-eventos")
@cliente_requerido
def ver_eventos():
    lista_eventos = list(EVENTOS_DISPONIBLES.values())
    return render_template("ver_eventos.html", eventos=lista_eventos)


@app.route("/eventos/planificar", methods=["GET"])
@cliente_requerido
def planifica_evento():
    tipo = request.args.get("tipo", "").strip()
    ev = EVENTOS_DISPONIBLES.get(tipo)
    tipo_nombre = ev["tipo_label"] if ev else (tipo.capitalize() if tipo else "")
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return render_template(
        "planifica_evento.html",
        tipo_preseleccionado=tipo_nombre,
        csrf_token=session["csrf_token"],
    )


@app.route("/eventos/planificar", methods=["POST"])
@cliente_requerido
def planifica_evento_post():
    if not _csrf_valido():
        flash("La sesión de seguridad venció. Vuelve a intentarlo.", "error")
        return redirect(url_for("planifica_evento"))

    tipo_evento = request.form.get("tipo_evento", "").strip()
    fecha_evento = request.form.get("fecha_evento", "").strip()
    num_invitados = request.form.get("num_invitados", "").strip()
    lugar_evento = request.form.get("lugar_evento", "").strip()
    presupuesto = request.form.get("presupuesto", "").strip()
    servicios = request.form.get("servicios", "").strip()

    if not tipo_evento or not fecha_evento or not num_invitados or not lugar_evento or not presupuesto or not servicios:
        flash("Por favor completa todos los campos requeridos para cotizar tu evento.", "error")
        return redirect(url_for("planifica_evento"))

    try:
        invitados_num = int(num_invitados)
        if invitados_num <= 0:
            raise ValueError()
    except ValueError:
        flash("Ingresa un número válido de invitados.", "error")
        return redirect(url_for("planifica_evento"))

    # Limpiar y parsear presupuesto aproximado obligatorio
    presupuesto_limpio = re.sub(r"[^\d.]", "", presupuesto)
    try:
        presupuesto_num = float(presupuesto_limpio)
        if presupuesto_num <= 0:
            raise ValueError()
    except (ValueError, TypeError):
        flash("Ingresa un presupuesto aproximado válido.", "error")
        return redirect(url_for("planifica_evento"))

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor()
        cursor.execute(
            """
            INSERT INTO SOLICITUD_PLANIFICACION
            (id_cliente, tipo_evento, num_invitados, presupuesto_estimado, fecha_evento, lugar_evento, servicios, estado)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'NUEVA')
            """,
            (
                session["id_cliente"],
                tipo_evento,
                invitados_num,
                presupuesto_num,
                fecha_evento,
                lugar_evento,
                servicios or None,
            ),
        )
        conexion.commit()

        app.logger.info(
            "Solicitud de planificación guardada | Cliente ID: %s | Evento: %s | Fecha: %s",
            session.get("id_cliente"),
            tipo_evento,
            fecha_evento,
        )

        flash("¡Se ha enviado tu reserva! Tu solicitud de evento fue recibida con éxito y nuestro equipo la revisará pronto.", "success")
        return redirect(url_for("eventos"))
    except Exception as err:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al registrar solicitud de evento: %s", err)
        flash("Ocurrió un error al enviar tu solicitud. Vuelve a intentarlo.", "error")
        return redirect(url_for("planifica_evento"))
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/admin/dashboard")
@administrador_requerido
def admin_dashboard():
    return render_template(
        "dashboard_admin.html",
        csrf_token=session["csrf_token"],
        admin_email=session.get("admin_email", ""),
    )


@app.route("/admin/productos")
@administrador_requerido
def admin_productos():
    return render_template(
        "admin_agr_producto.html",
        csrf_token=session["csrf_token"],
        admin_email=session.get("admin_email", ""),
    )


@app.route("/admin/reservas")
@administrador_requerido
def admin_reservas():
    return render_template(
        "admin_reservas.html",
        csrf_token=session["csrf_token"],
        admin_email=session.get("admin_email", ""),
    )


@app.route("/admin/ingresos")
@administrador_requerido
def admin_ingresos():
    return render_template(
        "admin_ingresos.html",
        csrf_token=session["csrf_token"],
        admin_email=session.get("admin_email", ""),
    )


@app.route("/admin/reservas/nueva", methods=["GET", "POST"])
@administrador_requerido
def admin_nueva_reserva():
    if request.method == "GET":
        minimo_retiro = datetime.now() + timedelta(days=5)
        fecha_hoy = date.today()
        productos = []
        ultimas_reservas = []
        conexion = None
        cursor = None
        try:
            conexion = obtener_conexion()
            cursor = conexion.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id_producto, nombre, categoria, precio, descripcion, disponible,
                       en_vitrina, se_vende_por_porciones, numero_porciones, precio_porcion,
                       (imagen IS NOT NULL AND tipo_imagen IS NOT NULL) AS tiene_imagen
                FROM PRODUCTO
                WHERE disponible = TRUE
                ORDER BY fecha_creacion DESC, id_producto DESC
                """
            )
            productos = [_producto_publico(reg) for reg in cursor.fetchall()]

            cursor.execute(
                """
                SELECT r.id_reserva, r.codigo, r.nombre_cliente,
                       COALESCE(NULLIF(r.correo, ''), c.correo, '') AS correo, r.telefono,
                       d.nombre_producto, d.cantidad, d.precio_unitario,
                   COALESCE(d.es_porcion, 0) AS es_porcion,
                       r.total, r.anticipo_requerido, r.monto_pagado,
                       r.fecha_retiro, r.estado, p.metodo_pago,
                       p.estado AS pago_estado
                FROM RESERVA r
                LEFT JOIN CLIENTE c ON c.id_cliente = r.id_cliente
                JOIN DETALLE_RESERVA d ON d.id_reserva = r.id_reserva
                LEFT JOIN PAGO p ON p.id_pago = (
                    SELECT MAX(p2.id_pago) FROM PAGO p2
                    WHERE p2.id_reserva = r.id_reserva
                )
                ORDER BY r.id_reserva DESC
                LIMIT 8
                """
            )
            ultimas_reservas = [_normalizar_reserva(row) for row in cursor.fetchall()]
        except Exception as error:
            app.logger.warning("Error al preparar datos de nueva reserva: %s", error)
        finally:
            if cursor:
                cursor.close()
            if conexion and conexion.is_connected():
                conexion.close()

        session.setdefault("csrf_token", secrets.token_urlsafe(32))
        return render_template(
            "admin_nueva_reserva.html",
            csrf_token=session["csrf_token"],
            admin_email=session.get("admin_email", ""),
            productos=productos,
            ultimas_reservas=ultimas_reservas,
            fecha_minima_retiro=minimo_retiro.strftime("%Y-%m-%d"),
            fecha_minima_display=minimo_retiro.strftime("%d/%m/%Y"),
            fecha_hoy=fecha_hoy.strftime("%Y-%m-%d"),
            fecha_hoy_display=fecha_hoy.strftime("%d/%m/%Y"),
            client_catalog_url=url_for("catalogo"),
        )

    # POST: Crear reserva desde panel administrativo
    if not _csrf_valido():
        flash("La sesión de seguridad venció. Vuelve a intentarlo.", "error")
        return redirect(url_for("admin_nueva_reserva"))

    try:
        producto_id = int(request.form.get("producto_id", "0"))
        cantidad = int(request.form.get("cantidad", "1"))
    except (ValueError, TypeError):
        flash("Selecciona un producto y una cantidad válidos.", "error")
        return redirect(url_for("admin_nueva_reserva"))

    tipo_venta = request.form.get("tipo_venta", "completo").strip().lower()
    nombre = request.form.get("nombre", "").strip()
    correo = request.form.get("correo", "").strip().lower()
    telefono = request.form.get("telefono", "").strip()
    fecha_str = request.form.get("fecha", "").strip()
    hora_str = request.form.get("hora", "").strip()

    if not nombre or len(nombre) > 100:
        flash("Ingresa el nombre del cliente para identificar la reserva.", "error")
        return redirect(url_for("admin_nueva_reserva"))
    if correo and ("@" not in correo or len(correo) > 150):
        flash("Si ingresas un correo electrónico, debe tener un formato válido.", "error")
        return redirect(url_for("admin_nueva_reserva"))
    if not telefono or len(telefono) > 30:
        flash("Ingresa un número de teléfono de contacto.", "error")
        return redirect(url_for("admin_nueva_reserva"))
    if cantidad < 1 or cantidad > 30:
        flash("La cantidad debe estar entre 1 y 30 unidades.", "error")
        return redirect(url_for("admin_nueva_reserva"))

    fecha = None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            fecha = datetime.strptime(fecha_str, fmt).date()
            break
        except (ValueError, TypeError):
            pass
    if not fecha:
        flash("Por favor indica una fecha válida para la reserva.", "error")
        return redirect(url_for("admin_nueva_reserva"))

    hora = None
    for fmt in ("%I:%M %p", "%I:%M%p", "%H:%M", "%H:%M:%S"):
        try:
            hora = datetime.strptime(hora_str.strip().upper(), fmt).time()
            break
        except (ValueError, TypeError):
            pass
    if not hora:
        hora = time(15, 0)

    fecha_retiro = datetime.combine(fecha, hora)

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        conexion.start_transaction()
        cursor = conexion.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT id_producto, nombre, categoria, precio,
                   se_vende_por_porciones, numero_porciones, precio_porcion
            FROM PRODUCTO
            WHERE id_producto = %s AND disponible = TRUE
            """,
            (producto_id,),
        )
        producto = cursor.fetchone()
        if not producto:
            conexion.rollback()
            flash("El producto seleccionado no está disponible.", "error")
            return redirect(url_for("admin_nueva_reserva"))

        permite_porciones = bool(producto.get("se_vende_por_porciones") or producto.get("categoria") == "Porciones de Pasteles")
        es_porcion = (tipo_venta == "porciones" and permite_porciones)
        es_bebida = bool(producto.get("categoria") == "Bebidas")
        sin_anticipacion = es_porcion or es_bebida

        # Validación de anticipación de fecha:
        # Porciones de pasteles y bebidas pueden reservarse desde hoy (sin restricción de 5 días)
        # Los demás productos requieren al menos 5 días de anticipación
        if sin_anticipacion:
            if fecha < date.today():
                conexion.rollback()
                flash("La fecha de retiro no puede ser en el pasado.", "error")
                return redirect(url_for("admin_nueva_reserva"))
        else:
            if fecha_retiro < datetime.now() + timedelta(days=5):
                conexion.rollback()
                flash("Las reservas de pasteles completos deben realizarse con al menos 5 días de anticipación.", "error")
                return redirect(url_for("admin_nueva_reserva"))

        if es_porcion:
            max_porciones = int(producto.get("numero_porciones") or 0)
            if max_porciones <= 0:
                conexion.rollback()
                flash("Este pastel ya no tiene porciones disponibles.", "error")
                return redirect(url_for("admin_nueva_reserva"))
            if cantidad > max_porciones:
                conexion.rollback()
                flash(f"Este pastel solo rinde hasta {max_porciones} porciones. Ingresa una cantidad entre 1 y {max_porciones}.", "error")
                return redirect(url_for("admin_nueva_reserva"))
            precio_unitario = Decimal(str(producto.get("precio_porcion") or producto["precio"]))
            nombre_reserva = f"Porciones de Pasteles: {producto['nombre']}"
        else:
            precio_unitario = Decimal(str(producto["precio"]))
            nombre_reserva = producto["nombre"]

        id_cliente = None
        if correo:
            cursor.execute(
                "SELECT id_cliente FROM CLIENTE WHERE correo = %s LIMIT 1",
                (correo,),
            )
            cliente_existente = cursor.fetchone()
            if cliente_existente:
                id_cliente = cliente_existente["id_cliente"]

        total = (precio_unitario * cantidad).quantize(Decimal("0.01"))
        anticipo = (total / 2).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        codigo = f"TB-{secrets.token_hex(4).upper()}"

        cursor.execute(
            """
            INSERT INTO RESERVA
                (codigo, id_cliente, fecha_reserva, fecha_retiro, estado,
                 nombre_cliente, correo, telefono, total, anticipo_requerido, monto_pagado)
            VALUES (%s, %s, %s, %s, 'PENDIENTE_PAGO', %s, %s, %s, %s, %s, 0)
            """,
            (
                codigo,
                id_cliente,
                datetime.now(),
                fecha_retiro,
                nombre,
                correo or None,
                telefono,
                total,
                anticipo,
            ),
        )
        id_reserva = cursor.lastrowid

        cursor.execute(
            """
            INSERT INTO DETALLE_RESERVA
                (id_reserva, id_pastel, nombre_producto, precio_unitario, cantidad, es_porcion, numero_porciones)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                id_reserva,
                producto["id_producto"],
                nombre_reserva,
                precio_unitario,
                cantidad,
                1 if es_porcion else 0,
                cantidad if es_porcion else None,
            ),
        )

        # Reducción del contador de porciones y agotado automático si llega a 0
        if es_porcion:
            nuevo_porciones = max(0, max_porciones - cantidad)
            if nuevo_porciones == 0:
                cursor.execute(
                    "UPDATE PRODUCTO SET numero_porciones = 0, disponible = 0 WHERE id_producto = %s",
                    (producto["id_producto"],),
                )
            else:
                cursor.execute(
                    "UPDATE PRODUCTO SET numero_porciones = %s WHERE id_producto = %s",
                    (nuevo_porciones, producto["id_producto"]),
                )

        cursor.execute(
            """
            INSERT INTO PAGO
                (id_reserva, metodo_pago, monto, estado, referencia)
            VALUES (%s, 'EFECTIVO_TIENDA', %s, 'PENDIENTE', %s)
            """,
            (id_reserva, anticipo, codigo),
        )

        conexion.commit()
        # NOTA IMPORTANTE: Por solicitud explícita del usuario, NO se envía correo de confirmación.
        flash(f"¡Reserva {codigo} registrada exitosamente! Se agregó a reservas registradas.", "success")
        return redirect(url_for("admin_reservas"))
    except mysql.connector.Error as error:
        if conexion:
            conexion.rollback()
        _error_base_datos(error, "No se pudo registrar la reserva.")
        flash("No se pudo registrar la reserva. Inténtalo de nuevo.", "error")
        return redirect(url_for("admin_nueva_reserva"))
    except Exception:
        if conexion:
            conexion.rollback()
        app.logger.exception("No se pudo registrar la reserva administrativa.")
        flash("Ocurrió un error inesperado al registrar la reserva.", "error")
        return redirect(url_for("admin_nueva_reserva"))
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/admin/configuracion")
@administrador_requerido
def admin_configuracion():
    return render_template(
        "admin_configuracion.html",
        csrf_token=session["csrf_token"],
        admin_email=session.get("admin_email", ""),
    )


@app.route("/admin/eventos")
@administrador_requerido
def admin_eventos():
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return render_template(
        "admin_eventos.html",
        csrf_token=session["csrf_token"],
        admin_email=session.get("admin_email", ""),
    )


@app.route("/admin/chat")
@administrador_requerido
def admin_chat():
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return render_template(
        "admin_chat.html",
        csrf_token=session["csrf_token"],
        admin_email=session.get("admin_email", ""),
    )


@app.route("/admin/chat/evento/<int:chat_evento_id>")
@administrador_requerido
def admin_chat_evento(chat_evento_id):
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT ce.id_chat_evento, ce.titulo, ce.id_solicitud, ce.id_cliente,
                   c.nombre AS cliente_nombre, c.correo AS cliente_correo,
                   s.tipo_evento, s.num_invitados, s.presupuesto_estimado,
                   s.fecha_evento, s.lugar_evento, s.servicios
            FROM CHAT_EVENTO ce
            JOIN CLIENTE c ON c.id_cliente = ce.id_cliente
            JOIN SOLICITUD_PLANIFICACION s ON s.id_solicitud = ce.id_solicitud
            WHERE ce.id_chat_evento = %s
            """,
            (chat_evento_id,),
        )
        chat = cursor.fetchone()
        if not chat:
            abort(404)
        session.setdefault("csrf_token", secrets.token_urlsafe(32))
        return render_template(
            "chat_evento.html",
            chat=chat,
            es_admin=True,
            csrf_token=session["csrf_token"],
        )
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/chat")
@cliente_requerido
def chat_general():
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return render_template(
        "chat_cliente.html",
        csrf_token=session["csrf_token"],
        nombre_cliente=session.get("nombre_cliente", ""),
    )


@app.route("/chat/evento/<int:chat_evento_id>")
@cliente_requerido
def cliente_chat_evento(chat_evento_id):
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT ce.id_chat_evento, ce.titulo, ce.id_solicitud, ce.id_cliente,
                   c.nombre AS cliente_nombre, c.correo AS cliente_correo,
                   s.tipo_evento, s.num_invitados, s.presupuesto_estimado,
                   s.fecha_evento, s.lugar_evento, s.servicios
            FROM CHAT_EVENTO ce
            JOIN CLIENTE c ON c.id_cliente = ce.id_cliente
            JOIN SOLICITUD_PLANIFICACION s ON s.id_solicitud = ce.id_solicitud
            WHERE ce.id_chat_evento = %s AND ce.id_cliente = %s
            """,
            (chat_evento_id, session["id_cliente"]),
        )
        chat = cursor.fetchone()
        if not chat:
            abort(404)
        session.setdefault("csrf_token", secrets.token_urlsafe(32))
        return render_template(
            "chat_evento.html",
            chat=chat,
            es_admin=False,
            csrf_token=session["csrf_token"],
        )
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


# Constantes de seguridad para el Panel Administrativo
ADMIN_MAX_INTENTOS = 3
ADMIN_BLOQUEO_SEGUNDOS = 60  # 1 minuto de bloqueo tras 3 intentos fallidos

# Registro en memoria para control de intentos fallidos y bloqueos por IP
_admin_intentos_fallidos = {}  # ip -> {"intentos": int, "bloqueado_hasta": float, "ultimo_intento": float}


def _obtener_ip_cliente():
    """Obtiene la dirección IP real del cliente considerando proxies y cabeceras."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "127.0.0.1"


def _verificar_bloqueo_admin(ip):
    """
    Verifica si la IP o la sesión actual están bloqueadas temporalmente.
    Retorna una tupla (bloqueado: bool, segundos_restantes: int).
    """
    ahora = time_module.time()

    # 1. Comprobar bloqueo a nivel de IP (memoria del servidor)
    registro = _admin_intentos_fallidos.get(ip)
    if registro:
        bloqueado_hasta = registro.get("bloqueado_hasta", 0)
        if bloqueado_hasta > ahora:
            return True, int(bloqueado_hasta - ahora) + 1
        elif bloqueado_hasta > 0:
            # El bloqueo ya expiró: limpiar estado
            _admin_intentos_fallidos.pop(ip, None)
            session.pop("admin_bloqueado_hasta", None)
            session.pop("admin_intentos", None)

    # 2. Comprobar bloqueo a nivel de sesión (capa complementaria)
    bloqueado_sesion = session.get("admin_bloqueado_hasta", 0)
    if bloqueado_sesion > ahora:
        return True, int(bloqueado_sesion - ahora) + 1
    elif bloqueado_sesion > 0:
        session.pop("admin_bloqueado_hasta", None)
        session.pop("admin_intentos", None)

    return False, 0


def _registrar_intento_fallido_admin(ip):
    """
    Registra un intento fallido para la IP y la sesión.
    Si se alcanzan los 3 intentos, impone un bloqueo de 1 minuto.
    Retorna (bloqueado: bool, intentos_restantes: int, segundos_bloqueo: int).
    """
    ahora = time_module.time()
    registro = _admin_intentos_fallidos.setdefault(
        ip, {"intentos": 0, "bloqueado_hasta": 0, "ultimo_intento": ahora}
    )

    # Si han transcurrido más de 10 minutos desde el último intento no bloqueado, reiniciar contador
    if ahora - registro.get("ultimo_intento", ahora) > 600:
        registro["intentos"] = 0
        registro["bloqueado_hasta"] = 0
    registro["ultimo_intento"] = ahora

    # Si había un bloqueo anterior ya vencido, limpiar
    if registro.get("bloqueado_hasta", 0) <= ahora and registro.get("bloqueado_hasta", 0) > 0:
        registro["intentos"] = 0
        registro["bloqueado_hasta"] = 0

    registro["intentos"] += 1
    intentos_ip = registro["intentos"]
    intentos_sesion = session.get("admin_intentos", 0) + 1
    total_intentos = max(intentos_ip, intentos_sesion)
    registro["intentos"] = total_intentos
    session["admin_intentos"] = total_intentos

    if total_intentos >= ADMIN_MAX_INTENTOS:
        bloqueo_hasta = ahora + ADMIN_BLOQUEO_SEGUNDOS
        registro["bloqueado_hasta"] = bloqueo_hasta
        session["admin_bloqueado_hasta"] = bloqueo_hasta
        return True, 0, ADMIN_BLOQUEO_SEGUNDOS
    else:
        restantes = max(0, ADMIN_MAX_INTENTOS - total_intentos)
        return False, restantes, 0


def _limpiar_intentos_admin(ip):
    """Limpia los contadores de intentos fallidos y bloqueos tras un login exitoso."""
    _admin_intentos_fallidos.pop(ip, None)
    session.pop("admin_intentos", None)
    session.pop("admin_bloqueado_hasta", None)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    ip_cliente = _obtener_ip_cliente()

    # Manejo de petición GET
    if request.method == "GET":
        # Redirigir al dashboard únicamente si la sesión de admin ya es activa y válida
        if session.get("es_admin") and session.get("id_admin"):
            try:
                if _administrador_activo(session.get("id_admin")):
                    return redirect(url_for("admin_dashboard"))
                else:
                    session.clear()
            except Exception:
                session.clear()
        elif session.get("es_admin"):
            session.clear()

        # Comprobar si hay un bloqueo activo para la IP
        bloqueado, segs_restantes = _verificar_bloqueo_admin(ip_cliente)
        if bloqueado:
            flash(
                f"Has superado los 3 intentos permitidos. Por seguridad, debes esperar {segs_restantes} segundos antes de volver a intentar.",
                "error",
            )

        if not session.get("csrf_token"):
            session["csrf_token"] = secrets.token_urlsafe(32)

        return render_template(
            "admin_login.html",
            admin_existe=True,
            error_base_datos=False,
            setup_configurado=True,
            csrf_token=session.get("csrf_token"),
            bloqueado=bloqueado,
            segundos_restantes=segs_restantes,
        )

    # Manejo de petición POST
    # 1. Comprobar si se encuentra bajo bloqueo temporal por intentos fallidos
    bloqueado, segs_restantes = _verificar_bloqueo_admin(ip_cliente)
    if bloqueado:
        flash(
            f"Acceso temporalmente bloqueado por seguridad tras 3 intentos fallidos. Por favor espera {segs_restantes} segundos antes de volver a ingresar.",
            "error",
        )
        return render_template(
            "admin_login.html",
            admin_existe=True,
            error_base_datos=False,
            setup_configurado=True,
            csrf_token=session.get("csrf_token"),
            bloqueado=True,
            segundos_restantes=segs_restantes,
        ), 429

    # 2. Validación obligatoria del token CSRF
    token_esperado = session.get("csrf_token", "")
    token_recibido = request.form.get("csrf_token", "") or request.headers.get("X-CSRF-Token", "")
    if not token_esperado or not token_recibido or not hmac.compare_digest(token_esperado, token_recibido):
        session["csrf_token"] = secrets.token_urlsafe(32)
        flash("La sesión de seguridad del formulario ha vencido. Vuelve a intentar.", "error")
        return render_template(
            "admin_login.html",
            admin_existe=True,
            error_base_datos=False,
            setup_configurado=True,
            csrf_token=session.get("csrf_token"),
            bloqueado=False,
            segundos_restantes=0,
        ), 400

    correo = request.form.get("correo", "").strip().lower()
    contrasena = request.form.get("contrasena", "")

    # Validar campos vacíos
    if not correo or not contrasena:
        flash("Ingresa tanto el correo como la contraseña de administrador.", "error")
        return render_template(
            "admin_login.html",
            admin_existe=True,
            error_base_datos=False,
            setup_configurado=True,
            csrf_token=session.get("csrf_token"),
            bloqueado=False,
            segundos_restantes=0,
        ), 400

    # 3. Verificación segura en la base de datos contra la tabla ADMINISTRADOR
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            "SELECT id_admin, nombre, correo, contrasena FROM ADMINISTRADOR WHERE LOWER(correo) = %s",
            (correo,),
        )
        admin = cursor.fetchone()

        # Validación segura mediante hash criptográfico
        clave_valida = False
        if admin and admin.get("contrasena"):
            clave_valida = check_password_hash(admin["contrasena"], contrasena)

        if clave_valida:
            # ÉXITO: Limpiar cualquier intento fallido y desbloquear
            _limpiar_intentos_admin(ip_cliente)

            # Regenerar la sesión para prevenir fijación de sesión (Session Fixation Attack)
            session.clear()
            session["es_admin"] = True
            session["id_admin"] = admin["id_admin"]
            session["admin_email"] = admin["correo"]
            session["csrf_token"] = secrets.token_urlsafe(32)
            session.permanent = True

            # Enviar notificación de seguridad por correo al administrador
            try:
                user_agent = request.headers.get("User-Agent", "Navegador web")
                enviar_correo_inicio_sesion_admin(
                    admin["correo"],
                    admin.get("nombre", "Administrador"),
                    ip=ip_cliente,
                    dispositivo=user_agent,
                )
            except Exception as err_mail:
                app.logger.warning("No se pudo enviar la alerta de inicio de sesión de admin: %s", err_mail)

            flash("Inicio de sesión de administrador exitoso. ¡Bienvenido!", "success")
            return redirect(url_for("admin_dashboard"))
        else:
            # Credenciales incorrectas: registrar intento fallido
            bloqueado_ahora, restantes, segs = _registrar_intento_fallido_admin(ip_cliente)
            if bloqueado_ahora:
                flash(
                    "Has superado los 3 intentos permitidos con datos incorrectos. Tu acceso ha sido bloqueado por 1 minuto para evitar accesos no autorizados.",
                    "error",
                )
                return render_template(
                    "admin_login.html",
                    admin_existe=True,
                    error_base_datos=False,
                    setup_configurado=True,
                    csrf_token=session.get("csrf_token"),
                    bloqueado=True,
                    segundos_restantes=segs,
                ), 429
            else:
                flash(
                    f"Credenciales de administrador incorrectas. Te quedan {restantes} intento{'s' if restantes != 1 else ''} antes de que se bloquee el acceso por 1 minuto.",
                    "error",
                )
                return render_template(
                    "admin_login.html",
                    admin_existe=True,
                    error_base_datos=False,
                    setup_configurado=True,
                    csrf_token=session.get("csrf_token"),
                    bloqueado=False,
                    segundos_restantes=0,
                ), 401

    except Exception as err_login:
        app.logger.exception("Error al autenticar administrador: %s", err_login)
        flash("Ocurrió un error en el servidor al verificar las credenciales. Intenta de nuevo.", "error")
        return render_template(
            "admin_login.html",
            admin_existe=True,
            error_base_datos=True,
            setup_configurado=True,
            csrf_token=session.get("csrf_token"),
            bloqueado=False,
            segundos_restantes=0,
        ), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/admin/cerrar-sesion", methods=["POST"])
@administrador_requerido
def admin_cerrar_sesion():
    session.clear()
    return redirect(url_for("admin_login"))


@app.route("/api/admin/usuario", methods=["DELETE"])
@administrador_requerido
def api_admin_eliminar_usuario():
    # Por políticas de seguridad, la cuenta principal de administración está protegida contra eliminación
    return jsonify({"error": "Por políticas estrictas de seguridad, la cuenta principal de administración está protegida y no puede ser eliminada."}), 403


def _producto_publico(registro, incluir_stock=False):
    tiene_imagen = bool(
        registro.get("tiene_imagen")
        if "tiene_imagen" in registro
        else (registro.get("imagen") and registro.get("tipo_imagen"))
    )
    producto = {
        "id": registro["id_producto"],
        "nombre": registro["nombre"],
        "categoria": registro["categoria"] or "",
        "precio": float(registro["precio"]),
        "descripcion": registro.get("descripcion", ""),
        "disponible": bool(registro.get("disponible", True)),
        "en_vitrina": bool(registro.get("en_vitrina", False)),
        "se_vende_por_porciones": bool(registro.get("se_vende_por_porciones", False)),
        "numero_porciones": int(registro.get("numero_porciones") or 0) if registro.get("se_vende_por_porciones") else None,
        "precio_porcion": float(registro.get("precio_porcion") or 0) if (registro.get("se_vende_por_porciones") and registro.get("precio_porcion") is not None) else None,
        "canjeable_puntos": bool(registro.get("canjeable_puntos", False) or registro.get("es_canjeable", False)),
        "puntos_canje": int(registro.get("puntos_canje") or 50),
        "genera_puntos": bool(registro.get("genera_puntos", True) if registro.get("genera_puntos") is not None else True),
        "tiene_imagen": tiene_imagen,
        "imagen": (
            url_for("imagen_producto", producto_id=registro["id_producto"])
            if tiene_imagen
            else ""
        ),
    }
    if incluir_stock:
        producto["stock"] = int(registro.get("stock", 0))
    return producto


def _obtener_productos(solo_disponibles, incluir_stock=False):
    conexion = obtener_conexion()
    cursor = None
    try:
        cursor = conexion.cursor(dictionary=True)
        consulta = """
            SELECT p.id_producto, p.nombre, p.categoria, p.precio, p.descripcion,
                   p.disponible, p.en_vitrina,
                   COALESCE(p.se_vende_por_porciones, 0) AS se_vende_por_porciones,
                   p.numero_porciones, p.precio_porcion,
                   COALESCE(p.canjeable_puntos, p.es_canjeable, 0) AS canjeable_puntos,
                   COALESCE(p.puntos_canje, 50) AS puntos_canje,
                   COALESCE(p.genera_puntos, 1) AS genera_puntos,
                   COALESCE(i.stock, CASE WHEN p.disponible = TRUE THEN 1 ELSE 0 END) AS stock,
                   (p.imagen IS NOT NULL AND p.tipo_imagen IS NOT NULL) AS tiene_imagen
            FROM PRODUCTO p
            LEFT JOIN INVENTARIO i ON i.id_pastel = p.id_producto
        """
        if solo_disponibles:
            consulta += """
                WHERE p.disponible = TRUE
                  AND COALESCE(i.stock, 1) > 0
                  AND p.categoria IS NOT NULL
                  AND p.imagen IS NOT NULL
                  AND p.tipo_imagen IS NOT NULL
                  AND (p.se_vende_por_porciones = 0 OR p.numero_porciones IS NULL OR p.numero_porciones > 0)
            """
            if request.args.get("vitrina") == "1":
                consulta += " AND p.en_vitrina = TRUE"
        consulta += " ORDER BY p.fecha_creacion DESC, p.id_producto DESC"
        cursor.execute(consulta)
        return [
            _producto_publico(registro, incluir_stock=incluir_stock)
            for registro in cursor.fetchall()
        ]
    finally:
        if cursor:
            cursor.close()
        if conexion.is_connected():
            conexion.close()


def _error_base_datos(error, mensaje):
    app.logger.exception(mensaje)
    if error.errno in {1054, 1146}:
        return jsonify({
            "error": "La base de datos necesita inicializarse o actualizarse. Ejecuta inicializar_bd.py y vuelve a intentar."
        }), 503
    return jsonify({"error": "No se pudo completar la operación. Revisa la conexión a la base de datos e inténtalo otra vez."}), 500


def _validar_producto_formulario():
    nombre = request.form.get("nombre", "").strip()
    categoria = request.form.get("categoria", "").strip()
    descripcion = request.form.get("descripcion", "").strip()
    precio_texto = request.form.get("precio", "").strip()
    disponible_texto = request.form.get("disponible", "true")
    en_vitrina_texto = request.form.get("en_vitrina", "false")
    stock_texto = request.form.get("stock", "").strip()

    if not nombre or len(nombre) > 80:
        raise ValueError("El nombre es obligatorio y admite hasta 80 caracteres.")
    if categoria not in CATEGORIAS_PRODUCTO:
        raise ValueError("Selecciona una categoría válida.")
    if not descripcion or len(descripcion) > 300:
        raise ValueError("La descripción es obligatoria y admite hasta 300 caracteres.")
    if disponible_texto not in {"true", "false"}:
        raise ValueError("Selecciona una disponibilidad válida.")
    if en_vitrina_texto not in {"true", "false"}:
        raise ValueError("Selecciona una opción válida para la vitrina.")
    if not re.fullmatch(r"[0-9]{1,10}", stock_texto):
        raise ValueError("La cantidad disponible debe ser un número entero igual o mayor que cero.")
    stock = int(stock_texto)
    if stock > 2_147_483_647:
        raise ValueError("La cantidad disponible es demasiado grande.")

    canjeable_puntos_texto = request.form.get("canjeable_puntos", "false")
    puntos_canje_texto = request.form.get("puntos_canje", "50").strip()
    genera_puntos_texto = request.form.get("genera_puntos", "true")

    se_vende_por_porciones_texto = request.form.get("se_vende_por_porciones", "false")
    se_vende_por_porciones = se_vende_por_porciones_texto.lower() in ("true", "1", "yes", "on")
    numero_porciones = None
    precio_porcion = None
    if se_vende_por_porciones:
        num_porciones_texto = request.form.get("numero_porciones", "").strip()
        precio_porc_texto = request.form.get("precio_porcion", "").strip()
        if not num_porciones_texto or not re.fullmatch(r"[0-9]{1,4}", num_porciones_texto) or int(num_porciones_texto) < 1:
            raise ValueError("Indica en cuántas porciones se divide el pastel (número entero de al menos 1).")
        numero_porciones = int(num_porciones_texto)
        if not precio_porc_texto:
            raise ValueError("Indica el precio por porción para el pastel.")
        try:
            precio_porcion = Decimal(precio_porc_texto)
            if not precio_porcion.is_finite() or precio_porcion <= 0 or precio_porcion > Decimal("99999.99"):
                raise ValueError()
        except (InvalidOperation, ValueError) as error:
            raise ValueError("El precio por porción debe ser mayor que cero y no superar 99,999.99.") from error

    canjeable_puntos = canjeable_puntos_texto.lower() in ("true", "1", "yes", "on")
    genera_puntos = genera_puntos_texto.lower() in ("true", "1", "yes", "on")
    puntos_canje = 50
    if canjeable_puntos:
        try:
            puntos_canje = int(puntos_canje_texto)
            if puntos_canje < 50:
                raise ValueError("La cantidad mínima permitida para configurar un producto canjeable es de 50 puntos.")
        except (ValueError, TypeError) as error:
            raise ValueError("Los puntos requeridos para canje deben ser al menos 50.") from error

    try:
        precio = Decimal(precio_texto)
    except InvalidOperation as error:
        raise ValueError("Ingresa un precio válido.") from error
    if not precio.is_finite() or precio <= 0 or precio > Decimal("99999.99"):
        raise ValueError("El precio debe ser mayor que cero y no superar 99,999.99.")

    imagen = request.files.get("imagen")
    contenido_imagen = None
    tipo_imagen = None
    if imagen and imagen.filename:
        tipo_imagen = imagen.mimetype
        if tipo_imagen not in TIPOS_IMAGEN:
            raise ValueError("La imagen debe ser JPG, PNG o WEBP.")
        contenido_imagen = imagen.read(1_200_001)
        if not contenido_imagen or len(contenido_imagen) > 1_200_000:
            raise ValueError("La imagen debe pesar como máximo 1.2 MB.")
        if not any(contenido_imagen.startswith(firma) for firma in TIPOS_IMAGEN[tipo_imagen]):
            raise ValueError("El archivo no coincide con el formato de imagen indicado.")
        if tipo_imagen == "image/webp" and contenido_imagen[8:12] != b"WEBP":
            raise ValueError("El archivo no es una imagen WEBP válida.")

    return {
        "nombre": nombre,
        "categoria": categoria,
        "precio": precio,
        "descripcion": descripcion,
        "disponible": disponible_texto == "true",
        "en_vitrina": en_vitrina_texto == "true",
        "se_vende_por_porciones": se_vende_por_porciones,
        "numero_porciones": numero_porciones,
        "precio_porcion": precio_porcion,
        "canjeable_puntos": canjeable_puntos,
        "puntos_canje": puntos_canje,
        "genera_puntos": genera_puntos,
        "stock": stock,
        "imagen": contenido_imagen,
        "tipo_imagen": tipo_imagen,
    }


def _guardar_stock_producto(cursor, producto_id, stock):
    cursor.execute(
        "SELECT id_inventario FROM INVENTARIO WHERE id_pastel = %s",
        (producto_id,),
    )
    inventario = cursor.fetchone()
    if inventario:
        cursor.execute(
            "UPDATE INVENTARIO SET stock = %s WHERE id_pastel = %s",
            (stock, producto_id),
        )
    else:
        cursor.execute(
            "INSERT INTO INVENTARIO (id_pastel, stock) VALUES (%s, %s)",
            (producto_id, stock),
        )


@app.route("/api/productos")
def api_productos():
    try:
        return jsonify(_obtener_productos(solo_disponibles=True))
    except mysql.connector.Error as error:
        return _error_base_datos(error, "No se pudo consultar el catálogo de productos.")
    except Exception:
        app.logger.exception("No se pudo consultar el catálogo de productos.")
        return jsonify({"error": "No se pudo cargar el catálogo. Intenta nuevamente."}), 500


@app.route("/api/productos/<int:producto_id>/imagen")
def imagen_producto(producto_id):
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor()
        cursor.execute(
            "SELECT imagen, tipo_imagen FROM PRODUCTO "
            "WHERE id_producto = %s AND imagen IS NOT NULL AND tipo_imagen IS NOT NULL",
            (producto_id,),
        )
        imagen = cursor.fetchone()
        if not imagen:
            abort(404)
        return send_file(
            BytesIO(imagen[0]),
            mimetype=imagen[1],
            max_age=0,
        )
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


# ==============================================================================
# GESTIÓN DE PERFIL DE USUARIO Y FOTO DE PERFIL (CLIENTE)
# ==============================================================================

@app.route("/cliente/foto-perfil")
def foto_perfil_cliente():
    """Sirve la foto de perfil del cliente autenticado o una imagen por defecto."""
    id_cliente = session.get("id_cliente")
    if not id_cliente:
        return send_from_directory("img", "logo.png")

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            "SELECT foto_perfil, tipo_foto_perfil FROM CLIENTE WHERE id_cliente = %s",
            (id_cliente,),
        )
        fila = cursor.fetchone()
        if fila and fila.get("foto_perfil") and fila.get("tipo_foto_perfil"):
            datos_foto = fila["foto_perfil"]
            if isinstance(datos_foto, str):
                datos_foto = datos_foto.encode("latin1")
            return send_file(
                BytesIO(datos_foto),
                mimetype=fila["tipo_foto_perfil"],
                max_age=0,
            )
    except Exception as err:
        app.logger.warning("No se pudo obtener foto de perfil: %s", err)
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()

    return send_from_directory("img", "logo.png")


@app.route("/api/cliente/foto-perfil", methods=["POST"])
@cliente_requerido
def api_subir_foto_perfil():
    """Actualiza la foto de perfil del cliente con estricta validación de seguridad (<= 20MB, MIME y magic bytes)."""
    if "foto" not in request.files:
        return jsonify({"error": "No se envió ningún archivo de imagen."}), 400

    foto = request.files["foto"]
    if not foto or not foto.filename:
        return jsonify({"error": "Archivo de imagen inválido."}), 400

    # Límite estricto de 20MB (20 * 1024 * 1024 bytes)
    limite_bytes = 20 * 1024 * 1024
    contenido = foto.read(limite_bytes + 1)
    if len(contenido) > limite_bytes:
        return jsonify({"error": "La imagen excede el tamaño máximo permitido de 20 MB."}), 400

    # Validación estricta de MIME type
    mimetype = (foto.mimetype or "").lower()
    if mimetype not in TIPOS_IMAGEN:
        return jsonify({"error": "Formato de imagen no permitido. Solo se admiten JPG, PNG o WEBP."}), 400

    # Validación de magic bytes (firma real del archivo)
    if not any(contenido.startswith(firma) for firma in TIPOS_IMAGEN[mimetype]):
        return jsonify({"error": "El contenido del archivo no corresponde a una imagen válida."}), 400

    if mimetype == "image/webp" and contenido[8:12] != b"WEBP":
        return jsonify({"error": "El archivo no es una imagen WEBP válida."}), 400

    id_cliente = session["id_cliente"]
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor()
        cursor.execute(
            "UPDATE CLIENTE SET foto_perfil = %s, tipo_foto_perfil = %s WHERE id_cliente = %s",
            (contenido, mimetype, id_cliente),
        )
        conexion.commit()
        # Seguridad estricta: responder únicamente con confirmación requerida
        return jsonify({"mensaje": "Foto de perfil actualizada exitosamente.", "ok": True})
    except Exception as err:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al guardar foto de perfil: %s", err)
        return jsonify({"error": "No se pudo actualizar la foto de perfil en el servidor."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


# ==============================================================================
# GESTIÓN DINÁMICA DE IMÁGENES DEL CARRUSEL (HOME)
# ==============================================================================

IMAGENES_CARRUSEL_DEFAULT = [
    {"id": "def-1", "url": "https://images.unsplash.com/photo-1578985545062-69928b1d9587?auto=format&fit=crop&w=1400&q=90"},
    {"id": "def-2", "url": "https://images.unsplash.com/photo-1588195538326-c5b1e9f80a1b?auto=format&fit=crop&w=1400&q=90"},
    {"id": "def-3", "url": "https://images.unsplash.com/photo-1550617931-e17a7b70dce2?auto=format&fit=crop&w=1400&q=90"},
    {"id": "def-4", "url": "https://images.unsplash.com/photo-1563729784474-d77dbb933a9e?auto=format&fit=crop&w=1400&q=90"},
    {"id": "def-5", "url": "https://images.unsplash.com/photo-1535141192574-5d4897c13136?auto=format&fit=crop&w=1400&q=90"},
]


@app.route("/api/home/carrusel", methods=["GET"])
def api_home_carrusel():
    """Devuelve las referencias de imágenes del carrusel home (sin fugas de datos)."""
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute("SELECT id FROM CARRUSEL_HOME ORDER BY orden ASC, id ASC LIMIT 5")
        filas = cursor.fetchall()
        if filas:
            imagenes = [
                {
                    "id": f["id"] if isinstance(f, dict) else f[0],
                    "url": url_for("carrusel_imagen", imagen_id=(f["id"] if isinstance(f, dict) else f[0])),
                }
                for f in filas
            ]
            return jsonify({"imagenes": imagenes})
    except Exception as err:
        app.logger.warning("No se pudieron cargar imágenes personalizadas del carrusel: %s", err)
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()

    # Si no hay imágenes subidas, devolver las 5 imágenes predeterminadas
    return jsonify({"imagenes": IMAGENES_CARRUSEL_DEFAULT})


@app.route("/carrusel-imagen/<int:imagen_id>")
def carrusel_imagen(imagen_id):
    """Transmite el archivo binario de la imagen del carrusel."""
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute("SELECT imagen, tipo_imagen FROM CARRUSEL_HOME WHERE id = %s", (imagen_id,))
        fila = cursor.fetchone()
        if not fila:
            abort(404)
        datos = fila["imagen"]
        if isinstance(datos, str):
            datos = datos.encode("latin1")
        return send_file(BytesIO(datos), mimetype=fila["tipo_imagen"], max_age=86400)
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/admin/home/carrusel", methods=["POST"])
@administrador_requerido
def api_admin_actualizar_carrusel():
    """Permite al administrador subir de 1 a 5 imágenes para el carrusel con validación estricta <= 20MB."""
    if not _csrf_valido():
        return jsonify({"error": "La sesión de seguridad venció. Recarga la página."}), 403

    archivos = request.files.getlist("imagenes")
    # Filtrar archivos vacíos
    archivos_validos = [a for a in archivos if a and a.filename]

    if not archivos_validos:
        return jsonify({"error": "Selecciona al menos una imagen (entre 1 y 5)."}), 400

    if len(archivos_validos) > 5:
        return jsonify({"error": "Solo puedes subir un máximo de 5 imágenes simultáneamente."}), 400

    limite_bytes = 20 * 1024 * 1024
    imagenes_procesadas = []

    for idx, archivo in enumerate(archivos_validos):
        contenido = archivo.read(limite_bytes + 1)
        if len(contenido) > limite_bytes:
            return jsonify({"error": f"La imagen '{archivo.filename}' supera el tamaño máximo permitido de 20 MB."}), 400

        mimetype = (archivo.mimetype or "").lower()
        if mimetype not in TIPOS_IMAGEN:
            return jsonify({"error": f"El archivo '{archivo.filename}' no tiene un formato válido (solo JPG, PNG, WEBP)."}), 400

        if not any(contenido.startswith(firma) for firma in TIPOS_IMAGEN[mimetype]):
            return jsonify({"error": f"El archivo '{archivo.filename}' no coincide con una imagen real."}), 400

        if mimetype == "image/webp" and contenido[8:12] != b"WEBP":
            return jsonify({"error": f"El archivo '{archivo.filename}' no es una imagen WEBP válida."}), 400

        imagenes_procesadas.append((contenido, mimetype, idx))

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor()
        # Reemplazar imágenes existentes de forma dinámica
        cursor.execute("DELETE FROM CARRUSEL_HOME")
        for img_bytes, tipo_img, orden in imagenes_procesadas:
            cursor.execute(
                "INSERT INTO CARRUSEL_HOME (imagen, tipo_imagen, orden) VALUES (%s, %s, %s)",
                (img_bytes, tipo_img, orden),
            )
        conexion.commit()
        return jsonify({
            "mensaje": f"Se guardaron con éxito {len(imagenes_procesadas)} imagen(es) en el carrusel de inicio.",
            "ok": True,
        })
    except Exception as err:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al guardar imágenes del carrusel: %s", err)
        return jsonify({"error": "No se pudieron guardar las imágenes en la base de datos."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/admin/productos", methods=["GET", "POST"])
@administrador_requerido
def api_admin_productos():
    if request.method == "GET":
        try:
            return jsonify(_obtener_productos(solo_disponibles=False, incluir_stock=True))
        except mysql.connector.Error as error:
            return _error_base_datos(error, "No se pudo consultar los productos de administración.")
        except Exception:
            app.logger.exception("No se pudo consultar los productos de administración.")
            return jsonify({"error": "No se pudieron cargar los productos."}), 500

    try:
        producto = _validar_producto_formulario()
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    if not producto["imagen"]:
        return jsonify({"error": "Selecciona una imagen para el producto."}), 400

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor()
        cursor.execute(
            """
            INSERT INTO PRODUCTO
                (nombre, categoria, precio, descripcion, disponible, en_vitrina,
                 se_vende_por_porciones, numero_porciones, precio_porcion,
                 canjeable_puntos, puntos_canje, genera_puntos,
                 imagen, tipo_imagen, id_admin)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                producto["nombre"],
                producto["categoria"],
                producto["precio"],
                producto["descripcion"],
                producto["disponible"],
                producto["en_vitrina"],
                producto["se_vende_por_porciones"],
                producto["numero_porciones"],
                producto["precio_porcion"],
                producto["canjeable_puntos"],
                producto["puntos_canje"],
                producto["genera_puntos"],
                producto["imagen"],
                producto["tipo_imagen"],
                session.get("id_admin"),
            ),
        )
        _guardar_stock_producto(cursor, cursor.lastrowid, producto["stock"])
        conexion.commit()
        return jsonify({"id": cursor.lastrowid, "mensaje": "Producto agregado."}), 201
    except mysql.connector.Error as error:
        if conexion:
            conexion.rollback()
        return _error_base_datos(error, "No se pudo guardar el producto.")
    except Exception:
        if conexion:
            conexion.rollback()
        app.logger.exception("No se pudo guardar el producto.")
        return jsonify({"error": "No se pudo guardar el producto."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/admin/productos/<int:producto_id>", methods=["PUT", "DELETE"])
@administrador_requerido
def api_admin_producto(producto_id):
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            "SELECT imagen, tipo_imagen FROM PRODUCTO WHERE id_producto = %s",
            (producto_id,),
        )
        existente = cursor.fetchone()
        if not existente:
            return jsonify({"error": "El producto ya no existe."}), 404

        if request.method == "DELETE":
            cursor.execute(
                "DELETE FROM PRODUCTO WHERE id_producto = %s",
                (producto_id,),
            )
            conexion.commit()
            return jsonify({"mensaje": "Producto eliminado."})

        try:
            producto = _validar_producto_formulario()
        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        imagen = producto["imagen"] or existente["imagen"]
        tipo_imagen = producto["tipo_imagen"] or existente["tipo_imagen"]
        cursor.execute(
            """
            UPDATE PRODUCTO
            SET nombre = %s, categoria = %s, precio = %s, descripcion = %s,
                disponible = %s, en_vitrina = %s,
                se_vende_por_porciones = %s, numero_porciones = %s, precio_porcion = %s,
                canjeable_puntos = %s, puntos_canje = %s, genera_puntos = %s,
                imagen = %s, tipo_imagen = %s
            WHERE id_producto = %s
            """,
            (
                producto["nombre"],
                producto["categoria"],
                producto["precio"],
                producto["descripcion"],
                producto["disponible"],
                producto["en_vitrina"],
                producto["se_vende_por_porciones"],
                producto["numero_porciones"],
                producto["precio_porcion"],
                producto["canjeable_puntos"],
                producto["puntos_canje"],
                producto["genera_puntos"],
                imagen,
                tipo_imagen,
                producto_id,
            ),
        )
        _guardar_stock_producto(cursor, producto_id, producto["stock"])
        conexion.commit()
        return jsonify({"mensaje": "Producto actualizado."})
    except mysql.connector.Error as error:
        if conexion:
            conexion.rollback()
        if request.method == "DELETE" and (
            error.errno == 1451
            or "FOREIGN KEY constraint failed" in str(error)
        ):
            app.logger.warning(
                "La base de datos aún tiene una referencia de reserva al producto %s; "
                "debe aplicarse la migración de DETALLE_RESERVA.",
                producto_id,
            )
            return jsonify({
                "error": "La base de datos todavía tiene una referencia al producto. Ejecuta python inicializar_bd.py contra esta misma base de datos y vuelve a intentar."
            }), 409
        return _error_base_datos(
            error,
            f"No se pudo completar la operación del producto {producto_id}.",
        )
    except Exception:
        if conexion:
            conexion.rollback()
        app.logger.exception("No se pudo completar la operación del producto %s.", producto_id)
        return jsonify({"error": "No se pudo completar la operación del producto."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/reservar/<int:producto_id>", methods=["GET", "POST"])
@cliente_requerido
def reservar_producto(producto_id):
    if request.method == "GET":
        conexion = None
        cursor = None
        try:
            conexion = obtener_conexion()
            cursor = conexion.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT id_producto, nombre, categoria, precio,
                       se_vende_por_porciones, numero_porciones, precio_porcion
                FROM PRODUCTO
                WHERE id_producto = %s AND disponible = TRUE
                  AND COALESCE(
                      (SELECT stock FROM INVENTARIO
                       WHERE id_pastel = PRODUCTO.id_producto),
                      1
                  ) > 0
                """,
                (producto_id,),
            )
            producto = cursor.fetchone()
        except mysql.connector.Error as error:
            return _error_base_datos(error, "No se pudo comprobar la disponibilidad del producto para reservar.")
        finally:
            if cursor:
                cursor.close()
            if conexion and conexion.is_connected():
                conexion.close()
        if not producto:
            flash("El producto ya no está disponible para reservar.", "error")
            return redirect(url_for("catalogo"))

        es_porcion = bool(producto.get("se_vende_por_porciones") or producto.get("categoria") == "Porciones de Pasteles")
        es_bebida = bool(producto.get("categoria") == "Bebidas")
        sin_anticipacion = es_porcion or es_bebida
        max_porciones = int(producto.get("numero_porciones") or 30) if es_porcion else 30

        session.setdefault("csrf_token", secrets.token_urlsafe(32))
        minimo_retiro = date.today() if sin_anticipacion else (datetime.now() + timedelta(days=5)).date()
        return render_template(
            "reservar_producto.html",
            producto_id=producto_id,
            producto=producto,
            es_porcion=es_porcion,
            es_bebida=es_bebida,
            sin_anticipacion=sin_anticipacion,
            max_porciones=max_porciones,
            nombre_cliente=session.get("nombre_cliente", ""),
            csrf_token=session["csrf_token"],
            wompi_configurada=_wompi_configurada(),
            fecha_minima_retiro=minimo_retiro.isoformat(),
        )

    if not _csrf_valido():
        flash("La sesión de seguridad venció. Vuelve a intentarlo.", "error")
        return redirect(url_for("reservar_producto", producto_id=producto_id))

    nombre = request.form.get("nombre", "").strip()
    telefono = request.form.get("telefono", "").strip()
    metodo_pago = request.form.get("metodo_pago", "")
    acepto_terminos = request.form.get("acepto_terminos_reserva")
    if metodo_pago != "WOMPI" and not acepto_terminos:
        flash("Debes leer y aceptar los Términos y Condiciones, la Política de Privacidad y la Política de Retiro y Reembolsos para continuar.", "error")
        return redirect(url_for("reservar_producto", producto_id=producto_id))

    try:
        cantidad = int(request.form.get("cantidad", ""))
        fecha = date.fromisoformat(request.form.get("fecha", ""))
        hora = time.fromisoformat(request.form.get("hora", ""))
    except (TypeError, ValueError):
        flash("Completa una cantidad, fecha y hora válidas.", "error")
        return redirect(url_for("reservar_producto", producto_id=producto_id))

    if not nombre or len(nombre) > 100 or not telefono or len(telefono) > 30:
        flash("Ingresa tu nombre y teléfono para identificar la reserva.", "error")
        return redirect(url_for("reservar_producto", producto_id=producto_id))
    if cantidad < 1 or cantidad > 30:
        flash("La cantidad debe estar entre 1 y 30.", "error")
        return redirect(url_for("reservar_producto", producto_id=producto_id))
    if metodo_pago not in {"EFECTIVO_TIENDA", "WOMPI"}:
        flash("Selecciona una forma de pago válida.", "error")
        return redirect(url_for("reservar_producto", producto_id=producto_id))
    if metodo_pago == "WOMPI" and not _wompi_configurada():
        flash("El pago con tarjeta por Wompi aún no está configurado para la moneda de esta tienda. Elige efectivo o contacta con TWINS Bakery.", "error")
        return redirect(url_for("reservar_producto", producto_id=producto_id))

    fecha_retiro = datetime.combine(fecha, hora)

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        conexion.start_transaction()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id_producto, nombre, categoria, precio,
                   se_vende_por_porciones, numero_porciones, precio_porcion
            FROM PRODUCTO
            WHERE id_producto = %s AND disponible = TRUE
              AND COALESCE(
                  (SELECT stock FROM INVENTARIO
                   WHERE id_pastel = PRODUCTO.id_producto),
                  1
              ) > 0
            FOR UPDATE
            """,
            (producto_id,),
        )
        producto = cursor.fetchone()
        if not producto:
            conexion.rollback()
            flash("El producto ya no está disponible para reservar.", "error")
            return redirect(url_for("catalogo"))

        es_porcion = bool(producto.get("se_vende_por_porciones") or producto.get("categoria") == "Porciones de Pasteles")
        es_bebida = bool(producto.get("categoria") == "Bebidas")
        sin_anticipacion = es_porcion or es_bebida

        # Validación de anticipación de fecha:
        # Porciones de pasteles y bebidas pueden reservarse desde la fecha actual (hoy)
        # Los demás productos requieren al menos 5 días de anticipación
        if sin_anticipacion:
            if fecha < date.today():
                conexion.rollback()
                flash("La fecha de retiro no puede ser en el pasado.", "error")
                return redirect(url_for("reservar_producto", producto_id=producto_id))
        else:
            if fecha_retiro < datetime.now() + timedelta(days=5):
                conexion.rollback()
                flash("Las reservas deben realizarse con al menos 5 días de anticipación.", "error")
                return redirect(url_for("reservar_producto", producto_id=producto_id))

        if es_porcion and producto.get("precio_porcion"):
            precio_unitario = Decimal(str(producto["precio_porcion"]))
            nombre_reserva = f"Porciones de Pasteles: {producto['nombre']}"
            max_porciones = int(producto.get("numero_porciones") or 0)
            if max_porciones <= 0:
                conexion.rollback()
                flash("Este pastel ya no cuenta con porciones disponibles.", "error")
                return redirect(url_for("catalogo"))
            if cantidad > max_porciones:
                conexion.rollback()
                flash(f"Este pastel solo rinde hasta {max_porciones} porciones. Por favor ingresa una cantidad entre 1 y {max_porciones}.", "error")
                return redirect(url_for("reservar_producto", producto_id=producto_id))
        else:
            precio_unitario = Decimal(str(producto["precio"]))
            nombre_reserva = producto["nombre"]

        total = (precio_unitario * cantidad).quantize(Decimal("0.01"))
        anticipo = (total / 2).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        tipo_cobro_tarjeta = request.form.get("tipo_cobro_tarjeta", "ANTICIPO_50").strip()
        cobro_completo = (metodo_pago == "WOMPI" and tipo_cobro_tarjeta == "TOTAL_100")
        monto_a_cobrar = total if cobro_completo else anticipo

        # Protección contra envío duplicado (doble clic del usuario al pagar con Wompi)
        if metodo_pago == "WOMPI":
            cursor.execute(
                """
                SELECT r.codigo, p.referencia_wompi, p.monto
                FROM RESERVA r
                JOIN DETALLE_RESERVA d ON d.id_reserva = r.id_reserva
                JOIN PAGO p ON p.id_reserva = r.id_reserva
                WHERE r.id_cliente = %s AND d.id_pastel = %s AND d.cantidad = %s
                  AND r.estado = 'PENDIENTE_PAGO' AND p.metodo_pago = 'WOMPI'
                  AND p.estado = 'PENDIENTE'
                  AND p.referencia_wompi IS NOT NULL
                  AND r.fecha_creacion >= %s
                ORDER BY r.id_reserva DESC
                """,
                (session["id_cliente"], producto["id_producto"], cantidad, (datetime.now() - timedelta(seconds=25)).strftime("%Y-%m-%d %H:%M:%S")),
            )
            reserva_dup = cursor.fetchone()
            if reserva_dup and reserva_dup.get("referencia_wompi"):
                ref_w = str(reserva_dup["referencia_wompi"])
                cod_existente = reserva_dup["codigo"]
                session["pago_wompi_pendiente"] = {
                    "referencia_comercio": f"{cod_existente}-WOMPI",
                    "id_enlace": ref_w,
                    "codigo_reserva": cod_existente,
                    "id_cliente": session.get("id_cliente"),
                    "monto_cobro": float(monto_a_cobrar),
                    "es_pago_completo": cobro_completo,
                }
                conexion.commit()
                return redirect(f"https://pagos.wompi.sv/enlace/{ref_w}")

        codigo = f"TB-{secrets.token_hex(4).upper()}"
        referencia_pago = (
            f"{codigo}-{secrets.token_hex(4).upper()}"
            if metodo_pago == "WOMPI"
            else codigo
        )

        id_enlace_wompi = None
        url_enlace_wompi = None

        # Si el método de pago es WOMPI, PRIMERO generamos el enlace de pago con la pasarela.
        # Si la conexión falla o Wompi rechaza los datos, NO se crea ninguna reserva en la BD
        # ni se envía correo, protegiendo al cliente de reservas fantasmas o pagos fallidos.
        if metodo_pago == "WOMPI":
            try:
                enlace = crear_enlace_pago(referencia_pago, monto_a_cobrar, producto["nombre"])
                id_enlace_wompi = str(enlace["idEnlace"])
                url_enlace_wompi = enlace["urlEnlace"]
            except Exception as err_wompi_link:
                if conexion:
                    conexion.rollback()
                app.logger.exception("No se pudo crear el enlace de pago de Wompi: %s", err_wompi_link)
                flash(
                    "No se pudo conectar con la pasarela de pagos Wompi. Por favor verifica tu conexión a internet e inténtalo de nuevo. No se ha generado ninguna reserva ni cobro en tu cuenta.",
                    "error",
                )
                return redirect(url_for("reservar_producto", producto_id=producto_id))

        cursor.execute(
            """
            INSERT INTO RESERVA
                (codigo, id_cliente, fecha_reserva, fecha_retiro, estado,
                 nombre_cliente, telefono, total, anticipo_requerido, monto_pagado)
            VALUES (%s, %s, NOW(), %s, 'PENDIENTE_PAGO', %s, %s, %s, %s, 0)
            """,
            (
                codigo,
                session["id_cliente"],
                fecha_retiro,
                nombre,
                telefono,
                total,
                anticipo,
            ),
        )
        id_reserva = cursor.lastrowid
        cursor.execute(
            """
            INSERT INTO DETALLE_RESERVA
                (id_reserva, id_pastel, nombre_producto, precio_unitario, cantidad, es_porcion, numero_porciones)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                id_reserva,
                producto["id_producto"],
                nombre_reserva,
                precio_unitario,
                cantidad,
                1 if es_porcion else 0,
                producto.get("numero_porciones"),
            ),
        )

        # Reducción de contador de porciones y agotado automático si llega a 0
        if es_porcion:
            nuevo_porciones = max(0, max_porciones - cantidad)
            if nuevo_porciones == 0:
                cursor.execute(
                    "UPDATE PRODUCTO SET numero_porciones = 0, disponible = 0 WHERE id_producto = %s",
                    (producto["id_producto"],),
                )
            else:
                cursor.execute(
                    "UPDATE PRODUCTO SET numero_porciones = %s WHERE id_producto = %s",
                    (nuevo_porciones, producto["id_producto"]),
                )

        cursor.execute(
            """
            INSERT INTO PAGO
                (id_reserva, metodo_pago, monto, estado, referencia, referencia_wompi)
            VALUES (%s, %s, %s, 'PENDIENTE', %s, %s)
            """,
            (id_reserva, metodo_pago, monto_a_cobrar, referencia_pago, id_enlace_wompi),
        )
        conexion.commit()

        # Enviar correo de confirmación de reserva al cliente
        correo_cliente = session.get("correo_cliente")
        if not correo_cliente and session.get("id_cliente"):
            try:
                cursor.execute(
                    "SELECT correo FROM CLIENTE WHERE id_cliente = %s",
                    (session["id_cliente"],),
                )
                fila_c = cursor.fetchone()
                if fila_c:
                    correo_cliente = fila_c["correo"] if isinstance(fila_c, dict) else fila_c[0]
            except Exception:
                pass

        if correo_cliente:
            try:
                enviar_correo_reserva_creada(
                    destinatario=correo_cliente,
                    nombre=nombre,
                    codigo=codigo,
                    nombre_producto=producto["nombre"],
                    categoria=producto.get("categoria", ""),
                    cantidad=cantidad,
                    total=total,
                    anticipo=anticipo,
                    fecha_retiro=fecha_retiro,
                    metodo_pago=metodo_pago,
                )
            except Exception as err_envio:
                app.logger.warning("No se pudo disparar correo de reserva creada: %s", err_envio)

        if metodo_pago == "WOMPI" and url_enlace_wompi:
            session["pago_wompi_pendiente"] = {
                "referencia_comercio": referencia_pago,
                "id_enlace": id_enlace_wompi,
                "codigo_reserva": codigo,
                "id_cliente": session.get("id_cliente"),
                "monto_cobro": float(monto_a_cobrar),
                "es_pago_completo": cobro_completo,
            }
            return redirect(url_enlace_wompi)

        return redirect(url_for("reserva_registrada", codigo=codigo))

    except mysql.connector.Error as error:
        if conexion:
            conexion.rollback()
        _error_base_datos(error, "No se pudo registrar la reserva.")
        flash("No se pudo registrar la reserva. Revisa la conexión e inténtalo otra vez.", "error")
        return redirect(url_for("reservar_producto", producto_id=producto_id))
    except Exception:
        if conexion:
            conexion.rollback()
        app.logger.exception("No se pudo registrar la reserva del producto %s.", producto_id)
        flash("No se pudo registrar la reserva. Inténtalo otra vez.", "error")
        return redirect(url_for("reservar_producto", producto_id=producto_id))
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/reservas")
@cliente_requerido
def mis_reservas():
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT r.codigo, r.fecha_retiro, r.estado, r.total,
                   r.anticipo_requerido, r.monto_pagado, d.nombre_producto,
                   d.cantidad, COALESCE(d.es_porcion, 0) AS es_porcion,
                   d.numero_porciones, p.metodo_pago, p.estado AS pago_estado
            FROM RESERVA r
            JOIN DETALLE_RESERVA d ON d.id_reserva = r.id_reserva
            LEFT JOIN PAGO p ON p.id_pago = (
                SELECT MAX(p2.id_pago) FROM PAGO p2
                WHERE p2.id_reserva = r.id_reserva
            )
            WHERE r.id_cliente = %s
            ORDER BY r.fecha_reserva DESC
            """,
            (session["id_cliente"],),
        )
        reservas = cursor.fetchall()
        return render_template(
            "mis_reservas.html",
            reservas=reservas,
            csrf_token=session["csrf_token"],
        )
    except mysql.connector.Error as error:
        _error_base_datos(error, "No se pudieron consultar las reservas del cliente.")
        flash("No se pudieron cargar tus reservas. Inténtalo otra vez.", "error")
        return render_template(
            "mis_reservas.html",
            reservas=[],
            csrf_token=session["csrf_token"],
        )
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/reservas/<codigo>/cancelar", methods=["POST"])
@cliente_requerido
def cancelar_reserva_cliente(codigo):
    if not _csrf_valido():
        flash("La sesión de seguridad venció. Vuelve a intentarlo.", "error")
        return redirect(url_for("mis_reservas"))

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        conexion.start_transaction()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id_reserva, estado
            FROM RESERVA
            WHERE codigo = %s AND id_cliente = %s
            FOR UPDATE
            """,
            (codigo, session["id_cliente"]),
        )
        reserva = cursor.fetchone()
        if not reserva:
            conexion.rollback()
            abort(404)
        if reserva["estado"] == "ENTREGADA":
            conexion.rollback()
            flash("No se puede cancelar un pedido que ya fue entregado.", "error")
            return redirect(url_for("reserva_registrada", codigo=codigo))
        if reserva["estado"] == "CANCELADA":
            conexion.rollback()
            flash("Esta reserva ya estaba cancelada. Los pagos realizados no son reembolsables.", "error")
            return redirect(url_for("reserva_registrada", codigo=codigo))
        cursor.execute(
            "UPDATE RESERVA SET estado = 'CANCELADA' WHERE id_reserva = %s",
            (reserva["id_reserva"],),
        )
        conexion.commit()
        flash("La reserva fue cancelada. Recuerda que los pagos realizados no son reembolsables.", "success")
        return redirect(url_for("reserva_registrada", codigo=codigo))
    except mysql.connector.Error as error:
        if conexion:
            conexion.rollback()
        return _error_base_datos(error, f"No se pudo cancelar la reserva {codigo}.")
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.post("/reservas/<codigo>/pagar")
@cliente_requerido
def reintentar_pago_wompi(codigo):
    if not _csrf_valido():
        flash("La sesión de seguridad venció. Vuelve a intentarlo.", "error")
        return redirect(url_for("reserva_registrada", codigo=codigo))
    if not _wompi_configurada():
        flash("Wompi no está configurado todavía. Contacta con TWINS Bakery.", "error")
        return redirect(url_for("reserva_registrada", codigo=codigo))

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT r.estado AS reserva_estado, p.id_pago, p.monto, p.referencia,
                   p.estado AS pago_estado, p.metodo_pago, d.nombre_producto
            FROM RESERVA r
            JOIN PAGO p ON p.id_reserva = r.id_reserva
            JOIN DETALLE_RESERVA d ON d.id_reserva = r.id_reserva
            WHERE r.codigo = %s AND r.id_cliente = %s
            ORDER BY p.id_pago DESC
            LIMIT 1
            """,
            (codigo, session["id_cliente"]),
        )
        pago = cursor.fetchone()
        if (
            not pago
            or pago["reserva_estado"] == "CANCELADA"
            or pago["metodo_pago"] != "WOMPI"
            or pago["pago_estado"] != "PENDIENTE"
        ):
            abort(404)
        cursor.close()
        cursor = None
        conexion.close()
        conexion = None

        enlace = crear_enlace_pago(
            pago["referencia"],
            pago["monto"],
            pago["nombre_producto"],
        )
        id_enlace_wompi = str(enlace["idEnlace"])
        conexion = obtener_conexion()
        cursor = conexion.cursor()
        cursor.execute(
            """
            UPDATE PAGO SET referencia_wompi = %s
            WHERE id_pago = %s AND estado = 'PENDIENTE'
            """,
            (id_enlace_wompi, pago["id_pago"]),
        )
        if cursor.rowcount != 1:
            conexion.rollback()
            flash("El pago ya cambió de estado. Revisa tus reservas.", "error")
            return redirect(url_for("reserva_registrada", codigo=codigo))
        conexion.commit()
        # Guardar en sesión para identificar el pago al volver de Wompi
        session["pago_wompi_pendiente"] = {
            "referencia_comercio": pago["referencia"],
            "id_enlace": id_enlace_wompi,
            "codigo_reserva": codigo,
            "id_cliente": session.get("id_cliente"),
        }
        return redirect(enlace["urlEnlace"])
    except (requests.RequestException, ValueError, mysql.connector.Error):
        if conexion:
            conexion.rollback()
        app.logger.exception("No se pudo crear o reintentar un enlace de pago Wompi.")
        flash("No se pudo abrir Wompi. Verifica la conexión y vuelve a intentarlo.", "error")
        return redirect(url_for("reserva_registrada", codigo=codigo))
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/reservas/<codigo>")
@cliente_requerido
def reserva_registrada(codigo):
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT r.codigo, r.nombre_cliente, r.telefono, r.fecha_retiro,
                   r.estado, r.total, r.anticipo_requerido, r.monto_pagado,
                   d.nombre_producto, d.cantidad, COALESCE(d.es_porcion, 0) AS es_porcion,
                   d.numero_porciones, p.metodo_pago,
                   p.estado AS pago_estado
            FROM RESERVA r
            JOIN DETALLE_RESERVA d ON d.id_reserva = r.id_reserva
            LEFT JOIN PAGO p ON p.id_pago = (
                SELECT MAX(p2.id_pago) FROM PAGO p2
                WHERE p2.id_reserva = r.id_reserva
            )
            WHERE r.codigo = %s AND r.id_cliente = %s
            """,
            (codigo, session["id_cliente"]),
        )
        reserva = cursor.fetchone()
        if not reserva:
            abort(404)
        session.setdefault("csrf_token", secrets.token_urlsafe(32))
        return render_template(
            "reserva_registrada.html",
            reserva=reserva,
            csrf_token=session["csrf_token"],
            wompi_configurada=_wompi_configurada(),
        )
    except mysql.connector.Error as error:
        return _error_base_datos(error, "No se pudo consultar la reserva.")
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/pago/wompi/confirmar")
def wompi_confirmar():
    return redirect(url_for("pago_resultado"))


@app.get("/pago/resultado")
def pago_resultado():
    id_transaccion = request.args.get("idTransaccion", "").strip()
    id_enlace = request.args.get("idEnlace", "").strip()
    es_aprobada_raw = request.args.get("esAprobada", "").strip().lower()
    # Si viene esAprobada=true o viene idTransaccion válido (y no viene explícitamente false)
    es_aprobada = es_aprobada_raw in ("true", "1") or (bool(id_transaccion) and es_aprobada_raw != "false")

    pago_pendiente_cliente = session.get("pago_wompi_pendiente") or {}
    ref_enlace = id_enlace or str(pago_pendiente_cliente.get("id_enlace", "")).strip()
    ref_comercio = str(pago_pendiente_cliente.get("referencia_comercio", "")).strip()
    codigo_reserva = str(pago_pendiente_cliente.get("codigo_reserva", "")).strip()

    pago_row = None
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)

        # Buscar el pago correspondiente y los datos de reserva/cliente
        cursor.execute(
            """
            SELECT p.id_pago, p.id_reserva, p.monto, p.estado, p.referencia, p.referencia_wompi,
                   r.codigo, r.total, r.monto_pagado, r.id_cliente, r.nombre_cliente, r.anticipo_requerido,
                   c.id_cliente AS c_id_cliente, c.nombre AS c_nombre, c.correo AS c_correo
            FROM PAGO p
            JOIN RESERVA r ON r.id_reserva = p.id_reserva
            LEFT JOIN CLIENTE c ON c.id_cliente = r.id_cliente
            WHERE p.metodo_pago = 'WOMPI'
              AND (
                   (%s != '' AND p.referencia_wompi = %s)
                OR (%s != '' AND p.referencia = %s)
                OR (%s != '' AND r.codigo = %s)
              )
            ORDER BY p.id_pago DESC
            LIMIT 1
            """,
            (ref_enlace, ref_enlace, ref_comercio, ref_comercio, codigo_reserva, codigo_reserva),
        )
        pago_row = cursor.fetchone()

        if pago_row:
            # 1. Si el pago fue aprobado y estaba pendiente, registrarlo
            if es_aprobada:
                if pago_row.get("estado") != "PAGADO":
                    try:
                        conexion.start_transaction()
                    except Exception:
                        pass
                    monto_cobrado = Decimal(str(pago_row["monto"])).quantize(Decimal("0.01"))
                    pagado_previo = Decimal(str(pago_row["monto_pagado"] or 0)).quantize(Decimal("0.01"))
                    total_res = Decimal(str(pago_row["total"] or 0)).quantize(Decimal("0.01"))
                    nuevo_pagado = min(total_res, (pagado_previo + monto_cobrado).quantize(Decimal("0.01")))

                    cursor.execute(
                        "UPDATE PAGO SET estado = 'PAGADO', fecha_pago = NOW(), referencia_wompi = %s WHERE id_pago = %s",
                        (ref_enlace or pago_row.get("referencia_wompi") or pago_row.get("referencia"), pago_row["id_pago"]),
                    )
                    cursor.execute(
                        "UPDATE RESERVA SET monto_pagado = %s WHERE id_reserva = %s",
                        (nuevo_pagado, pago_row["id_reserva"]),
                    )
                    conexion.commit()

                    # Enviar correo comprobante al cliente
                    correo_cli = pago_row.get("c_correo")
                    if correo_cli:
                        try:
                            saldo_rest = max(Decimal("0.00"), total_res - nuevo_pagado)
                            enviar_correo_pago_tarjeta_recibido(
                                destinatario=correo_cli,
                                nombre=pago_row["c_nombre"] or pago_row["nombre_cliente"],
                                codigo=pago_row["codigo"],
                                monto_pagado=monto_cobrado,
                                referencia_pago=pago_row.get("referencia") or ref_enlace or "",
                                total=total_res,
                                saldo_restante=saldo_rest,
                                nombre_producto=f"Reserva {pago_row['codigo']}",
                            )
                        except Exception as err_m:
                            app.logger.warning("No se pudo enviar comprobante de pago con tarjeta: %s", err_m)

            # 2. Restaurar o confirmar siempre la sesión activa del cliente dueño de la reserva
            id_cli = pago_row.get("c_id_cliente") or pago_row.get("id_cliente")
            if id_cli and _cliente_activo(id_cli):
                session["id_cliente"] = pago_row.get("c_id_cliente") or id_cli
                session["nombre_cliente"] = pago_row.get("c_nombre") or pago_row.get("nombre_cliente")
                session["correo_cliente"] = pago_row.get("c_correo") or ""
                session.permanent = True

            # Limpiar datos temporales de la transacción
            session.pop("pago_wompi_pendiente", None)
            session.pop("intento_reserva", None)

            if es_aprobada:
                monto_pagado_txt = f"${Decimal(str(pago_row['monto'])):.2f}"
                flash(f"¡Pago con tarjeta de {monto_pagado_txt} procesado con éxito! Tu reserva {pago_row['codigo']} está registrada.", "success")
            else:
                flash("La transacción con tarjeta no se completó o fue cancelada en la pasarela.", "info")

            return redirect(url_for("mis_reservas"))

    except Exception as err_pr:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error en /pago/resultado al procesar retorno Wompi: %s", err_pr)
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()

    # Si no se encontró registro de pago específico pero el cliente está autenticado y activo,
    # llevarlo directamente a Mis reservas
    id_cli_actual = session.get("id_cliente")
    if id_cli_actual and _cliente_activo(id_cli_actual):
        return redirect(url_for("mis_reservas"))

    return redirect(url_for("inicio"))


@app.post("/webhook/wompi")
def webhook_wompi():
    if not WOMPI_CLIENT_SECRET:
        return jsonify({"error": "La firma del webhook Wompi no está configurada."}), 503
    cuerpo = request.get_data()
    firma_esperada = hmac.new(
        WOMPI_CLIENT_SECRET.encode("utf-8"),
        cuerpo,
        hashlib.sha256,
    ).hexdigest()
    firma_recibida = request.headers.get("wompi_hash", "")
    if not hmac.compare_digest(firma_esperada, firma_recibida.lower()):
        return jsonify({"error": "Firma inválida."}), 401

    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return jsonify({"error": "El evento recibido no es JSON válido."}), 400
    if datos.get("ResultadoTransaccion") != "ExitosaAprobada":
        return "", 200
    if not _marcar_pago_aprobado(datos):
        return jsonify({"error": "No se encontró un pago pendiente con el mismo monto."}), 400
    return "", 200


@app.route("/api/admin/dashboard", methods=["GET"])
@administrador_requerido
def api_admin_dashboard():
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)

        # Contadores por estado
        cursor.execute("""
            SELECT estado, COUNT(*) AS total
            FROM RESERVA
            GROUP BY estado
        """)
        estados = {row["estado"]: row["total"] for row in cursor.fetchall()}

        # Total de reservas registradas en la tienda
        cursor.execute("SELECT COUNT(*) AS total FROM RESERVA")
        row_total = cursor.fetchone()
        total_reservas = row_total["total"] if row_total else 0

        # Reservas registradas en la fecha de hoy (utilizando fecha local del servidor)
        hoy_str = date.today().isoformat()
        cursor.execute("SELECT COUNT(*) AS total FROM RESERVA WHERE DATE(fecha_reserva) = %s", (hoy_str,))
        row_hoy = cursor.fetchone()
        reservas_hoy = row_hoy["total"] if row_hoy else 0

        # Productos activos
        cursor.execute("SELECT COUNT(*) AS total FROM PRODUCTO WHERE disponible = TRUE")
        row_prod = cursor.fetchone()
        productos_activos = row_prod["total"] if row_prod else 0

        # Reservas de los últimos 7 días (para la gráfica de barras)
        hace_6_dias_str = (date.today() - timedelta(days=6)).isoformat()
        cursor.execute("""
            SELECT DATE(fecha_reserva) AS dia, COUNT(*) AS total
            FROM RESERVA
            WHERE DATE(fecha_reserva) >= %s AND DATE(fecha_reserva) <= %s
            GROUP BY DATE(fecha_reserva)
            ORDER BY dia ASC
        """, (hace_6_dias_str, hoy_str))
        reservas_semana = [
            {"dia": str(row["dia"]), "total": row["total"]}
            for row in cursor.fetchall()
        ]

        return jsonify({
            "total_reservas": total_reservas,
            "reservas_hoy": reservas_hoy,
            "pendientes": estados.get("PENDIENTE_PAGO", 0),
            "confirmadas": estados.get("CONFIRMADA", 0),
            "en_preparacion": estados.get("EN_PREPARACION", 0),
            "listas": estados.get("LISTA", 0),
            "entregadas": estados.get("ENTREGADA", 0),
            "canceladas": estados.get("CANCELADA", 0),
            "productos_activos": productos_activos,
            "reservas_semana": reservas_semana,
        })
    except mysql.connector.Error as error:
        return _error_base_datos(error, "No se pudieron cargar las métricas del dashboard.")
    except Exception:
        app.logger.exception("No se pudieron cargar las métricas del dashboard.")
        return jsonify({"error": "No se pudieron cargar las métricas."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()



@app.route("/api/admin/ingresos", methods=["GET"])
@administrador_requerido
def api_admin_ingresos():
    periodo = request.args.get("periodo", "semana").lower().strip()
    if periodo not in {"hoy", "semana", "mes", "todo"}:
        periodo = "semana"

    hoy = date.today()
    inicio_hoy = datetime.combine(hoy, datetime.min.time())
    inicio_semana = datetime.combine(hoy - timedelta(days=6), datetime.min.time())
    inicio_mes = datetime.combine(hoy.replace(day=1), datetime.min.time())

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT p.id_pago, p.id_reserva, p.monto, p.metodo_pago,
                   COALESCE(p.fecha_pago, p.fecha_creacion) AS fecha,
                   r.codigo, r.nombre_cliente, r.estado AS estado_reserva,
                   r.total, r.anticipo_requerido, r.monto_pagado,
                   p.referencia
            FROM PAGO p
            JOIN RESERVA r ON r.id_reserva = p.id_reserva
            WHERE p.estado = 'PAGADO' AND p.monto > 0
            ORDER BY fecha DESC, p.id_pago DESC
            """
        )
        pagos_raw = cursor.fetchall()

        cursor.execute(
            """
            SELECT id_movimiento, tipo, monto, concepto, categoria, metodo_pago, fecha, notas, id_reserva, id_admin
            FROM MOVIMIENTO_FINANCIERO
            ORDER BY fecha DESC, id_movimiento DESC
            """
        )
        manuales_raw = cursor.fetchall()

        # Identificar reservas cuyo anticipo retenido ya fue entregado/devuelto al cliente
        reservas_anticipo_devuelto = set()
        for m in manuales_raw:
            if m["tipo"] == "RESTA" and m.get("id_reserva"):
                reservas_anticipo_devuelto.add(m["id_reserva"])

        transacciones_todas = []

        for p in pagos_raw:
            monto = float(p["monto"])
            total_res = float(p["total"] or 0)
            anticipo_req = float(p["anticipo_requerido"] or 0)
            estado_res = p["estado_reserva"]
            id_res = p["id_reserva"]

            puede_entregar = False
            ya_devuelto = id_res in reservas_anticipo_devuelto

            if estado_res == "CANCELADA":
                subtipo = "ANTICIPO_RETENIDO"
                if ya_devuelto:
                    etiqueta = "Anticipo retenido (Ya entregado)"
                    categoria = "RESERVA_CANCELADA_DEVUELTA"
                else:
                    etiqueta = "Anticipo retenido (Cancelada)"
                    categoria = "RESERVA_CANCELADA"
                    puede_entregar = True
            elif monto >= total_res and total_res > 0:
                subtipo = "PAGO_COMPLETO"
                etiqueta = "Pago completo (100%)"
                categoria = "RESERVA_COMPLETA"
            elif abs(monto - anticipo_req) < 0.05:
                subtipo = "ANTICIPO"
                etiqueta = "Anticipo (50%)"
                categoria = "ANTICIPO_RESERVA"
            else:
                subtipo = "LIQUIDACION"
                etiqueta = "Liquidación de saldo"
                categoria = "LIQUIDACION_RESERVA"

            f = p["fecha"]
            if isinstance(f, str):
                try:
                    dt = datetime.fromisoformat(f.replace("Z", ""))
                except Exception:
                    dt = datetime.strptime(f[:19], "%Y-%m-%d %H:%M:%S")
            else:
                dt = f

            transacciones_todas.append({
                "id": f"PAGO-{p['id_pago']}",
                "origen": "RESERVA",
                "id_pago": p["id_pago"],
                "id_movimiento": None,
                "id_reserva": id_res,
                "codigo_reserva": p["codigo"],
                "cliente": p["nombre_cliente"] or "Cliente",
                "concepto": f"Reserva {p['codigo']} ({etiqueta})",
                "tipo": "INGRESO",
                "subtipo": subtipo,
                "subtipo_etiqueta": etiqueta,
                "categoria": categoria,
                "metodo_pago": p["metodo_pago"] or "TARJETA",
                "fecha_dt": dt,
                "fecha": dt.strftime("%Y-%m-%d %H:%M"),
                "fecha_corta": dt.strftime("%d/%m/%Y"),
                "monto": round(monto, 2),
                "es_editable": False,
                "puede_entregar_anticipo": puede_entregar,
                "anticipo_devuelto": ya_devuelto,
                "notas": f"Total reserva: ${total_res:.2f}",
            })

        for m in manuales_raw:
            monto = float(m["monto"])
            f = m["fecha"]
            if isinstance(f, str):
                try:
                    dt = datetime.fromisoformat(f.replace("Z", ""))
                except Exception:
                    dt = datetime.strptime(f[:19], "%Y-%m-%d %H:%M:%S")
            else:
                dt = f

            cat = m["categoria"] or ("VENTA_DIRECTA" if m["tipo"] == "INGRESO" else "GASTO")
            etiqueta = "Ingreso manual" if m["tipo"] == "INGRESO" else "Resta / Egreso"

            transacciones_todas.append({
                "id": f"MANUAL-{m['id_movimiento']}",
                "origen": "MANUAL",
                "id_pago": None,
                "id_movimiento": m["id_movimiento"],
                "id_reserva": m["id_reserva"],
                "codigo_reserva": None,
                "cliente": "Administración",
                "concepto": m["concepto"],
                "tipo": m["tipo"],
                "subtipo": cat,
                "subtipo_etiqueta": etiqueta,
                "categoria": cat,
                "metodo_pago": m["metodo_pago"] or "EFECTIVO",
                "fecha_dt": dt,
                "fecha": dt.strftime("%Y-%m-%d %H:%M"),
                "fecha_corta": dt.strftime("%d/%m/%Y"),
                "monto": round(monto, 2),
                "es_editable": True,
                "notas": m["notas"] or "",
            })

        transacciones_todas.sort(key=lambda x: x["fecha_dt"], reverse=True)

        def calc_neto(items):
            ing = sum(x["monto"] for x in items if x["tipo"] == "INGRESO")
            res = sum(x["monto"] for x in items if x["tipo"] == "RESTA")
            return round(ing - res, 2)

        metricas_fijas = {
            "hoy": calc_neto([t for t in transacciones_todas if t["fecha_dt"] >= inicio_hoy]),
            "semana": calc_neto([t for t in transacciones_todas if t["fecha_dt"] >= inicio_semana]),
            "mes": calc_neto([t for t in transacciones_todas if t["fecha_dt"] >= inicio_mes]),
            "total_historico": calc_neto(transacciones_todas),
        }

        if periodo == "hoy":
            filtradas = [t for t in transacciones_todas if t["fecha_dt"] >= inicio_hoy]
        elif periodo == "semana":
            filtradas = [t for t in transacciones_todas if t["fecha_dt"] >= inicio_semana]
        elif periodo == "mes":
            filtradas = [t for t in transacciones_todas if t["fecha_dt"] >= inicio_mes]
        else:
            filtradas = transacciones_todas

        ingresos_res = sum(t["monto"] for t in filtradas if t["tipo"] == "INGRESO" and t["origen"] == "RESERVA")
        ingresos_man = sum(t["monto"] for t in filtradas if t["tipo"] == "INGRESO" and t["origen"] == "MANUAL")
        restas_egresos = sum(t["monto"] for t in filtradas if t["tipo"] == "RESTA")
        ingreso_bruto = round(ingresos_res + ingresos_man, 2)
        ingreso_neto = round(ingreso_bruto - restas_egresos, 2)

        anticipos_m = round(sum(t["monto"] for t in filtradas if t["subtipo"] == "ANTICIPO"), 2)
        anticipos_c = sum(1 for t in filtradas if t["subtipo"] == "ANTICIPO")
        liquidaciones_m = round(sum(t["monto"] for t in filtradas if t["subtipo"] == "LIQUIDACION"), 2)
        liquidaciones_c = sum(1 for t in filtradas if t["subtipo"] == "LIQUIDACION")
        completos_m = round(sum(t["monto"] for t in filtradas if t["subtipo"] == "PAGO_COMPLETO"), 2)
        completos_c = sum(1 for t in filtradas if t["subtipo"] == "PAGO_COMPLETO")
        canceladas_m = round(sum(t["monto"] for t in filtradas if t["subtipo"] == "ANTICIPO_RETENIDO"), 2)
        canceladas_c = sum(1 for t in filtradas if t["subtipo"] == "ANTICIPO_RETENIDO")

        reservas_ids = set(t["id_reserva"] for t in filtradas if t["origen"] == "RESERVA" and t["id_reserva"])
        total_pedidos = len(reservas_ids)
        ticket_medio = round(ingresos_res / total_pedidos, 2) if total_pedidos > 0 else 0.0

        nombres_dias = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
        nombres_meses = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
        puntos_grafica = []

        if periodo == "hoy":
            franjas = [
                (8, 10, "08:00 - 10:00"),
                (10, 12, "10:00 - 12:00"),
                (12, 14, "12:00 - 14:00"),
                (14, 16, "14:00 - 16:00"),
                (16, 18, "16:00 - 18:00"),
                (18, 20, "18:00 - 20:00"),
                (20, 24, "20:00+"),
            ]
            for h_ini, h_fin, label in franjas:
                items_f = [t for t in filtradas if h_ini <= t["fecha_dt"].hour < h_fin]
                ing = sum(t["monto"] for t in items_f if t["tipo"] == "INGRESO")
                res = sum(t["monto"] for t in items_f if t["tipo"] == "RESTA")
                puntos_grafica.append({
                    "label": label,
                    "ingreso": round(ing, 2),
                    "resta": round(res, 2),
                    "neto": round(ing - res, 2),
                    "conteo": len(items_f),
                })
        elif periodo == "semana":
            for offset in range(6, -1, -1):
                dia_target = hoy - timedelta(days=offset)
                items_d = [t for t in transacciones_todas if t["fecha_dt"].date() == dia_target]
                ing = sum(t["monto"] for t in items_d if t["tipo"] == "INGRESO")
                res = sum(t["monto"] for t in items_d if t["tipo"] == "RESTA")
                label = f"{nombres_dias[dia_target.weekday()]} {dia_target.day}"
                puntos_grafica.append({
                    "label": label,
                    "ingreso": round(ing, 2),
                    "resta": round(res, 2),
                    "neto": round(ing - res, 2),
                    "conteo": len(items_d),
                })
        elif periodo == "mes":
            dia_1 = hoy.replace(day=1)
            semanas = [
                (dia_1, dia_1 + timedelta(days=6), "Semana 1"),
                (dia_1 + timedelta(days=7), dia_1 + timedelta(days=13), "Semana 2"),
                (dia_1 + timedelta(days=14), dia_1 + timedelta(days=20), "Semana 3"),
                (dia_1 + timedelta(days=21), hoy + timedelta(days=10), "Semana 4+"),
            ]
            for f_ini, f_fin, label in semanas:
                items_s = [t for t in filtradas if f_ini <= t["fecha_dt"].date() <= f_fin]
                ing = sum(t["monto"] for t in items_s if t["tipo"] == "INGRESO")
                res = sum(t["monto"] for t in items_s if t["tipo"] == "RESTA")
                puntos_grafica.append({
                    "label": label,
                    "ingreso": round(ing, 2),
                    "resta": round(res, 2),
                    "neto": round(ing - res, 2),
                    "conteo": len(items_s),
                })
        else:
            for m_back in range(5, -1, -1):
                year = hoy.year
                month = hoy.month - m_back
                while month <= 0:
                    month += 12
                    year -= 1
                items_m = [t for t in transacciones_todas if t["fecha_dt"].year == year and t["fecha_dt"].month == month]
                ing = sum(t["monto"] for t in items_m if t["tipo"] == "INGRESO")
                res = sum(t["monto"] for t in items_m if t["tipo"] == "RESTA")
                puntos_grafica.append({
                    "label": f"{nombres_meses[month - 1]} {year}",
                    "ingreso": round(ing, 2),
                    "resta": round(res, 2),
                    "neto": round(ing - res, 2),
                    "conteo": len(items_m),
                })

        for t in filtradas:
            t.pop("fecha_dt", None)

        return jsonify({
            "periodo": periodo,
            "metricas_fijas": metricas_fijas,
            "resumen_periodo": {
                "ingreso_neto": ingreso_neto,
                "ingreso_bruto": ingreso_bruto,
                "ingresos_reservas": round(ingresos_res, 2),
                "ingresos_manuales": round(ingresos_man, 2),
                "restas_egresos": round(restas_egresos, 2),
                "total_pedidos": total_pedidos,
                "ticket_medio": ticket_medio,
                "anticipos_monto": anticipos_m,
                "anticipos_conteo": anticipos_c,
                "liquidaciones_monto": liquidaciones_m,
                "liquidaciones_conteo": liquidaciones_c,
                "pagos_completos_monto": completos_m,
                "pagos_completos_conteo": completos_c,
                "canceladas_monto": canceladas_m,
                "canceladas_conteo": canceladas_c,
                "total_transacciones": len(filtradas),
            },
            "grafica": puntos_grafica,
            "transacciones": filtradas,
        })
    except mysql.connector.Error as error:
        return _error_base_datos(error, "No se pudieron consultar los datos financieros.")
    except Exception:
        app.logger.exception("Error al procesar ingresos financieros.")
        return jsonify({"error": "No se pudieron consultar los ingresos."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/admin/ingresos/movimiento", methods=["POST"])
@administrador_requerido
def api_admin_crear_movimiento():
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return jsonify({"error": "Los datos enviados no son válidos."}), 400

    tipo = str(datos.get("tipo", "")).strip().upper()
    if tipo not in {"INGRESO", "RESTA"}:
        return jsonify({"error": "El tipo de movimiento debe ser 'INGRESO' o 'RESTA'."}), 400

    try:
        monto = float(datos.get("monto", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "El monto debe ser un número válido."}), 400

    if monto <= 0 or monto > 100000:
        return jsonify({"error": "El monto debe ser mayor a 0 y menor a $100,000."}), 400

    concepto = str(datos.get("concepto", "")).strip()
    if len(concepto) < 3 or len(concepto) > 200:
        return jsonify({"error": "El concepto debe tener entre 3 y 200 caracteres."}), 400

    categoria = str(datos.get("categoria", "OTRO")).strip().upper()
    metodos_validos = {"EFECTIVO", "TARJETA", "TRANSFERENCIA", "OTRO"}
    metodo_pago = str(datos.get("metodo_pago", "EFECTIVO")).strip().upper()
    if metodo_pago not in metodos_validos:
        metodo_pago = "EFECTIVO"

    notas = str(datos.get("notas", "")).strip()
    if len(notas) > 300:
        notas = notas[:300]

    fecha_str = datos.get("fecha")
    fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if fecha_str:
        try:
            fecha_dt = datetime.fromisoformat(str(fecha_str).strip())
            fecha_actual = fecha_dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass

    admin_id = session.get("id_admin")

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor()
        cursor.execute(
            """
            INSERT INTO MOVIMIENTO_FINANCIERO (tipo, monto, concepto, categoria, metodo_pago, fecha, id_admin, notas)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (tipo, monto, concepto, categoria, metodo_pago, fecha_actual, admin_id, notas),
        )
        conexion.commit()
        id_nuevo = cursor.lastrowid
        return jsonify({
            "mensaje": f"{'Ingreso' if tipo == 'INGRESO' else 'Resta'} registrado con éxito.",
            "id_movimiento": id_nuevo
        }), 201
    except mysql.connector.Error as error:
        if conexion:
            conexion.rollback()
        return _error_base_datos(error, "No se pudo registrar el movimiento financiero.")
    except Exception:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al registrar movimiento financiero.")
        return jsonify({"error": "No se pudo guardar el movimiento."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/admin/ingresos/movimiento/<int:id_movimiento>", methods=["DELETE"])
@administrador_requerido
def api_admin_eliminar_movimiento(id_movimiento):
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            "SELECT id_movimiento, tipo, concepto, monto FROM MOVIMIENTO_FINANCIERO WHERE id_movimiento = %s",
            (id_movimiento,)
        )
        mov = cursor.fetchone()
        if not mov:
            return jsonify({"error": "El movimiento no existe o ya fue eliminado."}), 404

        cursor.execute("DELETE FROM MOVIMIENTO_FINANCIERO WHERE id_movimiento = %s", (id_movimiento,))
        conexion.commit()
        return jsonify({
            "mensaje": f"Movimiento '{mov['concepto']}' (${float(mov['monto']):.2f}) eliminado exitosamente."
        })
    except mysql.connector.Error as error:
        if conexion:
            conexion.rollback()
        return _error_base_datos(error, "No se pudo eliminar el movimiento.")
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()



@app.route("/api/admin/ingresos/entregar-anticipo-retenido", methods=["POST"])
@administrador_requerido
def api_admin_entregar_anticipo_retenido():
    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return jsonify({"error": "Los datos enviados no son válidos."}), 400

    id_reserva = datos.get("id_reserva")
    try:
        id_reserva = int(id_reserva)
    except (TypeError, ValueError):
        return jsonify({"error": "El ID de reserva no es válido."}), 400

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)

        # 1. Verificar reserva cancelada con pago pagado
        cursor.execute(
            """
            SELECT r.id_reserva, r.codigo, r.nombre_cliente, r.estado,
                   p.id_pago, p.monto, p.metodo_pago
            FROM RESERVA r
            JOIN PAGO p ON p.id_reserva = r.id_reserva
            WHERE r.id_reserva = %s AND r.estado = 'CANCELADA' AND p.estado = 'PAGADO' AND p.monto > 0
            ORDER BY p.id_pago DESC
            LIMIT 1
            """,
            (id_reserva,),
        )
        reserva = cursor.fetchone()
        if not reserva:
            return jsonify({"error": "No se encontró un anticipo retenido pagado para esta reserva."}), 404

        # 2. Verificar que no se haya devuelto ya
        cursor.execute(
            """
            SELECT id_movimiento FROM MOVIMIENTO_FINANCIERO
            WHERE id_reserva = %s AND tipo = 'RESTA'
            LIMIT 1
            """,
            (id_reserva,),
        )
        if cursor.fetchone():
            return jsonify({"error": "El anticipo retenido de esta reserva ya fue registrado como entregado previamente."}), 400

        monto_devolver = float(reserva["monto"])
        concepto = f"Anticipo retenido entregado - Reserva {reserva['codigo']} ({reserva['nombre_cliente']})"
        categoria = "DEVOLUCION_ANTICIPO"
        metodo = reserva["metodo_pago"] or "EFECTIVO"
        fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        admin_id = session.get("id_admin")
        notas = "Anticipo retenido devuelto / entregado al cliente por la administración."

        cursor.execute(
            """
            INSERT INTO MOVIMIENTO_FINANCIERO (tipo, monto, concepto, categoria, metodo_pago, fecha, id_reserva, id_admin, notas)
            VALUES ('RESTA', %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (monto_devolver, concepto, categoria, metodo, fecha_actual, id_reserva, admin_id, notas),
        )
        conexion.commit()
        id_nuevo = cursor.lastrowid

        return jsonify({
            "mensaje": f"Se registró la entrega del anticipo retenido de ${monto_devolver:.2f} (Reserva {reserva['codigo']}). El valor se restó del sistema.",
            "id_movimiento": id_nuevo,
            "monto": monto_devolver
        }), 201
    except mysql.connector.Error as error:
        if conexion:
            conexion.rollback()
        return _error_base_datos(error, "No se pudo registrar la entrega del anticipo.")
    except Exception:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al registrar entrega de anticipo retenido.")
        return jsonify({"error": "Ocurrió un error al procesar la entrega del anticipo."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/admin/reservas", methods=["GET"])
@administrador_requerido
def api_admin_reservas():
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT r.id_reserva, r.codigo, r.nombre_cliente,
                   COALESCE(NULLIF(r.correo, ''), c.correo, '') AS correo, r.telefono,
                   d.nombre_producto, d.cantidad, d.precio_unitario,
                   COALESCE(d.es_porcion, 0) AS es_porcion,
                   r.total, r.anticipo_requerido, r.monto_pagado,
                   r.fecha_retiro, r.estado, p.metodo_pago,
                   p.estado AS pago_estado,
                   COALESCE(r.es_canje_fidelidad, 0) AS es_canje_fidelidad,
                   COALESCE(r.puntos_usados, 0) AS puntos_usados
            FROM RESERVA r
            LEFT JOIN CLIENTE c ON c.id_cliente = r.id_cliente
            JOIN DETALLE_RESERVA d ON d.id_reserva = r.id_reserva
            LEFT JOIN PAGO p ON p.id_pago = (
                SELECT MAX(p2.id_pago) FROM PAGO p2
                WHERE p2.id_reserva = r.id_reserva
            )
            ORDER BY r.id_reserva DESC
            """
        )
        return jsonify([_normalizar_reserva(row) for row in cursor.fetchall()])
    except mysql.connector.Error as error:
        return _error_base_datos(error, "No se pudieron consultar las reservas del administrador.")
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/admin/reservas/<int:reserva_id>", methods=["PATCH", "DELETE"])
@administrador_requerido
def api_admin_reserva(reserva_id):
    if request.method == "DELETE":
        conexion = None
        cursor = None
        try:
            conexion = obtener_conexion()
            conexion.start_transaction()
            cursor = conexion.cursor(dictionary=True)
            cursor.execute(
                "SELECT id_reserva, codigo FROM RESERVA WHERE id_reserva = %s FOR UPDATE",
                (reserva_id,),
            )
            reserva = cursor.fetchone()
            if not reserva:
                conexion.rollback()
                return jsonify({"error": "La reserva ya no existe."}), 404

            # Eliminar registros relacionados para garantizar integridad referencial
            cursor.execute("DELETE FROM PAGO WHERE id_reserva = %s", (reserva_id,))
            cursor.execute("DELETE FROM DETALLE_RESERVA WHERE id_reserva = %s", (reserva_id,))
            cursor.execute("DELETE FROM RESERVA WHERE id_reserva = %s", (reserva_id,))
            conexion.commit()
            return jsonify({"mensaje": f"Reserva {reserva['codigo']} eliminada exitosamente."})
        except mysql.connector.Error as error:
            if conexion:
                conexion.rollback()
            return _error_base_datos(error, "No se pudo eliminar la reserva.")
        finally:
            if cursor:
                cursor.close()
            if conexion and conexion.is_connected():
                conexion.close()

    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return jsonify({"error": "Los datos enviados no tienen un formato válido."}), 400
    if not set(datos).issubset({"estado", "nombre_cliente", "correo", "telefono", "fecha_retiro", "cantidad"}):
        return jsonify({"error": "La solicitud contiene campos que no se pueden modificar."}), 400
    if "estado" in datos and datos["estado"] not in ESTADOS_RESERVA:
        return jsonify({"error": "Selecciona un estado de reserva válido."}), 400
    if "nombre_cliente" in datos and (not str(datos["nombre_cliente"]).strip() or len(str(datos["nombre_cliente"])) > 100):
        return jsonify({"error": "El nombre del cliente no es válido."}), 400
    if "correo" in datos and datos["correo"] is not None and (not str(datos["correo"]).strip() or "@" not in str(datos["correo"]) or len(str(datos["correo"])) > 150):
        return jsonify({"error": "El correo del cliente no es válido."}), 400
    if "telefono" in datos and (not str(datos["telefono"]).strip() or len(str(datos["telefono"])) > 30):
        return jsonify({"error": "El teléfono del cliente no es válido."}), 400
    try:
        fecha_retiro = (
            datetime.fromisoformat(datos["fecha_retiro"])
            if "fecha_retiro" in datos
            else None
        )
        cantidad = int(datos["cantidad"]) if "cantidad" in datos else None
    except (TypeError, ValueError):
        return jsonify({"error": "La fecha o cantidad no son válidas."}), 400
    if cantidad is not None and (cantidad < 1 or cantidad > 30):
        return jsonify({"error": "La cantidad debe estar entre 1 y 30."}), 400

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        conexion.start_transaction()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT r.id_reserva, r.codigo, r.estado, r.monto_pagado, r.anticipo_requerido,
                   r.fecha_retiro, d.id_detalle, d.precio_unitario, d.cantidad
            FROM RESERVA r
            JOIN DETALLE_RESERVA d ON d.id_reserva = r.id_reserva
            WHERE r.id_reserva = %s
            FOR UPDATE
            """,
            (reserva_id,),
        )
        actual = cursor.fetchone()
        if not actual:
            conexion.rollback()
            return jsonify({"error": "La reserva ya no existe."}), 404
        estado = datos.get("estado", actual["estado"])
        pago_registrado = Decimal(str(actual["monto_pagado"] or 0)) >= Decimal(str(actual["anticipo_requerido"] or 0))

        asignaciones = []
        valores = []
        for campo in ("nombre_cliente", "correo", "telefono"):
            if campo in datos:
                asignaciones.append(f"{campo} = %s")
                valores.append(str(datos[campo]).strip().lower() if campo == "correo" else str(datos[campo]).strip())

        if fecha_retiro:
            asignaciones.append("fecha_retiro = %s")
            valores.append(fecha_retiro)

        if "estado" in datos:
            asignaciones.append("estado = %s")
            valores.append(estado)

            # Si el administrador avanza la reserva a Confirmada/Preparación/Lista y faltaba registrar el anticipo,
            # se actualiza el anticipo como registrado automáticamente.
            if estado in {"CONFIRMADA", "EN_PREPARACION", "LISTA", "ENTREGADA"} and not pago_registrado:
                cursor.execute(
                    """
                    UPDATE PAGO SET estado = 'PAGADO', fecha_pago = NOW()
                    WHERE id_reserva = %s AND estado = 'PENDIENTE'
                    """,
                    (reserva_id,),
                )
                asignaciones.append("monto_pagado = %s")
                valores.append(actual["anticipo_requerido"])

        if cantidad is not None and cantidad != actual["cantidad"]:
            if Decimal(str(actual["monto_pagado"] or 0)) > 0:
                conexion.rollback()
                return jsonify({"error": "No se puede cambiar la cantidad después de registrar un pago."}), 409
            nuevo_total = (Decimal(str(actual["precio_unitario"])) * cantidad).quantize(Decimal("0.01"))
            nuevo_anticipo = (nuevo_total / 2).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
            cursor.execute(
                "UPDATE DETALLE_RESERVA SET cantidad = %s WHERE id_detalle = %s",
                (cantidad, actual["id_detalle"]),
            )
            cursor.execute(
                """
                UPDATE PAGO SET monto = %s
                WHERE id_reserva = %s AND estado = 'PENDIENTE'
                """,
                (nuevo_anticipo, reserva_id),
            )
            asignaciones.extend(["total = %s", "anticipo_requerido = %s"])
            valores.extend([nuevo_total, nuevo_anticipo])

        if asignaciones:
            valores.append(reserva_id)
            cursor.execute(
                f"UPDATE RESERVA SET {', '.join(asignaciones)} WHERE id_reserva = %s",
                tuple(valores),
            )
        if "estado" in datos:
            try:
                cursor.execute("UPDATE CANJE_FIDELIDAD SET estado = %s WHERE id_reserva = %s", (estado, reserva_id))
                if estado == "ENTREGADA":
                    cursor.execute("UPDATE CANJE_FIDELIDAD SET fecha_entrega = NOW() WHERE id_reserva = %s", (reserva_id,))
            except Exception:
                pass
        _acreditar_puntos_fidelidad_si_corresponde(cursor, conexion, reserva_id)
        conexion.commit()

        # Notificaciones por correo según el cambio de estado
        if "estado" in datos and estado == "CONFIRMADA" and actual["estado"] != "CONFIRMADA":
            _notificar_reserva_confirmada(reserva_id)
        elif "estado" in datos and estado == "LISTA" and actual["estado"] != "LISTA":
            _notificar_reserva_lista(reserva_id)
        elif "estado" in datos and estado == "CANCELADA" and actual["estado"] != "CANCELADA":
            _notificar_reserva_rechazada(reserva_id, motivo="Reserva cancelada desde la edición del administrador.")

        return jsonify({"mensaje": "Reserva actualizada exitosamente."})
    except mysql.connector.Error as error:
        if conexion:
            conexion.rollback()
        return _error_base_datos(error, "No se pudo actualizar la reserva.")
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/admin/reservas/<int:reserva_id>/marcar-pago", methods=["POST"])
@app.route("/api/admin/reservas/<int:reserva_id>/confirmar", methods=["POST"])
@app.route("/api/admin/reservas/<int:reserva_id>/pago", methods=["POST"])
@administrador_requerido
def api_admin_marcar_pago(reserva_id):
    """Confirma manualmente la reserva tras recibir el anticipo en tienda y notifica al cliente."""
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        conexion.start_transaction()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT r.id_reserva, r.codigo, r.monto_pagado, r.anticipo_requerido, r.estado,
                   p.id_pago, p.monto, p.estado AS pago_estado, p.metodo_pago
            FROM RESERVA r
            LEFT JOIN PAGO p ON p.id_reserva = r.id_reserva
            WHERE r.id_reserva = %s
            ORDER BY p.id_pago DESC
            LIMIT 1
            FOR UPDATE
            """,
            (reserva_id,),
        )
        reserva = cursor.fetchone()
        if not reserva:
            conexion.rollback()
            return jsonify({"error": "La reserva no existe."}), 404
        if reserva["estado"] == "CANCELADA":
            conexion.rollback()
            return jsonify({"error": "No se puede confirmar una reserva cancelada."}), 409

        anticipo = Decimal(str(reserva["anticipo_requerido"] or 0))

        # Actualiza o crea el registro de pago del anticipo
        if reserva.get("id_pago"):
            cursor.execute(
                """
                UPDATE PAGO
                SET estado = 'PAGADO',
                    fecha_pago = NOW()
                WHERE id_pago = %s
                """,
                (reserva["id_pago"],),
            )
        else:
            cursor.execute(
                """
                INSERT INTO PAGO (id_reserva, metodo_pago, monto, estado, referencia, fecha_pago)
                VALUES (%s, 'EFECTIVO_TIENDA', %s, 'PAGADO', %s, NOW())
                """,
                (reserva_id, anticipo, f"CONF-MANUAL-{reserva['codigo']}"),
            )

        cursor.execute(
            """
            UPDATE RESERVA
            SET monto_pagado = CASE WHEN monto_pagado < anticipo_requerido THEN anticipo_requerido ELSE monto_pagado END,
                estado = 'CONFIRMADA'
            WHERE id_reserva = %s
            """,
            (reserva_id,),
        )
        conexion.commit()

        # Enviar correo electrónico de confirmación al cliente
        _notificar_reserva_confirmada(reserva_id)

        return jsonify({
            "mensaje": f"Anticipo registrado y reserva {reserva['codigo']} confirmada exitosamente. Se ha enviado el correo de confirmación al cliente."
        })
    except mysql.connector.Error as error:
        if conexion:
            conexion.rollback()
        return _error_base_datos(error, "No se pudo registrar el anticipo y confirmar la reserva.")
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/admin/reservas/<int:reserva_id>/rechazar", methods=["POST"])
@administrador_requerido
def api_admin_rechazar_reserva(reserva_id):
    """Rechaza / cancela la reserva y notifica por correo electrónico al cliente."""
    datos = request.get_json(silent=True) or {}
    motivo = str(datos.get("motivo", "")).strip() or None

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        conexion.start_transaction()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id_reserva, codigo, estado, nombre_cliente
            FROM RESERVA
            WHERE id_reserva = %s
            FOR UPDATE
            """,
            (reserva_id,),
        )
        reserva = cursor.fetchone()
        if not reserva:
            conexion.rollback()
            return jsonify({"error": "La reserva no existe."}), 404
        if reserva["estado"] == "CANCELADA":
            conexion.rollback()
            return jsonify({"error": "La reserva ya ha sido rechazada o cancelada anteriormente."}), 409

        cursor.execute(
            "UPDATE RESERVA SET estado = 'CANCELADA' WHERE id_reserva = %s",
            (reserva_id,),
        )
        cursor.execute(
            "UPDATE PAGO SET estado = 'CANCELADO' WHERE id_reserva = %s AND estado = 'PENDIENTE'",
            (reserva_id,),
        )
        conexion.commit()

        # Notificar por correo al cliente
        _notificar_reserva_rechazada(reserva_id, motivo=motivo)

        return jsonify({
            "mensaje": f"Reserva {reserva['codigo']} rechazada exitosamente. Se ha enviado una notificación por correo al cliente."
        })
    except mysql.connector.Error as error:
        if conexion:
            conexion.rollback()
        return _error_base_datos(error, "No se pudo rechazar la reserva.")
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/admin/reservas/<int:reserva_id>/marcar-lista", methods=["POST"])
@administrador_requerido
def api_admin_marcar_lista(reserva_id):
    """Marca la reserva como LISTA para retirar y envía un correo electrónico al cliente."""
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        conexion.start_transaction()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT r.id_reserva, r.codigo, r.estado, r.monto_pagado, r.anticipo_requerido
            FROM RESERVA r
            WHERE r.id_reserva = %s
            FOR UPDATE
            """,
            (reserva_id,),
        )
        reserva = cursor.fetchone()
        if not reserva:
            conexion.rollback()
            return jsonify({"error": "La reserva no existe."}), 404
        if reserva["estado"] == "CANCELADA":
            conexion.rollback()
            return jsonify({"error": "No se puede marcar como lista una reserva cancelada."}), 409
        if reserva["estado"] == "PENDIENTE_PAGO":
            conexion.rollback()
            return jsonify({"error": "La reserva aún no ha sido confirmada ni se ha registrado el anticipo."}), 409

        if reserva["estado"] != "LISTA":
            cursor.execute(
                "UPDATE RESERVA SET estado = 'LISTA' WHERE id_reserva = %s",
                (reserva_id,),
            )
        conexion.commit()

        # Despacha la notificación por correo al cliente
        _notificar_reserva_lista(reserva_id)

        return jsonify({
            "mensaje": f"Reserva {reserva['codigo']} marcada como lista. Notificación enviada al correo del cliente."
        })
    except mysql.connector.Error as error:
        if conexion:
            conexion.rollback()
        return _error_base_datos(error, "No se pudo actualizar la reserva a lista.")
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/admin/reservas/<int:reserva_id>/cobro-tarjeta", methods=["POST"])
@administrador_requerido
def api_admin_cobro_tarjeta(reserva_id):
    """
    Genera un cobro dinámico con tarjeta mediante Wompi para una reserva en el panel admin.
    Permite cobrar el anticipo o el saldo restante cuando el cliente llega al local o en línea.
    """
    if not _csrf_valido():
        return jsonify({"error": "La sesión de seguridad venció. Recarga la página."}), 403

    if not _wompi_configurada():
        return jsonify({
            "error": "Wompi no está configurado en .env. Por favor define WOMPI_CLIENT_ID y WOMPI_CLIENT_SECRET."
        }), 503

    datos = request.get_json(silent=True) or {}
    monto_raw = datos.get("monto")

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id_reserva, codigo, total, anticipo_requerido, monto_pagado, estado, nombre_cliente, telefono
            FROM RESERVA
            WHERE id_reserva = %s
            """,
            (reserva_id,),
        )
        reserva = cursor.fetchone()
        if not reserva:
            return jsonify({"error": "La reserva no existe."}), 404
        if reserva["estado"] == "CANCELADA":
            return jsonify({"error": "No se puede generar un cobro para una reserva cancelada."}), 409

        total = Decimal(str(reserva["total"] or 0))
        monto_pagado = Decimal(str(reserva["monto_pagado"] or 0))
        saldo_pendiente = (total - monto_pagado).quantize(Decimal("0.01"))

        if saldo_pendiente <= 0:
            return jsonify({"error": "Esta reserva ya está pagada en su totalidad."}), 400

        if monto_raw:
            try:
                monto_cobro = Decimal(str(monto_raw)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            except (ValueError, InvalidOperation):
                return jsonify({"error": "El monto especificado no es válido."}), 400
        else:
            anticipo = Decimal(str(reserva["anticipo_requerido"] or 0))
            if monto_pagado < anticipo:
                monto_cobro = (anticipo - monto_pagado).quantize(Decimal("0.01"))
            else:
                monto_cobro = saldo_pendiente

        if monto_cobro <= 0:
            return jsonify({"error": "El monto a cobrar debe ser mayor a cero."}), 400

        if monto_cobro > saldo_pendiente:
            monto_cobro = saldo_pendiente

        referencia_cobro = f"POS-{reserva['codigo']}-{secrets.token_hex(3).upper()}"
        nombre_producto = f"Reserva {reserva['codigo']} - TWINS Bakery"

        # Crear enlace de pago oficial en Wompi usando Python nativo
        enlace = crear_enlace_pago(referencia_cobro, monto_cobro, nombre_producto)

        cursor.execute(
            """
            INSERT INTO PAGO (id_reserva, metodo_pago, monto, estado, referencia, referencia_wompi)
            VALUES (%s, 'WOMPI', %s, 'PENDIENTE', %s, %s)
            """,
            (reserva_id, monto_cobro, referencia_cobro, str(enlace.get("idEnlace", ""))),
        )
        conexion.commit()

        return jsonify({
            "ok": True,
            "referencia": referencia_cobro,
            "url_pago": enlace["urlEnlace"],
            "id_enlace": enlace["idEnlace"],
            "monto": float(monto_cobro),
            "codigo_reserva": reserva["codigo"],
            "cliente": reserva["nombre_cliente"],
            "saldo_pendiente": float(saldo_pendiente),
        })

    except Exception as error:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al generar cobro Wompi para reserva %s: %s", reserva_id, error)
        return jsonify({"error": "No se pudo crear el enlace de cobro en este momento. Inténtalo más tarde."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/admin/reservas/<int:reserva_id>/verificar-pago-wompi", methods=["POST"])
@administrador_requerido
def api_admin_verificar_pago_wompi(reserva_id):
    """
    Verifica en tiempo real contra la API de Wompi si el enlace de cobro generado fue completado.
    Permite confirmar el cobro automáticamente desde el admin sin depender del móvil.
    """
    if not _csrf_valido():
        return jsonify({"error": "Sesión vencida. Recarga la página."}), 403

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT p.id_pago, p.id_reserva, p.monto, p.estado, p.referencia, p.referencia_wompi,
                   r.codigo, r.total, r.anticipo_requerido, r.monto_pagado, r.nombre_cliente,
                   COALESCE(NULLIF(r.correo, ''), c.correo, '') AS correo_cliente
            FROM PAGO p
            JOIN RESERVA r ON r.id_reserva = p.id_reserva
            LEFT JOIN CLIENTE c ON c.id_cliente = r.id_cliente
            WHERE p.id_reserva = %s AND p.metodo_pago = 'WOMPI'
            ORDER BY p.id_pago DESC
            LIMIT 1
            """,
            (reserva_id,),
        )
        pago = cursor.fetchone()
        if not pago:
            return jsonify({"ok": False, "error": "No hay ningún cobro con Wompi registrado para esta reserva."}), 404

        if pago["estado"] == "PAGADO":
            return jsonify({
                "ok": True,
                "pagado": True,
                "ya_registrado": True,
                "monto": float(pago["monto"]),
                "mensaje": "Este cobro ya se encuentra registrado y pagado.",
            })

        id_enlace = str(pago.get("referencia_wompi") or "").strip()
        if not id_enlace:
            return jsonify({"ok": False, "error": "El registro de cobro no tiene ID de enlace Wompi."}), 400

        resultado_wompi = consultar_estado_enlace_wompi(id_enlace)
        if resultado_wompi.get("pagado"):
            try:
                conexion.start_transaction()
            except Exception:
                pass
            monto_cobrado = Decimal(str(pago["monto"])).quantize(Decimal("0.01"))
            pagado_actual = Decimal(str(pago["monto_pagado"] or 0)).quantize(Decimal("0.01"))
            nuevo_pagado = (pagado_actual + monto_cobrado).quantize(Decimal("0.01"))
            total = Decimal(str(pago["total"] or 0)).quantize(Decimal("0.01"))

            cursor.execute(
                """
                UPDATE PAGO
                SET estado = 'PAGADO', fecha_pago = NOW()
                WHERE id_pago = %s
                """,
                (pago["id_pago"],),
            )

            # Actualizar el monto pagado de la reserva. El estado de la reserva se mantiene
            # tal cual (el administrador debe pulsar 'Aceptar reserva' para confirmarla manualmente).
            cursor.execute(
                """
                UPDATE RESERVA
                SET monto_pagado = %s
                WHERE id_reserva = %s
                """,
                (nuevo_pagado, reserva_id),
            )
            _acreditar_puntos_fidelidad_si_corresponde(cursor, conexion, reserva_id)
            conexion.commit()

            correo_cli = pago.get("correo_cliente")
            if correo_cli:
                try:
                    saldo_restante = max(Decimal("0.00"), total - nuevo_pagado)
                    enviar_correo_pago_tarjeta_recibido(
                        destinatario=correo_cli,
                        nombre=pago["nombre_cliente"],
                        codigo=pago["codigo"],
                        monto_pagado=monto_cobrado,
                        referencia_pago=pago.get("referencia") or id_enlace,
                        total=total,
                        saldo_restante=saldo_restante,
                        nombre_producto=f"Reserva {pago['codigo']}",
                    )
                except Exception as err_m:
                    app.logger.warning("No se pudo enviar comprobante tras verificar Wompi: %s", err_m)

            return jsonify({
                "ok": True,
                "pagado": True,
                "monto": float(monto_cobrado),
                "nuevo_pagado": float(nuevo_pagado),
                "total": float(total),
                "mensaje": f"¡Pago de ${monto_cobrado:.2f} verificado con éxito en Wompi y registrado!",
            })

        return jsonify({
            "ok": True,
            "pagado": False,
            "mensaje": "El pago aún no ha sido completado en Wompi.",
        })

    except Exception as err:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al verificar pago Wompi en reserva %s: %s", reserva_id, err)
        return jsonify({"ok": False, "error": "No se pudo verificar el estado del pago con la pasarela. Inténtalo nuevamente."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/admin/reservas/<int:reserva_id>/marcar-cobro-tarjeta-manual", methods=["POST"])
@administrador_requerido
def api_admin_marcar_cobro_tarjeta_manual(reserva_id):
    """
    Permite registrar un cobro con tarjeta realizado presencialmente en el POS del local.
    """
    if not _csrf_valido():
        return jsonify({"error": "Sesión vencida. Recarga la página."}), 403

    datos = request.get_json(silent=True) or {}
    monto_raw = datos.get("monto")

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        conexion.start_transaction()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT r.id_reserva, r.codigo, r.total, r.anticipo_requerido, r.monto_pagado, r.estado, r.nombre_cliente,
                   COALESCE(NULLIF(r.correo, ''), c.correo, '') AS correo_cliente,
                   d.nombre_producto
            FROM RESERVA r
            LEFT JOIN CLIENTE c ON c.id_cliente = r.id_cliente
            LEFT JOIN DETALLE_RESERVA d ON d.id_reserva = r.id_reserva
            WHERE r.id_reserva = %s
            ORDER BY d.id_detalle ASC
            LIMIT 1
            """,
            (reserva_id,),
        )
        reserva = cursor.fetchone()
        if not reserva:
            conexion.rollback()
            return jsonify({"error": "La reserva no existe."}), 404

        total = Decimal(str(reserva["total"] or 0))
        monto_pagado = Decimal(str(reserva["monto_pagado"] or 0))
        saldo_pendiente = (total - monto_pagado).quantize(Decimal("0.01"))

        if saldo_pendiente <= 0:
            conexion.rollback()
            return jsonify({"error": "Esta reserva ya se encuentra pagada en su totalidad."}), 400

        if monto_raw:
            try:
                monto_cobro = Decimal(str(monto_raw)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            except (ValueError, InvalidOperation):
                conexion.rollback()
                return jsonify({"error": "El monto especificado no es válido."}), 400
        else:
            anticipo = Decimal(str(reserva["anticipo_requerido"] or 0))
            if monto_pagado < anticipo:
                monto_cobro = (anticipo - monto_pagado).quantize(Decimal("0.01"))
            else:
                monto_cobro = saldo_pendiente

        if monto_cobro <= 0:
            conexion.rollback()
            return jsonify({"error": "El monto a cobrar debe ser mayor a cero."}), 400

        if monto_cobro > saldo_pendiente:
            monto_cobro = saldo_pendiente

        nuevo_pagado = (monto_pagado + monto_cobro).quantize(Decimal("0.01"))
        ref_pos = f"POS-FISICO-{reserva['codigo']}-{secrets.token_hex(3).upper()}"

        cursor.execute(
            """
            INSERT INTO PAGO (id_reserva, metodo_pago, monto, estado, referencia, fecha_pago)
            VALUES (%s, 'WOMPI_POS', %s, 'PAGADO', %s, NOW())
            """,
            (reserva_id, monto_cobro, ref_pos),
        )

        # Actualizar monto pagado sin alterar estado_reserva para que el admin confirme manualmente
        cursor.execute(
            """
            UPDATE RESERVA
            SET monto_pagado = %s
            WHERE id_reserva = %s
            """,
            (nuevo_pagado, reserva_id),
        )
        _acreditar_puntos_fidelidad_si_corresponde(cursor, conexion, reserva_id)
        conexion.commit()

        correo_cli = reserva.get("correo_cliente")
        if correo_cli:
            try:
                saldo_restante = max(Decimal("0.00"), total - nuevo_pagado)
                enviar_correo_pago_tarjeta_recibido(
                    destinatario=correo_cli,
                    nombre=reserva["nombre_cliente"],
                    codigo=reserva["codigo"],
                    monto_pagado=monto_cobro,
                    referencia_pago=ref_pos,
                    total=total,
                    saldo_restante=saldo_restante,
                    nombre_producto=reserva.get("nombre_producto") or f"Reserva {reserva['codigo']}",
                )
            except Exception as err_m:
                app.logger.warning("No se pudo enviar comprobante tras cobro POS manual: %s", err_m)

        return jsonify({
            "ok": True,
            "monto": float(monto_cobro),
            "nuevo_pagado": float(nuevo_pagado),
            "saldo_restante": float(max(Decimal("0.00"), total - nuevo_pagado)),
            "mensaje": f"Cobro con tarjeta de ${monto_cobro:.2f} registrado exitosamente.",
        })

    except Exception as error:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al registrar cobro POS manual para reserva %s: %s", reserva_id, error)
        return jsonify({"error": "No se pudo registrar el cobro en el sistema. Inténtalo de nuevo."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/admin/reservas/<int:reserva_id>/liquidar-pago", methods=["POST"])
@app.route("/api/admin/reservas/<int:reserva_id>/marcar-pago-completo", methods=["POST"])
@administrador_requerido
def api_admin_liquidar_pago(reserva_id):
    """
    Registra la liquidación completa del saldo restante de una reserva (100% pagado).
    Permite al administrador indicar cuándo el pago total ha sido completado.
    """
    if not _csrf_valido():
        return jsonify({"error": "La sesión de seguridad venció. Recarga la página."}), 403

    datos = request.get_json(silent=True) or {}
    metodo = datos.get("metodo_pago", "EFECTIVO_TIENDA")
    if metodo not in ("EFECTIVO_TIENDA", "WOMPI_POS", "TRANSFERENCIA", "WOMPI"):
        metodo = "EFECTIVO_TIENDA"

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        conexion.start_transaction()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id_reserva, codigo, total, monto_pagado, estado, nombre_cliente,
                   COALESCE(NULLIF(correo, ''), '') AS correo_cliente
            FROM RESERVA
            WHERE id_reserva = %s
            """,
            (reserva_id,),
        )
        reserva = cursor.fetchone()
        if not reserva:
            conexion.rollback()
            return jsonify({"error": "La reserva no existe."}), 404
        if reserva["estado"] == "CANCELADA":
            conexion.rollback()
            return jsonify({"error": "No se puede liquidar una reserva cancelada."}), 409

        total = Decimal(str(reserva["total"] or 0)).quantize(Decimal("0.01"))
        pagado_actual = Decimal(str(reserva["monto_pagado"] or 0)).quantize(Decimal("0.01"))
        saldo_pendiente = (total - pagado_actual).quantize(Decimal("0.01"))

        if saldo_pendiente <= Decimal("0.00"):
            conexion.rollback()
            return jsonify({"error": "Esta reserva ya se encuentra 100% pagada."}), 400

        ref_liq = f"LIQ-{reserva['codigo']}-{secrets.token_hex(2).upper()}"
        cursor.execute(
            """
            INSERT INTO PAGO (id_reserva, metodo_pago, monto, estado, referencia, fecha_pago)
            VALUES (%s, %s, %s, 'PAGADO', %s, NOW())
            """,
            (reserva_id, metodo, saldo_pendiente, ref_liq),
        )

        cursor.execute(
            """
            UPDATE RESERVA
            SET monto_pagado = %s
            WHERE id_reserva = %s
            """,
            (total, reserva_id),
        )
        _acreditar_puntos_fidelidad_si_corresponde(cursor, conexion, reserva_id)
        conexion.commit()

        # Enviar comprobante al cliente si tiene correo registrado
        correo_cli = reserva.get("correo_cliente")
        if correo_cli:
            try:
                enviar_correo_pago_tarjeta_recibido(
                    destinatario=correo_cli,
                    nombre=reserva["nombre_cliente"],
                    codigo=reserva["codigo"],
                    monto_pagado=saldo_pendiente,
                    referencia_pago=ref_liq,
                    total=total,
                    saldo_restante=Decimal("0.00"),
                    nombre_producto=f"Liquidación Total · Reserva {reserva['codigo']}",
                )
            except Exception as err_m:
                app.logger.warning("No se pudo enviar comprobante de liquidación total: %s", err_m)

        return jsonify({
            "ok": True,
            "codigo": reserva["codigo"],
            "monto_liquidado": float(saldo_pendiente),
            "nuevo_pagado": float(total),
            "total": float(total),
            "mensaje": f"¡Saldo de ${saldo_pendiente:.2f} registrado con éxito! La reserva {reserva['codigo']} quedó 100% pagada.",
        })
    except Exception as e:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al liquidar pago de reserva %s: %s", reserva_id, e)
        return jsonify({"error": "No se pudo registrar la liquidación del pago. Inténtalo de nuevo."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


# ==========================================
# APIS PARA EVENTOS Y SOLICITUDES DE PLANIFICACIÓN
# ==========================================

@app.route("/api/admin/eventos", methods=["GET"])
@administrador_requerido
def api_admin_eventos():
    """Retorna la lista de solicitudes de planificación para el administrador."""
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT s.id_solicitud, s.id_cliente, c.nombre AS cliente,
                   COALESCE(c.correo, '') AS correo, COALESCE(c.telefono, '') AS telefono,
                   s.tipo_evento, s.num_invitados, s.presupuesto_estimado,
                   s.fecha_evento, s.lugar_evento, s.servicios, s.estado,
                   s.fecha_solicitud, ce.id_chat_evento
            FROM SOLICITUD_PLANIFICACION s
            JOIN CLIENTE c ON c.id_cliente = s.id_cliente
            LEFT JOIN CHAT_EVENTO ce ON ce.id_solicitud = s.id_solicitud
            ORDER BY s.fecha_solicitud DESC, s.id_solicitud DESC
            """
        )
        filas = cursor.fetchall()
        resultados = []
        for f in filas:
            presupuesto_val = None
            if f.get("presupuesto_estimado") is not None:
                try:
                    presupuesto_val = float(f["presupuesto_estimado"])
                except (ValueError, TypeError):
                    presupuesto_val = None

            resultados.append({
                "id_solicitud": f["id_solicitud"],
                "id_cliente": f["id_cliente"],
                "cliente": f["cliente"],
                "correo": f["correo"],
                "telefono": f["telefono"],
                "tipo_evento": f["tipo_evento"],
                "num_invitados": f["num_invitados"],
                "presupuesto_estimado": presupuesto_val,
                "fecha_evento": str(f["fecha_evento"]),
                "lugar_evento": f.get("lugar_evento") or "",
                "servicios": f.get("servicios") or "",
                "estado": f["estado"],
                "fecha_solicitud": str(f["fecha_solicitud"]),
                "id_chat_evento": f.get("id_chat_evento"),
            })
        return jsonify(resultados)
    except Exception as err:
        app.logger.exception("Error al consultar solicitudes de eventos: %s", err)
        return jsonify({"error": "No se pudieron consultar las solicitudes de eventos."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/admin/eventos/<int:solicitud_id>/aceptar", methods=["POST"])
@administrador_requerido
def api_admin_evento_aceptar(solicitud_id):
    """Acepta la solicitud, notifica por correo al cliente y crea el chat-evento 1:1 redirigiendo a él."""
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT s.id_solicitud, s.id_cliente, s.tipo_evento, s.num_invitados,
                   s.presupuesto_estimado, s.fecha_evento, s.lugar_evento, s.estado,
                   c.nombre, c.correo
            FROM SOLICITUD_PLANIFICACION s
            JOIN CLIENTE c ON c.id_cliente = s.id_cliente
            WHERE s.id_solicitud = %s
            """,
            (solicitud_id,),
        )
        solicitud = cursor.fetchone()
        if not solicitud:
            return jsonify({"error": "La solicitud ya no existe."}), 404

        # Cambiar estado a ACEPTADA
        cursor.execute(
            "UPDATE SOLICITUD_PLANIFICACION SET estado = 'ACEPTADA' WHERE id_solicitud = %s",
            (solicitud_id,),
        )

        # Crear o consultar el CHAT_EVENTO con restricción 1:1
        cursor.execute(
            "SELECT id_chat_evento FROM CHAT_EVENTO WHERE id_solicitud = %s",
            (solicitud_id,),
        )
        chat_existente = cursor.fetchone()
        if chat_existente:
            id_chat_evento = chat_existente["id_chat_evento"] if isinstance(chat_existente, dict) else chat_existente[0]
        else:
            titulo_default = f"{solicitud['tipo_evento']} - {solicitud['nombre']}"
            cursor.execute(
                """
                INSERT INTO CHAT_EVENTO (id_solicitud, id_cliente, id_admin, titulo)
                VALUES (%s, %s, %s, %s)
                """,
                (solicitud_id, solicitud["id_cliente"], 1, titulo_default),
            )
            id_chat_evento = cursor.lastrowid

            # Mensaje de bienvenida inicial
            mensaje_bienvenida = (
                f"¡Hola {solicitud['nombre']}! Tu solicitud para el evento '{solicitud['tipo_evento']}' "
                f"ha sido aceptada por TWINS Bakery. Estaremos coordinando todos los detalles aquí."
            )
            cursor.execute(
                """
                INSERT INTO MENSAJE_EVENTO (id_chat_evento, rol, mensaje)
                VALUES (%s, 'admin', %s)
                """,
                (id_chat_evento, mensaje_bienvenida),
            )

        conexion.commit()

        # Despachar correo de notificación de evento aceptado
        try:
            enviar_correo_evento_aceptado(
                destinatario=solicitud["correo"],
                nombre=solicitud["nombre"],
                tipo_evento=solicitud["tipo_evento"],
                fecha_evento=solicitud["fecha_evento"],
                num_invitados=solicitud["num_invitados"],
                presupuesto_estimado=solicitud["presupuesto_estimado"],
            )
        except Exception as err_mail:
            app.logger.warning("No se pudo despachar correo de evento aceptado: %s", err_mail)

        return jsonify({
            "ok": True,
            "mensaje": "Solicitud aceptada y notificación enviada.",
            "id_chat_evento": id_chat_evento,
            "redirect_url": url_for("admin_chat_evento", chat_evento_id=id_chat_evento),
        })
    except Exception as err:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al aceptar solicitud de evento: %s", err)
        return jsonify({"error": "No se pudo aceptar la solicitud de evento."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/admin/eventos/<int:solicitud_id>/rechazar", methods=["POST"])
@administrador_requerido
def api_admin_evento_rechazar(solicitud_id):
    """Rechaza la solicitud y envía notificación por correo explicando el motivo."""
    datos = request.get_json(silent=True) or {}
    motivo = datos.get("motivo", "").strip() if isinstance(datos, dict) else ""

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT s.id_solicitud, s.tipo_evento, s.fecha_evento,
                   c.nombre, c.correo
            FROM SOLICITUD_PLANIFICACION s
            JOIN CLIENTE c ON c.id_cliente = s.id_cliente
            WHERE s.id_solicitud = %s
            """,
            (solicitud_id,),
        )
        solicitud = cursor.fetchone()
        if not solicitud:
            return jsonify({"error": "La solicitud ya no existe."}), 404

        cursor.execute(
            "UPDATE SOLICITUD_PLANIFICACION SET estado = 'RECHAZADA' WHERE id_solicitud = %s",
            (solicitud_id,),
        )
        conexion.commit()

        try:
            enviar_correo_evento_rechazado(
                destinatario=solicitud["correo"],
                nombre=solicitud["nombre"],
                tipo_evento=solicitud["tipo_evento"],
                fecha_evento=solicitud["fecha_evento"],
                motivo=motivo or None,
            )
        except Exception as err_mail:
            app.logger.warning("No se pudo enviar correo de evento rechazado: %s", err_mail)

        return jsonify({
            "ok": True,
            "mensaje": "Solicitud rechazada y notificación enviada por correo al cliente.",
        })
    except Exception as err:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al rechazar solicitud de evento: %s", err)
        return jsonify({"error": "No se pudo procesar el rechazo de la solicitud."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


# ==========================================
# APIS PARA CHAT DE EVENTO (CHAT-EVENTO)
# ==========================================

@app.route("/api/chat-evento/<int:chat_evento_id>/mensajes", methods=["GET"])
def api_chat_evento_mensajes(chat_evento_id):
    """Obtiene los mensajes de un chat-evento verificando permisos."""
    es_admin = bool(session.get("es_admin"))
    id_cliente = session.get("id_cliente")

    if not es_admin and not id_cliente:
        return jsonify({"error": "No autorizado."}), 401

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT ce.id_chat_evento, ce.id_solicitud, ce.id_cliente, ce.titulo,
                   s.tipo_evento, s.fecha_evento, s.num_invitados, s.presupuesto_estimado,
                   s.lugar_evento, s.servicios, c.nombre AS cliente_nombre
            FROM CHAT_EVENTO ce
            JOIN SOLICITUD_PLANIFICACION s ON s.id_solicitud = ce.id_solicitud
            JOIN CLIENTE c ON c.id_cliente = ce.id_cliente
            WHERE ce.id_chat_evento = %s
            """,
            (chat_evento_id,),
        )
        chat = cursor.fetchone()
        if not chat:
            return jsonify({"error": "El chat de evento no existe."}), 404

        if not es_admin and chat["id_cliente"] != id_cliente:
            return jsonify({"error": "No tienes acceso a este chat."}), 403

        cursor.execute(
            """
            SELECT id_mensaje_evento, rol, mensaje, fecha_envio
            FROM MENSAJE_EVENTO
            WHERE id_chat_evento = %s
            ORDER BY id_mensaje_evento ASC
            """,
            (chat_evento_id,),
        )
        mensajes = cursor.fetchall()
        mensajes_serializables = []
        for m in mensajes:
            mensajes_serializables.append({
                "id_mensaje_evento": m["id_mensaje_evento"],
                "rol": m["rol"],
                "mensaje": m["mensaje"],
                "fecha_envio": str(m["fecha_envio"]),
            })

        return jsonify({
            "chat": {
                "id_chat_evento": chat["id_chat_evento"],
                "titulo": chat["titulo"],
                "tipo_evento": chat["tipo_evento"],
                "fecha_evento": str(chat["fecha_evento"]),
                "num_invitados": chat["num_invitados"],
                "presupuesto_estimado": float(chat["presupuesto_estimado"]) if chat.get("presupuesto_estimado") is not None else None,
                "cliente_nombre": chat["cliente_nombre"],
            },
            "mensajes": mensajes_serializables,
        })
    except Exception as err:
        app.logger.exception("Error al consultar mensajes de chat-evento: %s", err)
        return jsonify({"error": "No se pudieron obtener los mensajes."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/chat-evento/<int:chat_evento_id>/mensaje", methods=["POST"])
def api_chat_evento_enviar_mensaje(chat_evento_id):
    """Envía un mensaje a un chat de evento (cliente o administrador)."""
    es_admin = bool(session.get("es_admin"))
    id_cliente = session.get("id_cliente")

    if not es_admin and not id_cliente:
        return jsonify({"error": "No autorizado."}), 401

    datos = request.get_json(silent=True) or {}
    texto = str(datos.get("mensaje", "")).strip()
    if not texto:
        return jsonify({"error": "El mensaje no puede estar vacío."}), 400
    if len(texto) > 1000:
        return jsonify({"error": "El mensaje supera los 1000 caracteres permitidos."}), 400

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)

        cursor.execute("SELECT id_cliente FROM CHAT_EVENTO WHERE id_chat_evento = %s", (chat_evento_id,))
        chat = cursor.fetchone()
        if not chat:
            return jsonify({"error": "El chat no existe."}), 404

        if not es_admin and chat["id_cliente"] != id_cliente:
            return jsonify({"error": "No tienes acceso a este chat."}), 403

        rol = "admin" if es_admin else "cliente"
        cursor.execute(
            """
            INSERT INTO MENSAJE_EVENTO (id_chat_evento, rol, mensaje)
            VALUES (%s, %s, %s)
            """,
            (chat_evento_id, rol, texto),
        )
        conexion.commit()
        return jsonify({"ok": True, "mensaje_id": cursor.lastrowid})
    except Exception as err:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al guardar mensaje en chat-evento: %s", err)
        return jsonify({"error": "No se pudo enviar el mensaje."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


# ==========================================
# APIS PARA CHAT GENERAL (CLIENTE - ADMINISTRADOR)
# ==========================================

@app.route("/api/chat/mensajes", methods=["GET"])
@cliente_requerido
def api_chat_general_mensajes():
    """Consulta los mensajes del chat general del cliente logueado."""
    id_cliente = session["id_cliente"]
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)

        # Buscar o crear chat general (1:1 con cliente)
        cursor.execute("SELECT id_chat FROM CHAT WHERE id_cliente = %s", (id_cliente,))
        chat = cursor.fetchone()
        if not chat:
            cursor.execute("INSERT INTO CHAT (id_cliente, id_admin) VALUES (%s, 1)", (id_cliente,))
            id_chat = cursor.lastrowid
            conexion.commit()
        else:
            id_chat = chat["id_chat"] if isinstance(chat, dict) else chat[0]

        cursor.execute(
            """
            SELECT id_mensaje, rol, mensaje, fecha_envio
            FROM MENSAJE
            WHERE id_chat = %s
            ORDER BY id_mensaje ASC
            """,
            (id_chat,),
        )
        mensajes = cursor.fetchall()
        serializables = [
            {
                "id_mensaje": m["id_mensaje"],
                "rol": m["rol"],
                "mensaje": m["mensaje"],
                "fecha_envio": str(m["fecha_envio"]),
            }
            for m in mensajes
        ]
        return jsonify({"id_chat": id_chat, "mensajes": serializables})
    except Exception as err:
        app.logger.exception("Error al consultar mensajes de chat general: %s", err)
        return jsonify({"error": "No se pudieron obtener los mensajes."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/chat/mensaje", methods=["POST"])
@cliente_requerido
def api_chat_general_enviar():
    """Envía un mensaje en el chat general desde la perspectiva del cliente."""
    id_cliente = session["id_cliente"]
    datos = request.get_json(silent=True) or {}
    texto = str(datos.get("mensaje", "")).strip()

    if not texto:
        return jsonify({"error": "El mensaje no puede estar vacío."}), 400
    if len(texto) > 1000:
        return jsonify({"error": "El mensaje no puede superar 1000 caracteres."}), 400

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)

        cursor.execute("SELECT id_chat FROM CHAT WHERE id_cliente = %s", (id_cliente,))
        chat = cursor.fetchone()
        if not chat:
            cursor.execute("INSERT INTO CHAT (id_cliente, id_admin) VALUES (%s, 1)", (id_cliente,))
            id_chat = cursor.lastrowid
        else:
            id_chat = chat["id_chat"] if isinstance(chat, dict) else chat[0]

        cursor.execute(
            "INSERT INTO MENSAJE (id_chat, rol, mensaje) VALUES (%s, 'cliente', %s)",
            (id_chat, texto),
        )
        conexion.commit()
        return jsonify({"ok": True, "id_mensaje": cursor.lastrowid})
    except Exception as err:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al enviar mensaje en chat general: %s", err)
        return jsonify({"error": "No se pudo enviar el mensaje."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/cliente/chats-eventos", methods=["GET"])
@cliente_requerido
def api_cliente_chats_eventos():
    """Lista los chats de eventos correspondientes al cliente en sesión."""
    id_cliente = session["id_cliente"]
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT ce.id_chat_evento, ce.titulo, s.tipo_evento, s.fecha_evento
            FROM CHAT_EVENTO ce
            JOIN SOLICITUD_PLANIFICACION s ON s.id_solicitud = ce.id_solicitud
            WHERE ce.id_cliente = %s
            ORDER BY ce.fecha_creacion DESC
            """,
            (id_cliente,),
        )
        chats = cursor.fetchall()
        serializables = [
            {
                "id_chat_evento": c["id_chat_evento"],
                "titulo": c["titulo"],
                "tipo_evento": c["tipo_evento"],
                "fecha_evento": str(c["fecha_evento"]),
            }
            for c in chats
        ]
        return jsonify({"chats": serializables})
    except Exception as err:
        app.logger.exception("Error al consultar chats de eventos del cliente: %s", err)
        return jsonify({"error": "No se pudieron obtener los chats de eventos."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/admin/chats", methods=["GET"])
@administrador_requerido
def api_admin_chats_lista():
    """Retorna para el administrador las conversaciones generales y de eventos."""
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)

        # Conversaciones generales de clientes
        cursor.execute(
            """
            SELECT ch.id_chat, ch.id_cliente, c.nombre AS cliente_nombre, c.correo AS cliente_correo,
                   (SELECT mensaje FROM MENSAJE m WHERE m.id_chat = ch.id_chat ORDER BY m.id_mensaje DESC LIMIT 1) AS ultimo_mensaje
            FROM CHAT ch
            JOIN CLIENTE c ON c.id_cliente = ch.id_cliente
            ORDER BY ch.fecha_creacion DESC
            """
        )
        generales = cursor.fetchall()

        # Conversaciones de eventos
        cursor.execute(
            """
            SELECT ce.id_chat_evento, ce.id_solicitud, ce.id_cliente, ce.titulo,
                   c.nombre AS cliente_nombre, s.tipo_evento, s.fecha_evento,
                   (SELECT mensaje FROM MENSAJE_EVENTO me WHERE me.id_chat_evento = ce.id_chat_evento ORDER BY me.id_mensaje_evento DESC LIMIT 1) AS ultimo_mensaje
            FROM CHAT_EVENTO ce
            JOIN CLIENTE c ON c.id_cliente = ce.id_cliente
            JOIN SOLICITUD_PLANIFICACION s ON s.id_solicitud = ce.id_solicitud
            ORDER BY ce.fecha_creacion DESC
            """
        )
        eventos = cursor.fetchall()

        return jsonify({
            "general": [
                {
                    "id_chat": g["id_chat"],
                    "id_cliente": g["id_cliente"],
                    "cliente_nombre": g["cliente_nombre"],
                    "cliente_correo": g["cliente_correo"],
                    "ultimo_mensaje": g.get("ultimo_mensaje") or "Sin mensajes",
                }
                for g in generales
            ],
            "eventos": [
                {
                    "id_chat_evento": e["id_chat_evento"],
                    "id_solicitud": e["id_solicitud"],
                    "titulo": e["titulo"],
                    "cliente_nombre": e["cliente_nombre"],
                    "tipo_evento": e["tipo_evento"],
                    "fecha_evento": str(e["fecha_evento"]),
                    "ultimo_mensaje": e.get("ultimo_mensaje") or "Sin mensajes",
                }
                for e in eventos
            ]
        })
    except Exception as err:
        app.logger.exception("Error al consultar lista de chats de admin: %s", err)
        return jsonify({"error": "No se pudieron obtener las conversaciones."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/admin/chat/<int:chat_id>/mensajes", methods=["GET"])
@administrador_requerido
def api_admin_chat_mensajes(chat_id):
    """Obtiene los mensajes de un chat general de cliente específico."""
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT m.id_mensaje, m.rol, m.mensaje, m.fecha_envio
            FROM MENSAJE m
            WHERE m.id_chat = %s
            ORDER BY m.id_mensaje ASC
            """,
            (chat_id,),
        )
        mensajes = cursor.fetchall()
        serializables = [
            {
                "id_mensaje": m["id_mensaje"],
                "rol": m["rol"],
                "mensaje": m["mensaje"],
                "fecha_envio": str(m["fecha_envio"]),
            }
            for m in mensajes
        ]
        return jsonify({"mensajes": serializables})
    except Exception as err:
        app.logger.exception("Error al consultar mensajes de chat: %s", err)
        return jsonify({"error": "No se pudieron obtener los mensajes."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/admin/chat/<int:chat_id>/mensaje", methods=["POST"])
@administrador_requerido
def api_admin_chat_enviar(chat_id):
    """Envía un mensaje de respuesta del administrador a un chat general de cliente."""
    datos = request.get_json(silent=True) or {}
    texto = str(datos.get("mensaje", "")).strip()

    if not texto:
        return jsonify({"error": "El mensaje no puede estar vacío."}), 400
    if len(texto) > 1000:
        return jsonify({"error": "El mensaje supera los 1000 caracteres permitidos."}), 400

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor()
        cursor.execute(
            "INSERT INTO MENSAJE (id_chat, rol, mensaje) VALUES (%s, 'admin', %s)",
            (chat_id, texto),
        )
        conexion.commit()
        return jsonify({"ok": True, "id_mensaje": cursor.lastrowid})
    except Exception as err:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al responder chat general: %s", err)
        return jsonify({"error": "No se pudo enviar la respuesta."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.errorhandler(413)
def limite_solicitud_excedido(_error):
    app.logger.warning(
        "Se rechazó una solicitud demasiado grande en %s: %s",
        request.path,
        getattr(_error, "description", str(_error)),
    )
    if request.path.startswith("/api/") or request.is_json:
        return jsonify({"error": "La imagen o solicitud supera el tamaño permitido."}), 413
    return "La solicitud supera el tamaño permitido.", 413


@app.errorhandler(404)
def recurso_no_encontrado(_error):
    es_api = (
        request.path.startswith("/api/")
        or request.is_json
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in request.headers.get("Accept", "")
    )
    if es_api:
        return jsonify({"ok": False, "error": "El recurso solicitado no fue encontrado."}), 404
    try:
        return render_template("404.html"), 404
    except Exception:
        return "Página no encontrada (404).", 404


@app.errorhandler(Exception)
def manejar_excepcion_global(error):
    # Si es una excepción HTTP estándar de Werkzeug (p. ej. 404, 403, 401, 405)
    if isinstance(error, HTTPException):
        if error.code == 404:
            return recurso_no_encontrado(error)
        es_api = (
            request.path.startswith("/api/")
            or request.is_json
            or request.headers.get("X-Requested-With") == "XMLHttpRequest"
            or "application/json" in request.headers.get("Accept", "")
        )
        if es_api:
            return jsonify({"ok": False, "error": error.description}), error.code
        return (
            f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>Error {error.code}</title></head>"
            f"<body style='font-family:sans-serif;text-align:center;padding:50px;background:#fff1f5;'>"
            f"<h2>Inconveniente ({error.code})</h2><p>{error.description}</p>"
            f"<a href='/' style='color:#e75480;font-weight:bold;'>Volver al inicio</a>"
            f"</body></html>",
            error.code,
        )

    # Para cualquier error 500 o excepción de servidor:
    # 1. Generar código de error aleatorio para trazabilidad y anonimato
    codigo_error = f"ERR-{secrets.token_hex(3).upper()}"

    # 2. Registrar el TRACEBACK COMPLETO en la consola/servidor de forma detallada
    app.logger.exception(
        "[%s] Excepción interna no controlada en %s %s: %s",
        codigo_error,
        request.method,
        request.path,
        error,
    )

    # 3. Responder al cliente de forma totalmente segura (sin filtrar código, SQL ni rutas de disco)
    es_api = (
        request.path.startswith("/api/")
        or request.is_json
        or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in request.headers.get("Accept", "")
    )

    if es_api:
        return jsonify({
            "ok": False,
            "error": "Ocurrió un error interno en el servidor. Por favor, inténtalo más tarde.",
            "codigo_referencia": codigo_error,
        }), 500

    try:
        return render_template("500.html", codigo_error=codigo_error), 500
    except Exception:
        return (
            f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>Error del Servidor</title></head>"
            f"<body style='font-family:sans-serif;text-align:center;padding:50px;background:#fff1f5;'>"
            f"<h2>Inconveniente temporal en el servidor</h2>"
            f"<p>Ha ocurrido un problema al procesar tu solicitud. Código de referencia: <strong>{codigo_error}</strong></p>"
            f"<a href='/' style='color:#e75480;text-decoration:none;font-weight:bold;'>Volver al inicio</a>"
            f"</body></html>",
            500,
        )


# ==========================================
# PANTALLA DE INICIO DE SESIÓN
# ==========================================

@app.route("/login")
def login():
    if session.get("id_cliente"):
        return redirect(url_for("inicio"))
    return render_template("login.html")


# ==========================================
# PANTALLA DE REGISTRO
# ==========================================

@app.route("/registro")
def registro():
    return render_template("registroCliente.html")


# ==========================================
# REGISTRAR CLIENTE
# ==========================================

@app.route("/registrar-cliente", methods=["POST"])
def registrar_cliente():

    nombre = request.form.get("nombre", "").strip()
    correo = request.form.get("correo", "").strip().lower()
    contrasena = request.form.get("contrasena", "")
    confirmar = request.form.get("confirmar_contrasena", "")

    # Validar campos básicos
    if not nombre or not correo or not contrasena:
        flash("Completa todos los campos obligatorios.", "error")
        return redirect(url_for("registro"))

    if len(nombre) > 100 or len(correo) > 150:
        flash("El nombre o correo es demasiado largo.", "error")
        return redirect(url_for("registro"))

    if len(contrasena) < 8:
        flash("La contraseña debe tener al menos 8 caracteres.", "error")
        return redirect(url_for("registro"))

    if contrasena != confirmar:
        flash("Las contraseñas no coinciden.", "error")
        return redirect(url_for("registro"))

    # Validar estructura y dominios reales autorizados (Google, Microsoft, Yahoo, Apple)
    valido, mensaje_val = es_correo_valido(correo)
    if not valido:
        flash(mensaje_val, "error")
        return redirect(url_for("registro"))

    conexion = None
    cursor = None

    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)

        # Comprobar si el correo ya existe
        cursor.execute(
            "SELECT id_cliente, correo_verificado FROM CLIENTE WHERE correo = %s",
            (correo,)
        )
        cliente_existente = cursor.fetchone()

        if cliente_existente:
            # Comprobar si ya está verificado
            esta_verificado = cliente_existente.get("correo_verificado") in (1, True, "1")
            if esta_verificado:
                flash(
                    "Este correo ya está registrado y verificado. Inicia sesión con tu cuenta.",
                    "error"
                )
                return redirect(url_for("login"))
            else:
                # Actualizar contraseña y nombre si estaba pendiente de verificación
                contrasena_hash = generate_password_hash(contrasena)
                cursor.execute(
                    "UPDATE CLIENTE SET nombre = %s, contrasena = %s WHERE correo = %s",
                    (nombre, contrasena_hash, correo)
                )
        else:
            # Encriptar la contraseña mediante hash y guardar con correo_verificado = 0
            contrasena_hash = generate_password_hash(contrasena)
            consulta = """
                INSERT INTO CLIENTE
                (nombre, correo, contrasena, correo_verificado)
                VALUES (%s, %s, %s, 0)
            """
            cursor.execute(
                consulta,
                (nombre, correo, contrasena_hash)
            )

        # Generar código OTP seguro de 6 dígitos
        codigo_otp = f"{secrets.randbelow(900000) + 100000}"
        expiracion = datetime.now() + timedelta(minutes=15)

        # Invalidar códigos anteriores no utilizados para este correo
        cursor.execute(
            "UPDATE CODIGO_VERIFICACION SET usado = 1 WHERE correo = %s AND usado = 0",
            (correo,)
        )

        # Guardar nuevo código de verificación
        cursor.execute(
            """
            INSERT INTO CODIGO_VERIFICACION
            (correo, codigo, tipo, intentos, usado, expira_en)
            VALUES (%s, %s, 'REGISTRO', 0, 0, %s)
            """,
            (correo, codigo_otp, expiracion)
        )

        conexion.commit()

        # Enviar correo de verificación asíncrono con el código
        try:
            enviar_correo_codigo_verificacion(correo, nombre, codigo_otp)
        except Exception as err_correo:
            app.logger.warning("No se pudo disparar el correo de verificación: %s", err_correo)

        # Establecer estado en sesión del servidor (NUNCA enviar el código al cliente)
        session["correo_pendiente_verificacion"] = correo
        session["nombre_pendiente_verificacion"] = nombre
        session["codigo_reenvio_tiempo"] = time_module.time()

        flash(
            "¡Casi listo! Hemos enviado un código de 6 dígitos a tu correo para verificar tu cuenta.",
            "info"
        )
        return redirect(url_for("verificar_correo_pantalla"))

    except Exception as e:
        if conexion:
            conexion.rollback()
        app.logger.error("Error al registrar cliente: %s", e)
        flash(
            "No se pudo completar el registro. Intenta nuevamente.",
            "error"
        )
        return redirect(url_for("registro"))

    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


# ==========================================
# PANTALLA DE VERIFICACIÓN DE CÓDIGO
# ==========================================

@app.route("/verificar-correo", methods=["GET"])
def verificar_correo_pantalla():
    correo = session.get("correo_pendiente_verificacion")
    if not correo:
        flash("Ingresa tus datos de registro para verificar tu correo.", "info")
        return redirect(url_for("registro"))

    # Ocultar parcialmente el correo para presentación segura
    partes = correo.split("@")
    usuario_raw = partes[0]
    dominio_raw = partes[1] if len(partes) > 1 else ""
    if len(usuario_raw) > 3:
        correo_oculto = f"{usuario_raw[:2]}***{usuario_raw[-1]}@{dominio_raw}"
    else:
        correo_oculto = f"{usuario_raw[0]}***@{dominio_raw}"

    return render_template(
        "verificar_correo.html",
        correo=correo,
        correo_oculto=correo_oculto
    )


# ==========================================
# VERIFICAR CÓDIGO (POST / API)
# ==========================================

@app.route("/verificar-codigo", methods=["POST"])
def verificar_codigo():
    correo = session.get("correo_pendiente_verificacion")
    if not correo:
        mensaje_sesion = "Tu sesión de verificación ha expirado. Por favor regístrate nuevamente."
        if request.is_json:
            return jsonify({"ok": False, "mensaje": mensaje_sesion, "redirect": url_for("registro")}), 400
        flash(mensaje_sesion, "error")
        return redirect(url_for("registro"))

    # Obtener el código enviado (soporta JSON o Formulario)
    datos = request.get_json(silent=True) or {}
    codigo_ingresado = (datos.get("codigo") if request.is_json else request.form.get("codigo", "")).strip()

    if not codigo_ingresado or len(codigo_ingresado) != 6 or not codigo_ingresado.isdigit():
        msg = "Ingresa un código numérico válido de 6 dígitos."
        if request.is_json:
            return jsonify({"ok": False, "mensaje": msg}), 400
        flash(msg, "error")
        return redirect(url_for("verificar_correo_pantalla"))

    conexion = None
    cursor = None

    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)

        # Buscar el código activo más reciente para este correo
        consulta = """
            SELECT id_codigo, codigo, intentos, expira_en
            FROM CODIGO_VERIFICACION
            WHERE correo = %s AND usado = 0
            ORDER BY id_codigo DESC
            LIMIT 1
        """
        cursor.execute(consulta, (correo,))
        registro_codigo = cursor.fetchone()

        if not registro_codigo:
            msg = "No hay ningún código de verificación activo. Haz clic en 'Reenviar código'."
            if request.is_json:
                return jsonify({"ok": False, "mensaje": msg}), 400
            flash(msg, "error")
            return redirect(url_for("verificar_correo_pantalla"))

        # Validar límite de intentos fallidos
        intentos = registro_codigo.get("intentos", 0)
        if intentos >= 5:
            msg = "Has superado el número de intentos permitidos (5). Solicita un nuevo código."
            if request.is_json:
                return jsonify({"ok": False, "mensaje": msg}), 400
            flash(msg, "error")
            return redirect(url_for("verificar_correo_pantalla"))

        # Validar tiempo de expiración
        expira_en = registro_codigo.get("expira_en")
        if isinstance(expira_en, str):
            try:
                expira_en = datetime.fromisoformat(expira_en)
            except Exception:
                pass

        if expira_en and datetime.now() > expira_en:
            msg = "El código ha expirado (validez de 15 minutos). Por favor solicita uno nuevo."
            if request.is_json:
                return jsonify({"ok": False, "mensaje": msg}), 400
            flash(msg, "error")
            return redirect(url_for("verificar_correo_pantalla"))

        # Comparación segura de tiempo constante para evitar fugas de información
        codigo_guardado = str(registro_codigo.get("codigo", "")).strip()
        if not secrets.compare_digest(codigo_guardado, codigo_ingresado):
            cursor.execute(
                "UPDATE CODIGO_VERIFICACION SET intentos = intentos + 1 WHERE id_codigo = %s",
                (registro_codigo["id_codigo"],)
            )
            conexion.commit()
            intentos_restantes = max(0, 4 - intentos)
            msg = f"El código ingresado es incorrecto. Intentos restantes: {intentos_restantes}."
            if request.is_json:
                return jsonify({"ok": False, "mensaje": msg}), 400
            flash(msg, "error")
            return redirect(url_for("verificar_correo_pantalla"))

        # ¡CÓDIGO CORRECTO! Marcar código como usado y activar cliente
        cursor.execute(
            "UPDATE CODIGO_VERIFICACION SET usado = 1 WHERE id_codigo = %s",
            (registro_codigo["id_codigo"],)
        )
        cursor.execute(
            "UPDATE CLIENTE SET correo_verificado = 1 WHERE correo = %s",
            (correo,)
        )
        conexion.commit()

        nombre_cliente = session.get("nombre_pendiente_verificacion", "")

        # Enviar correo de bienvenida al confirmar el correo con éxito
        try:
            enviar_correo_bienvenida(correo, nombre_cliente)
        except Exception as err_correo:
            app.logger.warning("No se pudo disparar el correo de bienvenida: %s", err_correo)

        # Limpiar variables temporales de sesión
        session.pop("correo_pendiente_verificacion", None)
        session.pop("nombre_pendiente_verificacion", None)
        session.pop("codigo_reenvio_tiempo", None)

        flash("¡Excelente! Tu correo ha sido verificado con éxito 💗. Ya puedes iniciar sesión con tu cuenta.", "success")

        if request.is_json:
            return jsonify({
                "ok": True,
                "mensaje": "¡Verificación exitosa! Redirigiendo...",
                "redirect": url_for("login")
            })

        return redirect(url_for("login"))

    except Exception as e:
        if conexion:
            conexion.rollback()
        app.logger.error("Error al verificar código: %s", e)
        msg = "Ocurrió un problema al procesar la verificación. Intenta nuevamente."
        if request.is_json:
            return jsonify({"ok": False, "mensaje": msg}), 500
        flash(msg, "error")
        return redirect(url_for("verificar_correo_pantalla"))

    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


# ==========================================
# REENVIAR CÓDIGO DE VERIFICACIÓN
# ==========================================

@app.route("/reenviar-codigo", methods=["POST"])
def reenviar_codigo():
    correo = session.get("correo_pendiente_verificacion")
    nombre = session.get("nombre_pendiente_verificacion", "")

    if not correo:
        return jsonify({
            "ok": False,
            "mensaje": "Sesión vencida. Vuelve a iniciar el registro."
        }), 400

    # Rate limiting para evitar saturación de correos (cooldown de 45s)
    ahora = time_module.time()
    ultimo_envio = session.get("codigo_reenvio_tiempo", 0)
    tiempo_transcurrido = ahora - ultimo_envio

    if tiempo_transcurrido < 45:
        segundos_espera = int(45 - tiempo_transcurrido)
        return jsonify({
            "ok": False,
            "mensaje": f"Por favor espera {segundos_espera} segundos antes de solicitar un nuevo código."
        }), 429

    conexion = None
    cursor = None

    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor()

        # Generar nuevo código de 6 dígitos
        nuevo_codigo = f"{secrets.randbelow(900000) + 100000}"
        expiracion = datetime.now() + timedelta(minutes=15)

        # Invalidar anteriores
        cursor.execute(
            "UPDATE CODIGO_VERIFICACION SET usado = 1 WHERE correo = %s AND usado = 0",
            (correo,)
        )

        cursor.execute(
            """
            INSERT INTO CODIGO_VERIFICACION
            (correo, codigo, tipo, intentos, usado, expira_en)
            VALUES (%s, %s, 'REGISTRO', 0, 0, %s)
            """,
            (correo, nuevo_codigo, expiracion)
        )
        conexion.commit()

        # Enviar correo asíncrono
        enviar_correo_codigo_verificacion(correo, nombre, nuevo_codigo)

        session["codigo_reenvio_tiempo"] = ahora

        return jsonify({
            "ok": True,
            "mensaje": "¡Hemos enviado un nuevo código de seguridad a tu correo electrónico!"
        })

    except Exception as e:
        if conexion:
            conexion.rollback()
        app.logger.error("Error al reenviar código: %s", e)
        return jsonify({
            "ok": False,
            "mensaje": "No se pudo reenviar el código. Intenta nuevamente."
        }), 500

    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


# ==========================================
# INICIAR SESIÓN
# ==========================================

@app.route("/iniciar-sesion", methods=["POST"])
def iniciar_sesion():

    correo = request.form.get("correo", "").strip().lower()
    contrasena = request.form.get("contrasena", "")

    if not correo or not contrasena:
        flash("Ingresa tu correo y contraseña.", "error")
        return redirect(url_for("login"))

    conexion = None
    cursor = None

    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)

        # Buscar el cliente en la base de datos
        consulta = """
            SELECT id_cliente, nombre, correo, contrasena, correo_verificado
            FROM CLIENTE
            WHERE correo = %s
        """

        cursor.execute(consulta, (correo,))
        cliente = cursor.fetchone()

        if cliente and check_password_hash(
            cliente["contrasena"],
            contrasena
        ):
            # Comprobar si el correo ya fue verificado
            if cliente.get("correo_verificado") in (0, False, "0"):
                codigo_otp = f"{secrets.randbelow(900000) + 100000}"
                expiracion = datetime.now() + timedelta(minutes=15)
                cursor.execute(
                    "UPDATE CODIGO_VERIFICACION SET usado = 1 WHERE correo = %s AND usado = 0",
                    (correo,)
                )
                cursor.execute(
                    """
                    INSERT INTO CODIGO_VERIFICACION
                    (correo, codigo, tipo, intentos, usado, expira_en)
                    VALUES (%s, %s, 'REGISTRO', 0, 0, %s)
                    """,
                    (correo, codigo_otp, expiracion)
                )
                conexion.commit()

                try:
                    enviar_correo_codigo_verificacion(correo, cliente["nombre"], codigo_otp)
                except Exception as err_env:
                    app.logger.warning("No se pudo enviar código al iniciar sesión: %s", err_env)

                session["correo_pendiente_verificacion"] = correo
                session["nombre_pendiente_verificacion"] = cliente["nombre"]
                session["codigo_reenvio_tiempo"] = time_module.time()

                flash("Debes verificar tu correo para activar tu cuenta. Te enviamos un nuevo código.", "warning")
                return redirect(url_for("verificar_correo_pantalla"))

            # Crear sesión única para el cliente
            session.clear()

            session["id_cliente"] = cliente["id_cliente"]
            session["nombre_cliente"] = cliente["nombre"]
            session["correo_cliente"] = cliente["correo"]

            # Enviar correo de notificación de inicio de sesión exitoso
            try:
                enviar_correo_inicio_sesion(cliente["correo"], cliente["nombre"])
            except Exception as err_correo:
                app.logger.warning("No se pudo disparar el correo de inicio de sesión: %s", err_correo)

            flash(
                "¡Bienvenido a TWINS Bakery, "
                + cliente["nombre"] + "! 💗",
                "success"
            )

            return redirect(url_for("inicio"))

        flash(
            "Correo o contraseña incorrectos.",
            "error"
        )

        return redirect(url_for("login"))

    except Exception as e:
        app.logger.error("Error al iniciar sesión: %s", e)

        flash(
            "Ocurrió un problema al verificar tus datos.",
            "error"
        )

        return redirect(url_for("login"))

    finally:

        if cursor:
            cursor.close()

        if conexion and conexion.is_connected():
            conexion.close()



# ==========================================
# RECUPERACIÓN DE CONTRASEÑA (CLIENTE)
# ==========================================

def _enmascarar_correo(correo):
    if not correo or "@" not in correo:
        return correo or ""
    partes = correo.split("@", 1)
    usuario, dominio = partes[0], partes[1]
    if len(usuario) <= 2:
        oculto = usuario[0] + "***"
    else:
        oculto = usuario[0] + "***" + usuario[-1]
    return f"{oculto}@{dominio}"


@app.route("/olvide-contrasena", methods=["GET"])
def olvide_contrasena():
    return render_template("olvide_contrasena.html")


@app.route("/solicitar-recuperacion-contrasena", methods=["POST"])
def solicitar_recuperacion_contrasena():
    correo = request.form.get("correo", "").strip().lower()

    if not correo:
        flash("Por favor ingresa tu correo electrónico registrado.", "error")
        return redirect(url_for("olvide_contrasena"))

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)

        cursor.execute(
            "SELECT id_cliente, nombre, correo FROM CLIENTE WHERE LOWER(correo) = %s",
            (correo,)
        )
        cliente = cursor.fetchone()

        if not cliente:
            flash("No encontramos ninguna cuenta asociada a este correo electrónico. Por favor verifica tus datos.", "error")
            return redirect(url_for("olvide_contrasena"))

        # Generar código OTP de 6 dígitos seguro
        codigo_otp = f"{secrets.randbelow(900000) + 100000}"
        expiracion = datetime.now() + timedelta(minutes=15)

        # Invalidar solicitudes anteriores
        cursor.execute(
            "UPDATE CODIGO_VERIFICACION SET usado = 1 WHERE correo = %s AND tipo = 'RECUPERACION' AND usado = 0",
            (correo,)
        )

        cursor.execute(
            """
            INSERT INTO CODIGO_VERIFICACION
                (correo, codigo, tipo, intentos, usado, expira_en)
            VALUES (%s, %s, 'RECUPERACION', 0, 0, %s)
            """,
            (correo, codigo_otp, expiracion)
        )
        conexion.commit()

        # Enviar correo asíncrono
        try:
            enviar_correo_recuperacion_contrasena(correo, cliente["nombre"], codigo_otp)
        except Exception as err_mail:
            app.logger.warning("No se pudo enviar correo de recuperación: %s", err_mail)

        session["correo_recuperacion"] = correo
        session["nombre_recuperacion"] = cliente["nombre"]
        session["recuperacion_reenvio_tiempo"] = time_module.time()
        session["codigo_recuperacion_aprobado"] = False

        flash("¡Código de seguridad enviado! Revisa tu bandeja de entrada o carpeta de spam.", "success")
        return redirect(url_for("verificar_codigo_recuperacion"))

    except Exception as e:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al solicitar recuperación de contraseña: %s", e)
        flash("Ocurrió un error al procesar tu solicitud. Por favor intenta nuevamente.", "error")
        return redirect(url_for("olvide_contrasena"))
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/verificar-codigo-recuperacion", methods=["GET", "POST"])
def verificar_codigo_recuperacion():
    correo = session.get("correo_recuperacion")
    if not correo:
        flash("La sesión de recuperación ha vencido. Por favor ingresa tu correo nuevamente.", "warning")
        return redirect(url_for("olvide_contrasena"))

    if request.method == "GET":
        return render_template(
            "verificar_codigo_recuperacion.html",
            correo_oculto=_enmascarar_correo(correo)
        )

    codigo_ingresado = request.form.get("codigo", "").strip()
    if not codigo_ingresado:
        flash("Por favor ingresa el código de 6 dígitos que recibiste por correo.", "error")
        return redirect(url_for("verificar_codigo_recuperacion"))

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT id_codigo, codigo, intentos, expira_en
            FROM CODIGO_VERIFICACION
            WHERE correo = %s AND tipo = 'RECUPERACION' AND usado = 0
            ORDER BY id_codigo DESC
            LIMIT 1
            """,
            (correo,)
        )
        registro = cursor.fetchone()

        if not registro:
            flash("No encontramos ningún código de recuperación pendiente o ya venció. Solicita uno nuevo.", "error")
            return redirect(url_for("olvide_contrasena"))

        # Validar intentos máximos (5)
        if registro.get("intentos", 0) >= 5:
            cursor.execute("UPDATE CODIGO_VERIFICACION SET usado = 1 WHERE id_codigo = %s", (registro["id_codigo"],))
            conexion.commit()
            flash("Has superado el número de intentos permitidos. Solicita un nuevo código de seguridad.", "error")
            return redirect(url_for("olvide_contrasena"))

        # Validar expiración
        expira_en = registro["expira_en"]
        if isinstance(expira_en, str):
            try:
                expira_en = datetime.fromisoformat(expira_en)
            except Exception:
                pass
        if isinstance(expira_en, datetime) and datetime.now() > expira_en:
            cursor.execute("UPDATE CODIGO_VERIFICACION SET usado = 1 WHERE id_codigo = %s", (registro["id_codigo"],))
            conexion.commit()
            flash("El código ha vencido (validez de 15 minutos). Por favor solicita uno nuevo.", "error")
            return redirect(url_for("olvide_contrasena"))

        # Validar coincidencia de código
        if str(registro["codigo"]).strip() != codigo_ingresado:
            cursor.execute(
                "UPDATE CODIGO_VERIFICACION SET intentos = intentos + 1 WHERE id_codigo = %s",
                (registro["id_codigo"],)
            )
            conexion.commit()
            intentos_restantes = max(0, 5 - (registro.get("intentos", 0) + 1))
            flash(f"El código ingresado es incorrecto. Te quedan {intentos_restantes} intento(s).", "error")
            return redirect(url_for("verificar_codigo_recuperacion"))

        # Código correcto: marcarlo usado y aprobar el cambio de contraseña
        cursor.execute("UPDATE CODIGO_VERIFICACION SET usado = 1 WHERE id_codigo = %s", (registro["id_codigo"],))
        conexion.commit()

        session["codigo_recuperacion_aprobado"] = True
        flash("Código verificado exitosamente. Ahora crea tu nueva contraseña.", "success")
        return redirect(url_for("nueva_contrasena"))

    except Exception as e:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al verificar código de recuperación: %s", e)
        flash("Ocurrió un error al verificar el código. Intenta nuevamente.", "error")
        return redirect(url_for("verificar_codigo_recuperacion"))
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/reenviar-codigo-recuperacion", methods=["POST"])
def reenviar_codigo_recuperacion():
    correo = session.get("correo_recuperacion")
    nombre = session.get("nombre_recuperacion", "Cliente")

    if not correo:
        return jsonify({
            "ok": False,
            "mensaje": "Sesión vencida. Vuelve a ingresar tu correo."
        }), 400

    ahora = time_module.time()
    ultimo_envio = session.get("recuperacion_reenvio_tiempo", 0)
    tiempo_transcurrido = ahora - ultimo_envio

    if tiempo_transcurrido < 45:
        segundos_espera = int(45 - tiempo_transcurrido)
        return jsonify({
            "ok": False,
            "mensaje": f"Por favor espera {segundos_espera} segundos antes de solicitar un nuevo código."
        }), 429

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor()

        nuevo_codigo = f"{secrets.randbelow(900000) + 100000}"
        expiracion = datetime.now() + timedelta(minutes=15)

        cursor.execute(
            "UPDATE CODIGO_VERIFICACION SET usado = 1 WHERE correo = %s AND tipo = 'RECUPERACION' AND usado = 0",
            (correo,)
        )
        cursor.execute(
            """
            INSERT INTO CODIGO_VERIFICACION
                (correo, codigo, tipo, intentos, usado, expira_en)
            VALUES (%s, %s, 'RECUPERACION', 0, 0, %s)
            """,
            (correo, nuevo_codigo, expiracion)
        )
        conexion.commit()

        enviar_correo_recuperacion_contrasena(correo, nombre, nuevo_codigo)
        session["recuperacion_reenvio_tiempo"] = ahora

        return jsonify({
            "ok": True,
            "mensaje": "¡Hemos enviado un nuevo código de seguridad a tu correo electrónico!"
        })

    except Exception as e:
        if conexion:
            conexion.rollback()
        app.logger.warning("Error al reenviar código de recuperación: %s", e)
        return jsonify({
            "ok": False,
            "mensaje": "No se pudo reenviar el código. Intenta nuevamente."
        }), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/nueva-contrasena", methods=["GET"])
def nueva_contrasena():
    correo = session.get("correo_recuperacion")
    aprobado = session.get("codigo_recuperacion_aprobado")

    if not correo or not aprobado:
        flash("Por seguridad, debes verificar tu código antes de crear una nueva contraseña.", "warning")
        return redirect(url_for("olvide_contrasena"))

    return render_template("nueva_contrasena.html", correo=correo)


@app.route("/guardar-nueva-contrasena", methods=["POST"])
def guardar_nueva_contrasena():
    correo = session.get("correo_recuperacion")
    aprobado = session.get("codigo_recuperacion_aprobado")
    nombre = session.get("nombre_recuperacion", "Cliente")

    if not correo or not aprobado:
        flash("Tu sesión de recuperación no es válida o ha vencido. Intenta de nuevo.", "error")
        return redirect(url_for("login"))

    nueva_pwd = request.form.get("nueva_contrasena", "")
    confirmar_pwd = request.form.get("confirmar_contrasena", "")

    if not nueva_pwd or len(nueva_pwd) < 8:
        flash("La nueva contraseña debe tener al menos 8 caracteres.", "error")
        return redirect(url_for("nueva_contrasena"))

    if nueva_pwd != confirmar_pwd:
        flash("Las contraseñas ingresadas no coinciden.", "error")
        return redirect(url_for("nueva_contrasena"))

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor()

        hash_nueva = generate_password_hash(nueva_pwd)
        cursor.execute(
            "UPDATE CLIENTE SET contrasena = %s WHERE LOWER(correo) = %s",
            (hash_nueva, correo.lower())
        )
        conexion.commit()

        # Enviar correo de notificación de contraseña actualizada
        try:
            enviar_correo_contrasena_actualizada(correo, nombre)
        except Exception as err_mail:
            app.logger.warning("No se pudo notificar contraseña actualizada por correo: %s", err_mail)

        # Limpiar variables de recuperación de la sesión
        session.pop("correo_recuperacion", None)
        session.pop("nombre_recuperacion", None)
        session.pop("codigo_recuperacion_aprobado", None)
        session.pop("recuperacion_reenvio_tiempo", None)

        flash("¡Tu contraseña ha sido restablecida con éxito! Ya puedes iniciar sesión.", "success")
        return redirect(url_for("login"))

    except Exception as e:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al guardar nueva contraseña: %s", e)
        flash("Ocurrió un error al guardar la nueva contraseña. Por favor intenta nuevamente.", "error")
        return redirect(url_for("nueva_contrasena"))
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/restablecer-contrasena", methods=["GET", "POST"])
def restablecer_contrasena():
    correo = session.get("correo_recuperacion")
    if not correo:
        flash("Ingresa tu correo para comenzar la recuperación.", "warning")
        return redirect(url_for("olvide_contrasena"))

    if request.method == "GET":
        return render_template(
            "restablecer_contrasena.html",
            correo_oculto=_enmascarar_correo(correo)
        )

    # Si se envía por POST directo a restablecer_contrasena
    codigo = request.form.get("codigo", "").strip()
    nueva_pwd = request.form.get("nueva_contrasena", "")
    confirmar_pwd = request.form.get("confirmar_contrasena", "")

    if not codigo or not nueva_pwd or len(nueva_pwd) < 8:
        flash("Ingresa el código de 6 dígitos y una contraseña de mínimo 8 caracteres.", "error")
        return redirect(url_for("restablecer_contrasena"))

    if nueva_pwd != confirmar_pwd:
        flash("Las contraseñas no coinciden.", "error")
        return redirect(url_for("restablecer_contrasena"))

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT id_codigo, codigo, expira_en
            FROM CODIGO_VERIFICACION
            WHERE correo = %s AND tipo = 'RECUPERACION' AND usado = 0
            ORDER BY id_codigo DESC LIMIT 1
            """,
            (correo,)
        )
        registro = cursor.fetchone()

        if not registro or str(registro["codigo"]).strip() != codigo:
            flash("Código de seguridad incorrecto o vencido.", "error")
            return redirect(url_for("restablecer_contrasena"))

        cursor.execute("UPDATE CODIGO_VERIFICACION SET usado = 1 WHERE id_codigo = %s", (registro["id_codigo"],))
        hash_nueva = generate_password_hash(nueva_pwd)
        cursor.execute("UPDATE CLIENTE SET contrasena = %s WHERE LOWER(correo) = %s", (hash_nueva, correo.lower()))
        conexion.commit()

        nombre = session.get("nombre_recuperacion", "Cliente")
        try:
            enviar_correo_contrasena_actualizada(correo, nombre)
        except Exception:
            pass

        session.pop("correo_recuperacion", None)
        session.pop("nombre_recuperacion", None)
        session.pop("codigo_recuperacion_aprobado", None)

        flash("¡Tu contraseña ha sido restablecida con éxito! Ya puedes iniciar sesión.", "success")
        return redirect(url_for("login"))
    except Exception as e:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al restablecer contraseña: %s", e)
        flash("Error al procesar el cambio de contraseña.", "error")
        return redirect(url_for("restablecer_contrasena"))
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


# ==========================================
# MÓDULO DE FIDELIDAD DEL CLIENTE Y ADMINISTRACIÓN
# ==========================================

@app.route("/fidelidad")
@cliente_requerido
def fidelidad():
    """Pantalla principal de Fidelidad para clientes con progreso circular, vitrina de canje e historial."""
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    id_cliente = session.get("id_cliente")
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)

        # 1. Obtener datos del cliente
        cursor.execute(
            """
            SELECT id_cliente, nombre, correo, COALESCE(telefono, '') AS telefono,
                   COALESCE(correo_verificado, 1) AS correo_verificado,
                   fecha_registro, COALESCE(puntos_fidelidad, 0) AS puntos_fidelidad
            FROM CLIENTE
            WHERE id_cliente = %s
            """,
            (id_cliente,),
        )
        cliente_row = cursor.fetchone()
        if not cliente_row:
            flash("Cliente no encontrado.", "error")
            return redirect(url_for("inicio"))

        cliente = {
            "id": cliente_row["id_cliente"],
            "nombre": cliente_row["nombre"],
            "correo": cliente_row["correo"],
            "telefono": cliente_row["telefono"] or "No registrado",
            "correo_verificado": bool(cliente_row.get("correo_verificado", True)),
            "fecha_registro": str(cliente_row.get("fecha_registro") or "2026")[:10],
            "puntos_fidelidad": int(cliente_row.get("puntos_fidelidad", 0) or 0),
        }

        # 2. Obtener productos de vitrina canjeables
        cursor.execute(
            """
            SELECT id_producto, nombre, descripcion, categoria, precio,
                   canjeable_puntos, COALESCE(puntos_canje, 50) AS puntos_canje,
                   genera_puntos, imagen, tipo_imagen
            FROM PRODUCTO
            WHERE canjeable_puntos = 1 AND disponible = 1
            ORDER BY puntos_canje ASC, nombre ASC
            """
        )
        productos_canjeables = [_producto_publico(p) for p in cursor.fetchall()]

        # 3. Obtener historial de movimientos del cliente
        cursor.execute(
            """
            SELECT id_historial,
                   COALESCE(fecha, fecha_registro) AS fecha,
                   COALESCE(motivo, descripcion) AS motivo,
                   puntos, saldo_resultante,
                   COALESCE(tipo_movimiento, tipo) AS tipo_movimiento
            FROM HISTORIAL_PUNTOS
            WHERE id_cliente = %s
            ORDER BY id_historial DESC
            LIMIT 100
            """,
            (id_cliente,),
        )
        movimientos_raw = cursor.fetchall() or []
        movimientos = []
        for m in movimientos_raw:
            f = m.get("fecha")
            if hasattr(f, "strftime"):
                fecha_str = f.strftime("%d/%m/%Y %H:%M")
            else:
                fecha_str = str(f)[:16] if f else ""
            movimientos.append({
                "fecha": fecha_str,
                "motivo": m.get("motivo") or ("Acumulación de puntos" if m["puntos"] > 0 else "Canje de producto"),
                "puntos": int(m.get("puntos") or 0),
                "saldo_resultante": int(m.get("saldo_resultante") or 0),
            })

        return render_template(
            "fidelidad.html",
            cliente=cliente,
            productos_canjeables=productos_canjeables,
            movimientos=movimientos,
            csrf_token=session["csrf_token"],
        )
    except mysql.connector.Error as error:
        _error_base_datos(error, "No se pudo cargar la pantalla de fidelidad.")
        flash("Ocurrió un error al cargar tu información de fidelidad.", "error")
        return redirect(url_for("inicio"))
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/fidelidad/canjear", methods=["POST"])
@cliente_requerido
def api_fidelidad_canjear():
    """Procesa el canje de un producto por puntos, descuenta el saldo y genera orden Canje por Fidelidad."""
    if not _csrf_valido():
        return jsonify({"ok": False, "error": "La sesión de seguridad venció. Recarga la página."}), 403

    id_cliente = session.get("id_cliente")
    datos = request.get_json(silent=True) or {}
    producto_id = datos.get("producto_id")
    fecha_retiro_str = datos.get("fecha_retiro")

    if not producto_id:
        return jsonify({"ok": False, "error": "Debes seleccionar un producto válido para canjear."}), 400

    try:
        producto_id = int(producto_id)
    except (ValueError, TypeError):
        return jsonify({"ok": False, "error": "Identificador de producto no válido."}), 400

    ahora = datetime.now()
    if fecha_retiro_str:
        try:
            fecha_retiro = datetime.fromisoformat(fecha_retiro_str)
            if fecha_retiro < ahora:
                fecha_retiro = ahora + timedelta(days=1)
        except Exception:
            fecha_retiro = ahora + timedelta(days=1)
    else:
        fecha_retiro = ahora + timedelta(days=1)

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        conexion.start_transaction()
        cursor = conexion.cursor(dictionary=True)

        # 1. Validar y bloquear al cliente
        cursor.execute(
            """
            SELECT id_cliente, nombre, correo, telefono, COALESCE(puntos_fidelidad, 0) AS puntos_fidelidad
            FROM CLIENTE
            WHERE id_cliente = %s
            FOR UPDATE
            """,
            (id_cliente,),
        )
        cliente = cursor.fetchone()
        if not cliente:
            conexion.rollback()
            return jsonify({"ok": False, "error": "Cliente no encontrado."}), 404

        saldo_actual = int(cliente.get("puntos_fidelidad") or 0)

        # 2. Validar y bloquear el producto
        cursor.execute(
            """
            SELECT id_producto, nombre, descripcion, categoria, precio,
                   canjeable_puntos, COALESCE(puntos_canje, 50) AS puntos_canje, disponible
            FROM PRODUCTO
            WHERE id_producto = %s
            FOR UPDATE
            """,
            (producto_id,),
        )
        producto = cursor.fetchone()
        if not producto or not producto.get("canjeable_puntos") or not producto.get("disponible"):
            conexion.rollback()
            return jsonify({"ok": False, "error": "Este producto no está disponible para canje por puntos."}), 400

        puntos_requeridos = max(50, int(producto.get("puntos_canje") or 50))

        # 3. Verificar si posee suficientes puntos
        if saldo_actual < puntos_requeridos:
            faltan = puntos_requeridos - saldo_actual
            conexion.rollback()
            return jsonify({
                "ok": False,
                "error": f"Puntos insuficientes. Posees {saldo_actual} puntos y necesitas {puntos_requeridos}. Te faltan {faltan} puntos adicionales para canjear este postre."
            }), 400

        # 4. Descontar puntos al cliente
        nuevo_saldo = saldo_actual - puntos_requeridos
        cursor.execute(
            "UPDATE CLIENTE SET puntos_fidelidad = %s WHERE id_cliente = %s",
            (nuevo_saldo, id_cliente),
        )

        # 5. Generar orden especial "Canje por Fidelidad" en RESERVA
        codigo_reserva = f"CJ-{secrets.token_hex(3).upper()}"
        cursor.execute(
            """
            INSERT INTO RESERVA (
                codigo, id_cliente, fecha_reserva, fecha_retiro, estado,
                nombre_cliente, correo, telefono, total, anticipo_requerido,
                monto_pagado, es_canje_fidelidad, puntos_usados, puntos_otorgados
            ) VALUES (
                %s, %s, %s, %s, 'CONFIRMADA',
                %s, %s, %s, 0.00, 0.00,
                0.00, 1, %s, 1
            )
            """,
            (
                codigo_reserva, id_cliente, ahora, fecha_retiro,
                cliente["nombre"], cliente["correo"], cliente.get("telefono") or "7000-0000",
                puntos_requeridos
            ),
        )
        id_reserva = cursor.lastrowid

        # 6. Detalle de reserva
        cursor.execute(
            """
            INSERT INTO DETALLE_RESERVA (
                id_reserva, id_pastel, nombre_producto, precio_unitario, cantidad
            ) VALUES (%s, %s, %s, 0.00, 1)
            """,
            (id_reserva, producto["id_producto"], f"🎁 [Canje Fidelidad] {producto['nombre']}"),
        )

        # 7. Registrar pago simbólico liquidado
        ref_pago = f"CANJE-{codigo_reserva}"
        cursor.execute(
            """
            INSERT INTO PAGO (
                id_reserva, metodo_pago, monto, fecha_pago, estado, referencia
            ) VALUES (%s, 'FIDELIDAD', 0.00, NOW(), 'PAGADO', %s)
            """,
            (id_reserva, ref_pago),
        )

        # 8. Descontar inventario si existe registro
        cursor.execute(
            "SELECT id_inventario, stock FROM INVENTARIO WHERE id_pastel = %s FOR UPDATE",
            (producto["id_producto"],),
        )
        inv = cursor.fetchone()
        if inv and inv.get("stock", 0) > 0:
            cursor.execute(
                "UPDATE INVENTARIO SET stock = stock - 1 WHERE id_inventario = %s",
                (inv["id_inventario"],),
            )
            cursor.execute(
                """
                INSERT INTO MOVIMIENTO_INVENTARIO (id_inventario, cantidad, tipo_movimiento)
                VALUES (%s, -1, 'CANJE_FIDELIDAD')
                """,
                (inv["id_inventario"],),
            )

        # 9. Registrar en CANJE_FIDELIDAD
        cursor.execute(
            """
            INSERT INTO CANJE_FIDELIDAD (
                id_cliente, id_producto, id_reserva, puntos_usados, fecha_canje, estado
            ) VALUES (%s, %s, %s, %s, NOW(), 'CONFIRMADA')
            """,
            (id_cliente, producto["id_producto"], id_reserva, puntos_requeridos),
        )

        # 10. Registrar en HISTORIAL_PUNTOS
        motivo_canje = f"Canje de producto: -{puntos_requeridos} puntos ({producto['nombre']})"
        cursor.execute(
            """
            INSERT INTO HISTORIAL_PUNTOS (
                id_cliente, id_reserva, id_producto, tipo, puntos, descripcion,
                saldo_resultante, fecha_registro, fecha, motivo, tipo_movimiento
            ) VALUES (
                %s, %s, %s, 'CANJE', %s, %s,
                %s, NOW(), NOW(), %s, 'CANJE'
            )
            """,
            (
                id_cliente, id_reserva, producto["id_producto"],
                -puntos_requeridos, motivo_canje,
                nuevo_saldo, motivo_canje
            ),
        )

        conexion.commit()

        fecha_canje_str = ahora.strftime("%d/%m/%Y %H:%M")
        return jsonify({
            "ok": True,
            "producto": producto["nombre"],
            "puntos_utilizados": puntos_requeridos,
            "puntos_restantes": nuevo_saldo,
            "fecha_canje": fecha_canje_str,
            "codigo_reserva": codigo_reserva,
            "mensaje": f"¡Felicidades! Has canjeado con éxito {producto['nombre']}.",
        })
    except Exception as e:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al procesar canje de fidelidad: %s", e)
        return jsonify({"ok": False, "error": "No se pudo procesar el canje de puntos. Inténtalo nuevamente."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/fidelidad/movimientos", methods=["GET"])
@cliente_requerido
def api_fidelidad_movimientos():
    """Consulta los movimientos de puntos del cliente autenticado."""
    id_cliente = session.get("id_cliente")
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id_historial,
                   COALESCE(fecha, fecha_registro) AS fecha,
                   COALESCE(motivo, descripcion) AS motivo,
                   puntos, saldo_resultante,
                   COALESCE(tipo_movimiento, tipo) AS tipo_movimiento
            FROM HISTORIAL_PUNTOS
            WHERE id_cliente = %s
            ORDER BY id_historial DESC
            """,
            (id_cliente,),
        )
        filas = cursor.fetchall() or []
        movimientos = []
        for f in filas:
            dt = f.get("fecha")
            fecha_str = dt.strftime("%d/%m/%Y %H:%M") if hasattr(dt, "strftime") else str(dt)[:16]
            movimientos.append({
                "id": f["id_historial"],
                "fecha": fecha_str,
                "motivo": f.get("motivo") or ("Acumulación" if f["puntos"] > 0 else "Canje"),
                "puntos": int(f.get("puntos") or 0),
                "saldo_resultante": int(f.get("saldo_resultante") or 0),
                "tipo_movimiento": f.get("tipo_movimiento") or ("ACUMULACION" if f["puntos"] > 0 else "CANJE"),
            })
        return jsonify({"ok": True, "movimientos": movimientos})
    except Exception as e:
        app.logger.exception("Error al consultar movimientos de fidelidad: %s", e)
        return jsonify({"ok": False, "error": "No se pudieron obtener los movimientos de puntos."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


# ── PANTALLAS INDEPENDIENTES DE ADMINISTRACIÓN: FIDELIDAD ──

@app.route("/admin/fidelidad")
@administrador_requerido
def admin_fidelidad():
    """Panel principal de Fidelidad con métricas y accesos rápidos a pantallas independientes."""
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    conexion = None
    cursor = None
    stats = {
        "total_puntos_emitidos": 0,
        "total_puntos_canjeados": 0,
        "total_canjes": 0,
        "canjes_pendientes": 0,
        "clientes_con_puntos": 0,
    }
    ultimos_canjes = []
    ultimos_movimientos = []
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN puntos > 0 THEN puntos ELSE 0 END), 0) AS emitidos,
                COALESCE(SUM(CASE WHEN puntos < 0 THEN ABS(puntos) ELSE 0 END), 0) AS canjeados
            FROM HISTORIAL_PUNTOS
            """
        )
        row_p = cursor.fetchone()
        if row_p:
            stats["total_puntos_emitidos"] = int(row_p.get("emitidos") or 0)
            stats["total_puntos_canjeados"] = int(row_p.get("canjeados") or 0)

        cursor.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN estado != 'ENTREGADA' AND estado != 'CANCELADA' THEN 1 ELSE 0 END) AS pendientes
            FROM CANJE_FIDELIDAD
            """
        )
        row_c = cursor.fetchone()
        if row_c:
            stats["total_canjes"] = int(row_c.get("total") or 0)
            stats["canjes_pendientes"] = int(row_c.get("pendientes") or 0)

        cursor.execute("SELECT COUNT(*) AS total FROM CLIENTE WHERE puntos_fidelidad > 0")
        row_cl = cursor.fetchone()
        if row_cl:
            stats["clientes_con_puntos"] = int(row_cl.get("total") or 0)

        # Últimos canjes
        cursor.execute(
            """
            SELECT c.id_canje, r.codigo, cl.nombre AS cliente, p.nombre AS producto,
                   c.puntos_usados, c.estado
            FROM CANJE_FIDELIDAD c
            JOIN RESERVA r ON r.id_reserva = c.id_reserva
            JOIN CLIENTE cl ON cl.id_cliente = c.id_cliente
            JOIN PRODUCTO p ON p.id_producto = c.id_producto
            ORDER BY c.id_canje DESC
            LIMIT 5
            """
        )
        ultimos_canjes = cursor.fetchall() or []

        # Últimos movimientos
        cursor.execute(
            """
            SELECT h.id_historial, cl.nombre AS cliente,
                   COALESCE(h.motivo, h.descripcion) AS motivo,
                   h.puntos, h.saldo_resultante,
                   COALESCE(h.fecha, h.fecha_registro) AS fecha
            FROM HISTORIAL_PUNTOS h
            JOIN CLIENTE cl ON cl.id_cliente = h.id_cliente
            ORDER BY h.id_historial DESC
            LIMIT 5
            """
        )
        ultimos_movimientos = cursor.fetchall() or []
    except Exception as e:
        app.logger.warning("Error al cargar dashboard de fidelidad: %s", e)
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()

    return render_template(
        "admin_fidelidad.html",
        stats=stats,
        ultimos_canjes=ultimos_canjes,
        ultimos_movimientos=ultimos_movimientos,
        csrf_token=session["csrf_token"],
        admin_email=session.get("admin_email", ""),
    )


@app.route("/admin/fidelidad/historial")
@administrador_requerido
def admin_fidelidad_historial():
    """Pantalla independiente para auditar la acumulación y descuento de puntos de todos los clientes."""
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return render_template(
        "admin_fidelidad_historial.html",
        csrf_token=session["csrf_token"],
        admin_email=session.get("admin_email", ""),
    )


@app.route("/admin/fidelidad/canjes")
@administrador_requerido
def admin_fidelidad_canjes():
    """Pantalla independiente para la gestión y entrega de productos canjeados por puntos."""
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return render_template(
        "admin_fidelidad_canjes.html",
        csrf_token=session["csrf_token"],
        admin_email=session.get("admin_email", ""),
    )


@app.route("/admin/fidelidad/configuracion")
@administrador_requerido
def admin_fidelidad_configuracion():
    """Pantalla independiente para configurar reglas y productos canjeables / acumulables."""
    session.setdefault("csrf_token", secrets.token_urlsafe(32))
    return render_template(
        "admin_fidelidad_configuracion.html",
        csrf_token=session["csrf_token"],
        admin_email=session.get("admin_email", ""),
    )


# ── APIS ADMINISTRATIVAS: FIDELIDAD ──

@app.route("/api/admin/fidelidad/canjes", methods=["GET"])
@administrador_requerido
def api_admin_fidelidad_canjes():
    """Retorna el listado completo de pedidos especiales de canjes de fidelidad."""
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT c.id_canje AS id, r.id_reserva, r.codigo, cl.nombre AS cliente,
                   COALESCE(NULLIF(r.correo, ''), cl.correo, '') AS correo,
                   COALESCE(NULLIF(r.telefono, ''), cl.telefono, '') AS telefono,
                   p.nombre AS producto, c.puntos_usados,
                   c.fecha_canje, c.estado, c.fecha_entrega, r.fecha_retiro
            FROM CANJE_FIDELIDAD c
            JOIN RESERVA r ON r.id_reserva = c.id_reserva
            JOIN CLIENTE cl ON cl.id_cliente = c.id_cliente
            JOIN PRODUCTO p ON p.id_producto = c.id_producto
            ORDER BY c.id_canje DESC
            """
        )
        filas = cursor.fetchall() or []
        canjes = []
        for f in filas:
            fc = f.get("fecha_canje")
            fe = f.get("fecha_entrega")
            fr = f.get("fecha_retiro")
            canjes.append({
                "id": f["id"],
                "id_reserva": f["id_reserva"],
                "codigo": f["codigo"],
                "cliente": f["cliente"],
                "correo": f["correo"],
                "telefono": f["telefono"],
                "producto": f["producto"],
                "puntos_usados": int(f.get("puntos_usados") or 0),
                "fecha_canje": fc.strftime("%d/%m/%Y %H:%M") if hasattr(fc, "strftime") else str(fc or "")[:16],
                "fecha_entrega": fe.strftime("%d/%m/%Y %H:%M") if hasattr(fe, "strftime") else (str(fe or "")[:16] if fe else None),
                "fecha_retiro": fr.strftime("%d/%m/%Y") if hasattr(fr, "strftime") else str(fr or "")[:10],
                "estado": f["estado"],
            })
        return jsonify({"ok": True, "canjes": canjes})
    except Exception as e:
        app.logger.exception("Error al consultar órdenes de canje: %s", e)
        return jsonify({"ok": False, "error": "No se pudieron cargar las órdenes de canje."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/admin/fidelidad/canjes/<int:canje_id>/estado", methods=["POST"])
@administrador_requerido
def api_admin_fidelidad_canjes_estado(canje_id):
    """Actualiza el estado de la orden de canje y sincroniza con RESERVA y stock/puntos."""
    if not _csrf_valido():
        return jsonify({"ok": False, "error": "Sesión vencida. Recarga la página."}), 403

    datos = request.get_json(silent=True) or {}
    nuevo_estado = str(datos.get("estado", "")).strip().upper()
    if nuevo_estado not in ("SOLICITADO", "CONFIRMADA", "EN_PREPARACION", "LISTA", "ENTREGADA", "CANCELADA"):
        return jsonify({"ok": False, "error": "Estado de orden de canje no válido."}), 400

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        conexion.start_transaction()
        cursor = conexion.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT c.id_canje, c.id_reserva, c.id_cliente, c.puntos_usados, c.estado,
                   p.nombre AS nombre_producto
            FROM CANJE_FIDELIDAD c
            JOIN PRODUCTO p ON p.id_producto = c.id_producto
            WHERE c.id_canje = %s OR c.id_reserva = %s
            LIMIT 1
            FOR UPDATE
            """,
            (canje_id, canje_id),
        )
        canje = cursor.fetchone()
        if not canje:
            conexion.rollback()
            return jsonify({"ok": False, "error": "No se encontró el canje especificado."}), 404

        es_entrega = nuevo_estado == "ENTREGADA"
        es_cancelacion = nuevo_estado == "CANCELADA" and canje["estado"] != "CANCELADA"

        if es_entrega:
            cursor.execute(
                "UPDATE CANJE_FIDELIDAD SET estado = %s, fecha_entrega = NOW() WHERE id_canje = %s",
                (nuevo_estado, canje["id_canje"]),
            )
        else:
            cursor.execute(
                "UPDATE CANJE_FIDELIDAD SET estado = %s WHERE id_canje = %s",
                (nuevo_estado, canje["id_canje"]),
            )

        cursor.execute(
            "UPDATE RESERVA SET estado = %s WHERE id_reserva = %s",
            (nuevo_estado, canje["id_reserva"]),
        )

        # Si se cancela la orden, reembolsar los puntos al cliente
        if es_cancelacion:
            cursor.execute(
                "SELECT puntos_fidelidad FROM CLIENTE WHERE id_cliente = %s FOR UPDATE",
                (canje["id_cliente"],),
            )
            cli = cursor.fetchone()
            saldo_act = (cli.get("puntos_fidelidad") or 0) if cli else 0
            nuevo_saldo = saldo_act + int(canje["puntos_usados"])
            cursor.execute(
                "UPDATE CLIENTE SET puntos_fidelidad = %s WHERE id_cliente = %s",
                (nuevo_saldo, canje["id_cliente"]),
            )
            motivo_ref = f"Reembolso por canje cancelado: +{canje['puntos_usados']} pts ({canje['nombre_producto']})"
            cursor.execute(
                """
                INSERT INTO HISTORIAL_PUNTOS (
                    id_cliente, id_reserva, tipo, puntos, descripcion,
                    saldo_resultante, fecha_registro, fecha, motivo, tipo_movimiento
                ) VALUES (
                    %s, %s, 'ACUMULACION', %s, %s,
                    %s, NOW(), NOW(), %s, 'REEMBOLSO'
                )
                """,
                (
                    canje["id_cliente"], canje["id_reserva"], int(canje["puntos_usados"]),
                    motivo_ref, nuevo_saldo, motivo_ref
                ),
            )

        conexion.commit()
        return jsonify({
            "ok": True,
            "mensaje": f"Orden de canje actualizada a '{nuevo_estado}' exitosamente."
        })
    except Exception as e:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al actualizar estado de orden de canje %s: %s", canje_id, e)
        return jsonify({"ok": False, "error": "No se pudo actualizar el estado de la orden de canje."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/admin/fidelidad/historial", methods=["GET"])
@administrador_requerido
def api_admin_fidelidad_historial():
    """Retorna el historial completo de movimientos de puntos de todos los clientes."""
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT h.id_historial AS id, cl.nombre AS cliente, cl.correo,
                   COALESCE(h.fecha, h.fecha_registro) AS fecha,
                   COALESCE(h.motivo, h.descripcion) AS motivo,
                   h.puntos, h.saldo_resultante,
                   COALESCE(h.tipo_movimiento, h.tipo) AS tipo_movimiento,
                   h.id_reserva
            FROM HISTORIAL_PUNTOS h
            JOIN CLIENTE cl ON cl.id_cliente = h.id_cliente
            ORDER BY h.id_historial DESC
            LIMIT 300
            """
        )
        filas = cursor.fetchall() or []
        movimientos = []
        for f in filas:
            dt = f.get("fecha")
            movimientos.append({
                "id": f["id"],
                "cliente": f["cliente"],
                "correo": f["correo"],
                "fecha": dt.strftime("%d/%m/%Y %H:%M") if hasattr(dt, "strftime") else str(dt or "")[:16],
                "motivo": f.get("motivo") or "",
                "puntos": int(f.get("puntos") or 0),
                "saldo_resultante": int(f.get("saldo_resultante") or 0),
                "tipo_movimiento": f.get("tipo_movimiento") or "ACUMULACION",
                "id_reserva": f.get("id_reserva"),
            })
        return jsonify({"ok": True, "movimientos": movimientos})
    except Exception as e:
        app.logger.exception("Error al consultar movimientos de fidelidad: %s", e)
        return jsonify({"ok": False, "error": "No se pudieron obtener los movimientos de puntos."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/admin/fidelidad/configuracion", methods=["GET", "POST"])
@administrador_requerido
def api_admin_fidelidad_configuracion():
    """Consulta y actualiza las reglas del programa y productos canjeables / acumulables."""
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)

        if request.method == "POST":
            if not _csrf_valido():
                return jsonify({"ok": False, "error": "Sesión vencida. Recarga la página."}), 403
            datos = request.get_json(silent=True) or {}
            puntos_dolar = max(1, int(datos.get("puntos_por_dolar") or 1))
            meta_minima = max(50, int(datos.get("meta_minima_canje") or 50))
            activo = 1 if datos.get("programa_activo", True) else 0

            cursor.execute(
                """
                UPDATE CONFIGURACION_FIDELIDAD
                SET puntos_por_dolar = %s, meta_minima_canje = %s, programa_activo = %s,
                    fecha_actualizacion = NOW()
                WHERE id = 1
                """,
                (puntos_dolar, meta_minima, activo),
            )
            conexion.commit()
            return jsonify({"ok": True, "mensaje": "Reglas de fidelidad actualizadas correctamente."})

        # GET: obtener configuración y productos
        cursor.execute("SELECT puntos_por_dolar, meta_minima_canje, programa_activo FROM CONFIGURACION_FIDELIDAD WHERE id = 1")
        cfg = cursor.fetchone() or {"puntos_por_dolar": 1, "meta_minima_canje": 50, "programa_activo": 1}

        cursor.execute(
            """
            SELECT p.id_producto, p.nombre, p.categoria, p.precio,
                   COALESCE(p.canjeable_puntos, p.es_canjeable, 0) AS canjeable_puntos,
                   COALESCE(p.puntos_canje, 50) AS puntos_canje,
                   COALESCE(p.genera_puntos, 1) AS genera_puntos,
                   p.imagen, p.tipo_imagen
            FROM PRODUCTO p
            ORDER BY p.nombre ASC
            """
        )
        prods_raw = cursor.fetchall() or []
        productos = []
        for p in prods_raw:
            pub = _producto_publico(p)
            productos.append({
                "id": pub["id"],
                "nombre": pub["nombre"],
                "categoria": pub["categoria"],
                "precio": pub["precio"],
                "canjeable_puntos": pub["canjeable_puntos"],
                "puntos_canje": pub["puntos_canje"],
                "genera_puntos": pub["genera_puntos"],
                "tiene_imagen": pub["tiene_imagen"],
                "imagen": pub["imagen"],
            })

        return jsonify({
            "ok": True,
            "config": {
                "puntos_por_dolar": int(cfg.get("puntos_por_dolar") or 1),
                "meta_minima_canje": int(cfg.get("meta_minima_canje") or 50),
                "programa_activo": bool(cfg.get("programa_activo")),
            },
            "productos": productos,
        })
    except Exception as e:
        if conexion and request.method == "POST":
            conexion.rollback()
        app.logger.exception("Error al consultar o actualizar configuración de fidelidad: %s", e)
        return jsonify({"ok": False, "error": "No se pudo procesar la configuración de fidelidad."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


@app.route("/api/admin/fidelidad/producto/<int:producto_id>", methods=["POST"])
@administrador_requerido
def api_admin_fidelidad_producto(producto_id):
    """Actualiza la configuración de fidelidad de un producto individual."""
    if not _csrf_valido():
        return jsonify({"ok": False, "error": "Sesión vencida. Recarga la página."}), 403

    datos = request.get_json(silent=True) or {}
    canjeable = 1 if datos.get("canjeable_puntos") else 0
    puntos_canje = int(datos.get("puntos_canje") or 50)
    genera = 1 if datos.get("genera_puntos", True) else 0

    if canjeable and puntos_canje < 50:
        return jsonify({"ok": False, "error": "La cantidad mínima requerida para canje es de 50 puntos."}), 400

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor()
        cursor.execute(
            """
            UPDATE PRODUCTO
            SET canjeable_puntos = %s, puntos_canje = %s, genera_puntos = %s
            WHERE id_producto = %s
            """,
            (canjeable, puntos_canje, genera, producto_id),
        )
        conexion.commit()
        return jsonify({"ok": True, "mensaje": "Producto actualizado exitosamente."})
    except Exception as e:
        if conexion:
            conexion.rollback()
        app.logger.exception("Error al actualizar fidelidad del producto %s: %s", producto_id, e)
        return jsonify({"ok": False, "error": "No se pudo actualizar la configuración de fidelidad del producto."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


# ==========================================
# CERRAR SESIÓN
# ==========================================

@app.route("/cerrar-sesion")
def cerrar_sesion():

    session.clear()

    flash("Has cerrado sesión correctamente.", "success")

    return redirect(url_for("login"))


# ==========================================
# EJECUTAR SERVIDOR
# ==========================================

if __name__ == "__main__":
    puerto = int(os.getenv("PORT", 5000))
    # Modo depuración controlado por variable de entorno (por defecto False para seguridad)
    debug_mode = os.getenv("FLASK_DEBUG", "false").strip().lower() in ("1", "true", "yes", "t")
    print("\n" + "=" * 65)
    print("  TWINS BAKERY - SERVIDOR INICIADO CON EXITO")
    print(f"  * Aplicacion web (Cliente): http://127.0.0.1:{puerto}/")
    print(f"  * Panel de Administracion:  http://127.0.0.1:{puerto}/admin/login")
    print(f"  * Modo Debug (desarrollo):  {'ACTIVADO (Debugger web bloqueado por seguridad)' if debug_mode else 'DESACTIVADO (Produccion segura)'}")
    print(f"  * Logs en terminal:        ACTIVOS (Auditoria y errores en consola)")
    print("=" * 65 + "\n")
    # use_debugger=False garantiza que Werkzeug NUNCA filtre trazas de error al navegador
    app.run(host="127.0.0.1", port=puerto, debug=debug_mode, use_debugger=False)
