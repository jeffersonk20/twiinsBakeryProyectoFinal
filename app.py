
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
from decimal import Decimal, InvalidOperation
from io import BytesIO
import hmac
import secrets
import mysql.connector

load_dotenv()

app = Flask(
    __name__,
    template_folder="html",
    static_folder=None
)

# Clave privada para las sesiones
app.secret_key = os.getenv("SECRET_KEY")

# Evitar iniciar la aplicación si falta la clave
if not app.secret_key:
    raise RuntimeError("Falta configurar SECRET_KEY en el archivo .env")

app.config["MAX_CONTENT_LENGTH"] = int(1.2 * 1024 * 1024) + 65536

CATEGORIAS_PRODUCTO = {"Pasteles", "Cupcakes", "Galletas", "Bebidas"}
ADMIN_AUTH_ENABLED = False
ADMIN_USER = os.getenv("ADMIN_USER", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
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
        if ADMIN_AUTH_ENABLED and not session.get("es_admin"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Inicia sesión como administrador."}), 401
            return redirect(url_for("admin_login"))
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
    )


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if not ADMIN_AUTH_ENABLED:
        return redirect(url_for("admin_productos"))
    if session.get("es_admin"):
        return redirect(url_for("admin_productos"))

    credenciales_configuradas = bool(ADMIN_USER and ADMIN_PASSWORD)
    if request.method == "POST":
        if not credenciales_configuradas:
            flash("Configura ADMIN_USER y ADMIN_PASSWORD en el archivo .env.", "error")
        else:
            usuario_valido = hmac.compare_digest(
                request.form.get("usuario", ""),
                ADMIN_USER,
            )
            contrasena_valida = hmac.compare_digest(
                request.form.get("contrasena", ""),
                ADMIN_PASSWORD,
            )
            if usuario_valido and contrasena_valida:
                session.clear()
                session["es_admin"] = True
                session["csrf_token"] = secrets.token_urlsafe(32)
                return redirect(url_for("admin_productos"))
            flash("Usuario o contraseña de administrador incorrectos.", "error")

    return render_template(
        "admin_login.html",
        credenciales_configuradas=credenciales_configuradas,
    )


@app.route("/admin/cerrar-sesion", methods=["POST"])
@administrador_requerido
def admin_cerrar_sesion():
    session.clear()
    return redirect(url_for("admin_login"))


def _producto_publico(registro):
    tiene_imagen = bool(registro["tiene_imagen"])
    return {
        "id": registro["id_producto"],
        "nombre": registro["nombre"],
        "categoria": registro["categoria"] or "",
        "precio": float(registro["precio"]),
        "descripcion": registro["descripcion"],
        "disponible": bool(registro["disponible"]),
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
    if error.errno == 1146:
        return jsonify({
            "error": "La tabla PRODUCTO todavía no existe. Ejecuta inicializar_bd.py y vuelve a intentar."
        }), 503
    if error.errno == 1054:
        return jsonify({
            "error": "La tabla PRODUCTO necesita actualizarse. Ejecuta inicializar_bd.py y reinicia la aplicación."
        }), 503
    return jsonify({"error": "No se pudo completar la operación. Revisa la conexión a la base de datos e inténtalo otra vez."}), 500


def _validar_producto_formulario():
    nombre = request.form.get("nombre", "").strip()
    categoria = request.form.get("categoria", "").strip()
    descripcion = request.form.get("descripcion", "").strip()
    precio_texto = request.form.get("precio", "").strip()
    disponible_texto = request.form.get("disponible", "true")

    if not nombre or len(nombre) > 80:
        raise ValueError("El nombre es obligatorio y admite hasta 80 caracteres.")
    if categoria not in CATEGORIAS_PRODUCTO:
        raise ValueError("Selecciona una categoría válida.")
    if not descripcion or len(descripcion) > 300:
        raise ValueError("La descripción es obligatoria y admite hasta 300 caracteres.")
    if disponible_texto not in {"true", "false"}:
        raise ValueError("Selecciona una disponibilidad válida.")

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
                (nombre, categoria, precio, descripcion, disponible, imagen, tipo_imagen)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                producto["nombre"],
                producto["categoria"],
                producto["precio"],
                producto["descripcion"],
                producto["disponible"],
                producto["imagen"],
                producto["tipo_imagen"],
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
                disponible = %s, imagen = %s, tipo_imagen = %s
            WHERE id_producto = %s
            """,
            (
                producto["nombre"],
                producto["categoria"],
                producto["precio"],
                producto["descripcion"],
                producto["disponible"],
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