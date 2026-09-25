
from conexion import obtener_conexion


def inicializar_base_datos():

    conexion = None
    cursor = None

    try:
        # Conectarse a Aiven
        conexion = obtener_conexion()
        cursor = conexion.cursor()

        print("Conectado a Aiven correctamente.")

        # ==========================================
        # TABLA 1: CLIENTE
        # ==========================================

        crear_cliente = """
        CREATE TABLE IF NOT EXISTS CLIENTE (
            id_cliente INT AUTO_INCREMENT PRIMARY KEY,
            nombre VARCHAR(100) NOT NULL,
            correo VARCHAR(150) NOT NULL UNIQUE,
            contrasena VARCHAR(255) NOT NULL,
            fecha_registro DATE DEFAULT (CURRENT_DATE)
        );
        """

        cursor.execute(crear_cliente)
        print("Tabla CLIENTE verificada.")

        # ==========================================
        # TABLA 2: PRODUCTO (EJEMPLO FUTURO)
        # ==========================================

        crear_producto = """
        CREATE TABLE IF NOT EXISTS PRODUCTO (
            id_producto INT AUTO_INCREMENT PRIMARY KEY,
            nombre VARCHAR(100) NOT NULL,
            descripcion VARCHAR(255),
            precio DECIMAL(10,2) NOT NULL,
            imagen VARCHAR(255),
            disponible BOOLEAN DEFAULT TRUE
        );
        """

        cursor.execute(crear_producto)
        print("Tabla PRODUCTO verificada.")

        # ==========================================
        # AQUI AGREGARAS LAS FUTURAS TABLAS
        # ==========================================

        # Ejemplo:
        #
        # crear_categoria = """
        # CREATE TABLE IF NOT EXISTS CATEGORIA (
        #     id_categoria INT AUTO_INCREMENT PRIMARY KEY,
        #     nombre VARCHAR(100) NOT NULL
        # );
        # """
        #
        # cursor.execute(crear_categoria)

        # ==========================================
        # GUARDAR CAMBIOS
        # ==========================================

        conexion.commit()

        print("\nBase de datos inicializada correctamente.")

    except Exception as e:

        if conexion:
            conexion.rollback()

        print(f"Error al inicializar la base de datos: {e}")

    finally:

        if cursor:
            cursor.close()

        if conexion and conexion.is_connected():
            conexion.close()


# Ejecutar solamente si se abre este archivo directamente
if __name__ == "__main__":
    inicializar_base_datos()