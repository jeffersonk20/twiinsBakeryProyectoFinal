
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    send_from_directory
)

from werkzeug.security import generate_password_hash, check_password_hash
from conexion import obtener_conexion
from dotenv import load_dotenv
import os

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


# ==========================================
# ARCHIVOS CSS E IMÁGENES
# ==========================================

@app.route("/static/<path:filename>")
def static_files(filename):

    # Solo permitir archivos de css e img
    if filename.startswith("css/"):
        carpeta = "css"
        archivo = filename[4:]

    elif filename.startswith("img/"):
        carpeta = "img"
        archivo = filename[4:]

    else:
        return "Archivo no permitido", 404

    return send_from_directory(carpeta, archivo)


# ==========================================
# PANTALLA DE INICIO
# ==========================================

@app.route("/")
def login():
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

            return redirect(url_for("login"))

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