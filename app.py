
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
from conexion import obtener_conexion
from dotenv import load_dotenv
import os
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

load_dotenv()

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

app.config["MAX_CONTENT_LENGTH"] = int(1.2 * 1024 * 1024) + 65536

CATEGORIAS_PRODUCTO = {"Pasteles", "Cupcakes", "Galletas", "Bebidas"}
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
URL_BASE_TUWEB = os.getenv("URL_BASE_TUWEB", "").rstrip("/")
WOMPI_TOKEN_URL = "https://id.wompi.sv/connect/token"
WOMPI_PAYMENT_LINK_URL = "https://api.wompi.sv/EnlacePago"
WOMPI_TOKEN = {"valor": None, "expira": 0}
TIPOS_IMAGEN = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
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


@app.route("/admin/configuracion")
@administrador_requerido
def admin_configuracion():
    return render_template(
        "admin_configuracion.html",
        csrf_token=session["csrf_token"],
        admin_email=session.get("admin_email", ""),
    )


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("es_admin"):
        return redirect(url_for("admin_reservas"))

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
                    return redirect(url_for("admin_reservas"))
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
                    return redirect(url_for("admin_reservas"))
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


def _producto_publico(registro):
    tiene_imagen = bool(registro["tiene_imagen"])
    return {
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


def _obtener_productos(solo_disponibles):
    conexion = obtener_conexion()
    cursor = None
    try:
        cursor = conexion.cursor(dictionary=True)
        consulta = """
            SELECT id_producto, nombre, categoria, precio, descripcion, disponible,
                   en_vitrina,
                   (imagen IS NOT NULL AND tipo_imagen IS NOT NULL) AS tiene_imagen
            FROM PRODUCTO
        """
        if solo_disponibles:
            consulta += """
                WHERE disponible = TRUE
                  AND categoria IS NOT NULL
                  AND imagen IS NOT NULL
                  AND tipo_imagen IS NOT NULL
            """
            if request.args.get("vitrina") == "1":
                consulta += " AND en_vitrina = TRUE"
        consulta += " ORDER BY fecha_creacion DESC, id_producto DESC"
        cursor.execute(consulta)
        return [_producto_publico(registro) for registro in cursor.fetchall()]
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
        "imagen": contenido_imagen,
        "tipo_imagen": tipo_imagen,
    }


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
            return jsonify(_obtener_productos(solo_disponibles=False))
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
                "SELECT id_detalle FROM DETALLE_RESERVA WHERE id_pastel = %s LIMIT 1",
                (producto_id,),
            )
            if cursor.fetchone():
                return jsonify({
                    "error": "No se puede eliminar un producto con reservas registradas. Márcalo como agotado para conservar el historial."
                }), 409
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
        conexion.commit()
        return jsonify({"mensaje": "Producto actualizado."})
    except mysql.connector.Error as error:
        if conexion:
            conexion.rollback()
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
            SELECT id_producto, nombre, precio
            FROM PRODUCTO
            WHERE id_producto = %s AND disponible = TRUE
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
                   COALESCE(c.correo, '') AS correo, r.telefono,
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
                "SELECT monto_pagado FROM RESERVA WHERE id_reserva = %s FOR UPDATE",
                (reserva_id,),
            )
            reserva = cursor.fetchone()
            if not reserva:
                conexion.rollback()
                return jsonify({"error": "La reserva ya no existe."}), 404
            if Decimal(reserva["monto_pagado"]) > 0:
                conexion.rollback()
                return jsonify({
                    "error": "No se puede eliminar una reserva con pagos registrados. Cámbiala a cancelada para conservar el historial; los pagos no son reembolsables."
                }), 409
            cursor.execute("DELETE FROM RESERVA WHERE id_reserva = %s", (reserva_id,))
            conexion.commit()
            return jsonify({"mensaje": "Reserva eliminada."})
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
    if not set(datos).issubset({"estado", "nombre_cliente", "telefono", "fecha_retiro", "cantidad"}):
        return jsonify({"error": "La solicitud contiene campos que no se pueden modificar."}), 400
    if "estado" in datos and datos["estado"] not in ESTADOS_RESERVA:
        return jsonify({"error": "Selecciona un estado de reserva válido."}), 400
    if "nombre_cliente" in datos and (not str(datos["nombre_cliente"]).strip() or len(str(datos["nombre_cliente"])) > 100):
        return jsonify({"error": "El nombre del cliente no es válido."}), 400
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
            SELECT r.id_reserva, r.estado, r.monto_pagado, r.anticipo_requerido,
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
        if actual["estado"] == "CANCELADA" and estado != "CANCELADA":
            conexion.rollback()
            return jsonify({"error": "Una reserva cancelada no se puede reactivar."}), 409
        pago_registrado = Decimal(actual["monto_pagado"]) >= Decimal(actual["anticipo_requerido"])
        if estado == "PENDIENTE_PAGO" and pago_registrado:
            conexion.rollback()
            return jsonify({"error": "No se puede devolver a pendiente una reserva cuyo anticipo ya fue pagado."}), 409
        if estado in {"CONFIRMADA", "EN_PREPARACION", "LISTA", "ENTREGADA"} and not pago_registrado:
            conexion.rollback()
            return jsonify({"error": "No se puede avanzar la reserva hasta registrar el pago del anticipo del 50%."}), 409

        asignaciones = []
        valores = []
        for campo in ("nombre_cliente", "telefono"):
            if campo in datos:
                asignaciones.append(f"{campo} = %s")
                valores.append(str(datos[campo]).strip())
        if fecha_retiro:
            fecha_actual = actual["fecha_retiro"].replace(second=0, microsecond=0)
            if (
                fecha_retiro != fecha_actual
                and fecha_retiro < datetime.now() + timedelta(days=5)
            ):
                conexion.rollback()
                return jsonify({"error": "Las reservas deben programarse con al menos 5 días de anticipación."}), 400
            asignaciones.append("fecha_retiro = %s")
            valores.append(fecha_retiro)
        if "estado" in datos:
            asignaciones.append("estado = %s")
            valores.append(estado)

        if cantidad is not None and cantidad != actual["cantidad"]:
            if Decimal(actual["monto_pagado"]) > 0:
                conexion.rollback()
                return jsonify({"error": "No se puede cambiar la cantidad después de registrar un pago."}), 409
            nuevo_total = (Decimal(actual["precio_unitario"]) * cantidad).quantize(Decimal("0.01"))
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
        return jsonify({"mensaje": "Reserva actualizada."})
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
@administrador_requerido
def api_admin_marcar_pago(reserva_id):
    conexion = None
    cursor = None
    try:
        conexion = obtener_conexion()
        conexion.start_transaction()
        cursor = conexion.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT p.id_pago, p.monto, p.estado AS pago_estado, p.metodo_pago,
                   r.monto_pagado, r.anticipo_requerido, r.estado
            FROM PAGO p JOIN RESERVA r ON r.id_reserva = p.id_reserva
            WHERE r.id_reserva = %s
            ORDER BY p.id_pago DESC
            LIMIT 1
            FOR UPDATE
            """,
            (reserva_id,),
        )
        pago = cursor.fetchone()
        if not pago:
            conexion.rollback()
            return jsonify({"error": "La reserva no existe o no tiene un pago pendiente."}), 404
        if pago["metodo_pago"] != "EFECTIVO_TIENDA":
            conexion.rollback()
            return jsonify({"error": "Solo se puede registrar aquí el anticipo pagado en la tienda."}), 409
        if pago["pago_estado"] != "PENDIENTE":
            conexion.rollback()
            return jsonify({"error": "El pago ya fue registrado."}), 409
        if pago["estado"] == "CANCELADA":
            conexion.rollback()
            return jsonify({"error": "No se puede registrar un anticipo para una reserva cancelada."}), 409
        cursor.execute(
            "UPDATE PAGO SET estado = 'PAGADO', fecha_pago = NOW() WHERE id_pago = %s",
            (pago["id_pago"],),
        )
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
            (pago["monto"], pago["monto"], reserva_id),
        )
        conexion.commit()
        return jsonify({"mensaje": "Anticipo de efectivo registrado. La reserva fue confirmada."})
    except mysql.connector.Error as error:
        if conexion:
            conexion.rollback()
        return _error_base_datos(error, "No se pudo registrar el anticipo en efectivo.")
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