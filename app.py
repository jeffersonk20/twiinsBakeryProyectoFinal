
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
    send_file
)

from werkzeug.security import generate_password_hash, check_password_hash
# pyrefly: ignore[missing-import]
from conexion import obtener_conexion
from dotenv import load_dotenv
import os
import re
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
    enviar_correo_reserva_creada,
    enviar_correo_reserva_aceptada,
    enviar_correo_reserva_lista,
    enviar_correo_evento_aceptado,
    enviar_correo_evento_rechazado,
    enviar_correo_reserva_rechazada,
)

load_dotenv()

APP_MODE = os.getenv("APP_MODE", "combined").strip().lower()
if APP_MODE not in {"combined", "customer", "admin"}:
    raise RuntimeError("APP_MODE debe ser combined, customer o admin.")


def _normalizar_url_publica(valor):
    valor = valor.strip().rstrip("/")
    if not valor:
        return ""
    url = urlsplit(valor if "://" in valor else f"https://{valor}")
    if (
        url.scheme != "https"
        or not url.netloc
        or url.path
        or url.query
        or url.fragment
    ):
        raise RuntimeError("Las URL públicas deben ser HTTPS y no incluir rutas.")
    return f"https://{url.netloc}"


CLIENT_URL = _normalizar_url_publica(os.getenv("CLIENT_URL", ""))
if APP_MODE == "admin" and not CLIENT_URL:
    raise RuntimeError("Falta configurar CLIENT_URL para el servicio de administración.")

app = Flask(
    __name__,
    template_folder="html",
    static_folder=None
)

# Clave privada para las sesiones
app.secret_key = os.getenv("SECRET_KEY")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
)

# Evitar iniciar la aplicación si falta la clave
if not app.secret_key:
    raise RuntimeError("Falta configurar SECRET_KEY en el archivo .env")

# ==============================================================================
# INTEGRACIÓN DEL ASISTENTE DE IA (GEMINI RAG CON AISLAMIENTO POR ROL)
# ==============================================================================
try:
    from ia_asistente import ia_bp
    app.register_blueprint(ia_bp)
except Exception as err:
    app.logger.warning("No se pudo cargar el módulo ia_asistente: %s", err)

app.config["MAX_CONTENT_LENGTH"] = int(1.2 * 1024 * 1024) + 65536

CATEGORIAS_PRODUCTO = {"Pasteles", "Cupcakes", "Galletas", "Bebidas", "Eventos"}
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
URL_BASE_TUWEB = _normalizar_url_publica(os.getenv("URL_BASE_TUWEB", ""))
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


@app.context_processor
def urls_entre_sitios():
    return {
        "client_home_url": CLIENT_URL or url_for("index"),
        "client_catalog_url": (
            f"{CLIENT_URL}/catalogo" if CLIENT_URL else url_for("catalogo")
        ),
    }


def cliente_requerido(view):
    @wraps(view)
    def vista_protegida(*args, **kwargs):
        if not session.get("id_cliente"):
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
    base_url = urlsplit(URL_BASE_TUWEB)
    return bool(
        WOMPI_CLIENT_ID
        and WOMPI_CLIENT_SECRET
        and base_url.scheme == "https"
        and base_url.netloc
    )


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
        raise ValueError("Configura las credenciales Wompi y URL_BASE_TUWEB HTTPS.")
    monto = Decimal(str(monto)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if monto <= 0 or not pedido_id or not nombre_producto:
        raise ValueError("Los datos del enlace de pago no son válidos.")
    payload = {
        "identificadorEnlaceComercio": pedido_id,
        "monto": float(monto),
        "nombreProducto": nombre_producto,
        "formaPago": {
            "permitirTarjetaCreditoDebido": True,
            "permitirPagoConPuntoAgricola": False,
            "permitirPagoEnCuotasAgricola": False,
            "permitirPagoEnBitcoin": False,
            "permitePagoQuickPay": False,
        },
        "configuracion": {
            "urlRedirect": f"{URL_BASE_TUWEB}/pago/resultado",
            "urlWebhook": f"{URL_BASE_TUWEB}/webhook/wompi",
            "notificarTransaccionCliente": True,
        },
    }
    respuesta = requests.post(
        WOMPI_PAYMENT_LINK_URL,
        json=payload,
        headers={"Authorization": f"Bearer {obtener_token()}"},
        timeout=15,
    )
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
}


@app.route("/eventos")
@cliente_requerido
def eventos():
    return render_template("eventos.html")


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

    if not tipo_evento or not fecha_evento or not num_invitados or not lugar_evento:
        flash("Por favor completa todos los campos requeridos para cotizar tu evento.", "error")
        return redirect(url_for("planifica_evento"))

    try:
        invitados_num = int(num_invitados)
        if invitados_num <= 0:
            raise ValueError()
    except ValueError:
        flash("Ingresa un número válido de invitados.", "error")
        return redirect(url_for("planifica_evento"))

    # Limpiar y parsear presupuesto aproximado
    presupuesto_num = None
    if presupuesto:
        presupuesto_limpio = re.sub(r"[^\d.]", "", presupuesto)
        try:
            presupuesto_num = float(presupuesto_limpio)
        except (ValueError, TypeError):
            presupuesto_num = None

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

        flash("¡Solicitud enviada con éxito! La administración la revisará y podrás coordinar todos los detalles en tu chat de evento una vez aceptada.", "success")
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


@app.route("/admin/reservas/nueva", methods=["GET", "POST"])
@administrador_requerido
def admin_nueva_reserva():
    if request.method == "GET":
        minimo_retiro = datetime.now() + timedelta(days=5)
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
                       en_vitrina,
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
    if fecha_retiro < datetime.now() + timedelta(days=5):
        flash("Las reservas deben realizarse con al menos 5 días de anticipación.", "error")
        return redirect(url_for("admin_nueva_reserva"))

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        conexion.start_transaction()
        cursor = conexion.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT id_producto, nombre, categoria, precio
            FROM PRODUCTO
            WHERE id_producto = %s
            """,
            (producto_id,),
        )
        producto = cursor.fetchone()
        if not producto:
            conexion.rollback()
            flash("El producto seleccionado no está disponible.", "error")
            return redirect(url_for("admin_nueva_reserva"))

        id_cliente = None
        if correo:
            cursor.execute(
                "SELECT id_cliente FROM CLIENTE WHERE correo = %s LIMIT 1",
                (correo,),
            )
            cliente_existente = cursor.fetchone()
            if cliente_existente:
                id_cliente = cliente_existente["id_cliente"]

        total = (Decimal(str(producto["precio"])) * cantidad).quantize(Decimal("0.01"))
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
                (id_reserva, id_pastel, nombre_producto, precio_unitario, cantidad)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                id_reserva,
                producto["id_producto"],
                producto["nombre"],
                producto["precio"],
                cantidad,
            ),
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


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("es_admin"):
        return redirect(url_for("admin_dashboard"))

    admin_existe = None
    error_base_datos = False
    if request.method == "POST":
        try:
            admin_existe = _contar_administradores() > 0
        except mysql.connector.Error:
            app.logger.exception("No se pudo comprobar el acceso de administrador.")
            error_base_datos = True
            flash("No se pudo conectar con la base de datos. Revisa la configuración e inténtalo otra vez.", "error")
        if error_base_datos:
            pass
        elif not admin_existe:
            setup_token = os.getenv("ADMIN_SETUP_TOKEN", "")
            nombre = request.form.get("nombre", "").strip()
            correo = request.form.get("correo", "").strip().lower()
            contrasena = request.form.get("contrasena", "")
            confirmar = request.form.get("confirmar_contrasena", "")
            recibido = request.form.get("token_configuracion", "")
            if len(setup_token) < 32:
                flash("Configura ADMIN_SETUP_TOKEN con al menos 32 caracteres aleatorios en .env.", "error")
            elif not hmac.compare_digest(recibido, setup_token):
                flash("El código de configuración no es válido.", "error")
            elif not nombre or len(nombre) > 100 or "@" not in correo or len(correo) > 150:
                flash("Ingresa un nombre y correo electrónico válidos.", "error")
            elif len(contrasena) < 10:
                flash("La contraseña debe tener al menos 10 caracteres.", "error")
            elif contrasena != confirmar:
                flash("Las contraseñas no coinciden.", "error")
            else:
                conexion = None
                cursor = None
                try:
                    conexion = obtener_conexion()
                    cursor = conexion.cursor()
                    cursor.execute(
                        """
                        INSERT INTO ADMINISTRADOR (id_admin, nombre, correo, contrasena)
                        VALUES (1, %s, %s, %s)
                        """,
                        (nombre, correo, generate_password_hash(contrasena)),
                    )
                    conexion.commit()
                    session.clear()
                    session["es_admin"] = True
                    session["id_admin"] = 1
                    session["admin_email"] = correo
                    session["csrf_token"] = secrets.token_urlsafe(32)
                    return redirect(url_for("admin_dashboard"))
                except mysql.connector.Error as error:
                    if conexion:
                        conexion.rollback()
                    if error.errno == 1062:
                        admin_existe = True
                        flash("Ya existe un usuario administrador. Inicia sesión.", "error")
                    else:
                        app.logger.exception("No se pudo crear el administrador inicial.")
                        flash("No se pudo crear el usuario. Revisa la base de datos e inténtalo otra vez.", "error")
                finally:
                    if cursor:
                        cursor.close()
                    if conexion and conexion.is_connected():
                        conexion.close()
        else:
            correo = request.form.get("correo", "").strip().lower()
            contrasena = request.form.get("contrasena", "")
            conexion = None
            cursor = None
            try:
                conexion = obtener_conexion()
                cursor = conexion.cursor(dictionary=True)
                cursor.execute(
                    "SELECT id_admin, correo, contrasena FROM ADMINISTRADOR WHERE correo = %s",
                    (correo,),
                )
                admin = cursor.fetchone()
                if admin and check_password_hash(admin["contrasena"], contrasena):
                    session.clear()
                    session["es_admin"] = True
                    session["id_admin"] = admin["id_admin"]
                    session["admin_email"] = admin["correo"]
                    session["csrf_token"] = secrets.token_urlsafe(32)
                    return redirect(url_for("admin_dashboard"))
                flash("Correo o contraseña de administrador incorrectos.", "error")
            except mysql.connector.Error:
                app.logger.exception("No se pudo iniciar sesión como administrador.")
                flash("No se pudo conectar con la base de datos. Inténtalo otra vez.", "error")
            finally:
                if cursor:
                    cursor.close()
                if conexion and conexion.is_connected():
                    conexion.close()

    if admin_existe is None and not error_base_datos:
        try:
            admin_existe = _contar_administradores() > 0
        except mysql.connector.Error:
            app.logger.exception("No se pudo consultar el estado del usuario administrador.")
            error_base_datos = True

    return render_template(
        "admin_login.html",
        admin_existe=admin_existe,
        error_base_datos=error_base_datos,
        setup_configurado=len(os.getenv("ADMIN_SETUP_TOKEN", "")) >= 32,
    )


@app.route("/admin/cerrar-sesion", methods=["POST"])
@administrador_requerido
def admin_cerrar_sesion():
    session.clear()
    return redirect(url_for("admin_login"))


@app.route("/api/admin/usuario", methods=["DELETE"])
@administrador_requerido
def api_admin_eliminar_usuario():
    if not _csrf_valido():
        return jsonify({"error": "La sesión de seguridad venció. Recarga el panel e inténtalo otra vez."}), 403
    contrasena = request.form.get("contrasena", "")
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            "SELECT contrasena FROM ADMINISTRADOR WHERE id_admin = %s",
            (session.get("id_admin"),),
        )
        admin = cursor.fetchone()
        if not admin or not check_password_hash(admin["contrasena"], contrasena):
            return jsonify({"error": "La contraseña no es correcta."}), 403
        cursor.execute(
            "DELETE FROM ADMINISTRADOR WHERE id_admin = %s",
            (session.get("id_admin"),),
        )
        conexion.commit()
        session.clear()
        return jsonify({"mensaje": "El usuario administrador fue eliminado."})
    except mysql.connector.Error:
        if conexion:
            conexion.rollback()
        app.logger.exception("No se pudo eliminar el usuario administrador.")
        return jsonify({"error": "No se pudo eliminar el usuario. Revisa la conexión e inténtalo otra vez."}), 500
    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


def _producto_publico(registro, incluir_stock=False):
    tiene_imagen = bool(registro["tiene_imagen"])
    producto = {
        "id": registro["id_producto"],
        "nombre": registro["nombre"],
        "categoria": registro["categoria"] or "",
        "precio": float(registro["precio"]),
        "descripcion": registro["descripcion"],
        "disponible": bool(registro["disponible"]),
        "en_vitrina": bool(registro["en_vitrina"]),
        "tiene_imagen": tiene_imagen,
        "imagen": (
            url_for("imagen_producto", producto_id=registro["id_producto"])
            if tiene_imagen
            else ""
        ),
    }
    if incluir_stock:
        producto["stock"] = int(registro["stock"])
    return producto


def _obtener_productos(solo_disponibles, incluir_stock=False):
    conexion = obtener_conexion()
    cursor = None
    try:
        cursor = conexion.cursor(dictionary=True)
        consulta = """
            SELECT p.id_producto, p.nombre, p.categoria, p.precio, p.descripcion,
                   p.disponible, p.en_vitrina,
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
                 imagen, tipo_imagen, id_admin)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                producto["nombre"],
                producto["categoria"],
                producto["precio"],
                producto["descripcion"],
                producto["disponible"],
                producto["en_vitrina"],
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
                disponible = %s, en_vitrina = %s, imagen = %s, tipo_imagen = %s
            WHERE id_producto = %s
            """,
            (
                producto["nombre"],
                producto["categoria"],
                producto["precio"],
                producto["descripcion"],
                producto["disponible"],
                producto["en_vitrina"],
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
            cursor = conexion.cursor()
            cursor.execute(
                """
                SELECT id_producto
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

        session.setdefault("csrf_token", secrets.token_urlsafe(32))
        minimo_retiro = datetime.now() + timedelta(days=5)
        return render_template(
            "reservar_producto.html",
            producto_id=producto_id,
            nombre_cliente=session.get("nombre_cliente", ""),
            csrf_token=session["csrf_token"],
            wompi_configurada=_wompi_configurada(),
            fecha_minima_retiro=minimo_retiro.date().isoformat(),
        )

    if not _csrf_valido():
        flash("La sesión de seguridad venció. Vuelve a intentarlo.", "error")
        return redirect(url_for("reservar_producto", producto_id=producto_id))

    nombre = request.form.get("nombre", "").strip()
    telefono = request.form.get("telefono", "").strip()
    metodo_pago = request.form.get("metodo_pago", "")
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
    if fecha_retiro < datetime.now() + timedelta(days=5):
        flash("Las reservas deben realizarse con al menos 5 días de anticipación.", "error")
        return redirect(url_for("reservar_producto", producto_id=producto_id))

    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        conexion.start_transaction()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT id_producto, nombre, categoria, precio
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

        total = (Decimal(producto["precio"]) * cantidad).quantize(Decimal("0.01"))
        anticipo = (total / 2).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        codigo = f"TB-{secrets.token_hex(4).upper()}"
        referencia_pago = (
            f"{codigo}-{secrets.token_hex(4).upper()}"
            if metodo_pago == "WOMPI"
            else codigo
        )
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
                (id_reserva, id_pastel, nombre_producto, precio_unitario, cantidad)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                id_reserva,
                producto["id_producto"],
                producto["nombre"],
                producto["precio"],
                cantidad,
            ),
        )
        cursor.execute(
            """
            INSERT INTO PAGO
                (id_reserva, metodo_pago, monto, estado, referencia)
            VALUES (%s, %s, %s, 'PENDIENTE', %s)
            """,
            (id_reserva, metodo_pago, anticipo, referencia_pago),
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

    if metodo_pago == "WOMPI":
        conexion = None
        cursor = None
        try:
            enlace = crear_enlace_pago(referencia_pago, anticipo, producto["nombre"])
            conexion = obtener_conexion()
            cursor = conexion.cursor()
            cursor.execute(
                """
                UPDATE PAGO SET referencia_wompi = %s
                WHERE referencia = %s AND metodo_pago = 'WOMPI'
                  AND estado = 'PENDIENTE'
                """,
                (str(enlace["idEnlace"]), referencia_pago),
            )
            conexion.commit()
            return redirect(enlace["urlEnlace"])
        except (requests.RequestException, ValueError, mysql.connector.Error):
            if conexion:
                conexion.rollback()
            app.logger.exception("No se pudo crear el enlace de pago de Wompi.")
            flash("La reserva quedó registrada, pero Wompi no pudo crear el enlace de pago. Revisa la configuración e inténtalo de nuevo desde la reserva.", "error")
            return redirect(url_for("reserva_registrada", codigo=codigo))
        finally:
            if cursor:
                cursor.close()
            if conexion and conexion.is_connected():
                conexion.close()

    return redirect(url_for("reserva_registrada", codigo=codigo))


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
                   d.cantidad, p.metodo_pago, p.estado AS pago_estado
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
        conexion = obtener_conexion()
        cursor = conexion.cursor()
        cursor.execute(
            """
            UPDATE PAGO SET referencia_wompi = %s
            WHERE id_pago = %s AND estado = 'PENDIENTE'
            """,
            (str(enlace["idEnlace"]), pago["id_pago"]),
        )
        if cursor.rowcount != 1:
            conexion.rollback()
            flash("El pago ya cambió de estado. Revisa tus reservas.", "error")
            return redirect(url_for("reserva_registrada", codigo=codigo))
        conexion.commit()
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
                   d.nombre_producto, d.cantidad, p.metodo_pago,
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
    return render_template("pago_resultado.html")


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

        # Reservas de hoy
        cursor.execute("""
            SELECT COUNT(*) AS total FROM RESERVA
            WHERE DATE(fecha_reserva) = DATE('now')
        """)
        row_hoy = cursor.fetchone()
        reservas_hoy = row_hoy["total"] if row_hoy else 0

        # Productos activos
        cursor.execute("SELECT COUNT(*) AS total FROM PRODUCTO WHERE disponible = TRUE")
        row_prod = cursor.fetchone()
        productos_activos = row_prod["total"] if row_prod else 0

        # Reservas de los últimos 7 días (para la gráfica)
        cursor.execute("""
            SELECT DATE(fecha_reserva) AS dia, COUNT(*) AS total
            FROM RESERVA
            WHERE fecha_reserva >= DATE('now', '-6 days')
            GROUP BY DATE(fecha_reserva)
            ORDER BY dia ASC
        """)
        reservas_semana = [
            {"dia": str(row["dia"]), "total": row["total"]}
            for row in cursor.fetchall()
        ]

        return jsonify({
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
            ORDER BY r.fecha_retiro DESC, r.id_reserva DESC
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

        # Actualiza o crea el registro de pago del anticipo en efectivo
        if reserva.get("id_pago"):
            cursor.execute(
                """
                UPDATE PAGO
                SET estado = 'PAGADO',
                    metodo_pago = CASE WHEN metodo_pago = 'WOMPI' THEN 'EFECTIVO_TIENDA' ELSE metodo_pago END,
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
        _error.description,
    )
    if request.path.startswith("/api/"):
        return jsonify({"error": "La imagen o solicitud supera el tamaño permitido."}), 413
    return "La solicitud supera el tamaño permitido.", 413


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

    # Validar campos
    if not nombre or not correo or not contrasena:
        flash("Completa todos los campos.", "error")
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

    conexion = None
    cursor = None

    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor()

        # Comprobar si el correo ya existe
        cursor.execute(
            "SELECT id_cliente FROM CLIENTE WHERE correo = %s",
            (correo,)
        )

        cliente_existente = cursor.fetchone()

        if cliente_existente:
            flash(
                "Este correo ya está registrado. Inicia sesión.",
                "error"
            )
            return redirect(url_for("registro"))

        # Encriptar la contraseña mediante hash
        contrasena_hash = generate_password_hash(contrasena)

        # Insertar el cliente en Aiven
        consulta = """
            INSERT INTO CLIENTE
            (nombre, correo, contrasena)
            VALUES (%s, %s, %s)
        """

        cursor.execute(
            consulta,
            (nombre, correo, contrasena_hash)
        )

        conexion.commit()

        # Enviar correo de bienvenida al cliente
        try:
            enviar_correo_bienvenida(correo, nombre)
        except Exception as err_correo:
            app.logger.warning("No se pudo disparar el correo de bienvenida: %s", err_correo)

        # Mensaje para el login
        flash(
            "¡Registro exitoso! 💗 Ya puedes iniciar sesión.",
            "success"
        )

        return redirect(url_for("login"))

    except Exception as e:

        if conexion:
            conexion.rollback()

        print("Error al registrar cliente:", e)

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

        # Buscar el cliente en Aiven
        consulta = """
            SELECT id_cliente, nombre, correo, contrasena
            FROM CLIENTE
            WHERE correo = %s
        """

        cursor.execute(consulta, (correo,))
        cliente = cursor.fetchone()

        if cliente and check_password_hash(
            cliente["contrasena"],
            contrasena
        ):

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

        print("Error al iniciar sesión:", e)

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
    app.run(debug=True)