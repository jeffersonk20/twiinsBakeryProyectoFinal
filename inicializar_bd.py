
from conexion import obtener_conexion


def inicializar_base_datos():

    conexion = None
    cursor = None

    try:
        # Conectarse a Aiven
        conexion = obtener_conexion()
        cursor = conexion.cursor(dictionary=True)

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
        # TABLA 2: TABLA PASTEL (producto)
        # ==========================================

        crear_producto = """
        CREATE TABLE IF NOT EXISTS PRODUCTO (
            id_producto INT AUTO_INCREMENT PRIMARY KEY,
            nombre VARCHAR(80) NOT NULL,
            categoria VARCHAR(30) NULL,
            precio DECIMAL(8, 2) NOT NULL,
            descripcion VARCHAR(300) NOT NULL,
            disponible BOOLEAN NOT NULL DEFAULT TRUE,
            en_vitrina BOOLEAN NOT NULL DEFAULT FALSE,
            imagen MEDIUMBLOB NULL,
            tipo_imagen VARCHAR(30) NULL,
            fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_producto_catalogo (disponible, categoria)
        );
        """

        cursor.execute(crear_producto)

        cursor.execute("SHOW COLUMNS FROM PRODUCTO")
        columnas_producto = {
            columna["Field"]
            for columna in cursor.fetchall()
        }

        migraciones_producto = {
            "categoria": "ALTER TABLE PRODUCTO ADD COLUMN categoria VARCHAR(30) NULL AFTER nombre",
            "disponible": "ALTER TABLE PRODUCTO ADD COLUMN disponible BOOLEAN NOT NULL DEFAULT TRUE AFTER precio",
            "en_vitrina": "ALTER TABLE PRODUCTO ADD COLUMN en_vitrina BOOLEAN NOT NULL DEFAULT FALSE AFTER disponible",
            "imagen": "ALTER TABLE PRODUCTO ADD COLUMN imagen MEDIUMBLOB NULL AFTER disponible",
            "tipo_imagen": "ALTER TABLE PRODUCTO ADD COLUMN tipo_imagen VARCHAR(30) NULL AFTER imagen",
            "fecha_actualizacion": (
                "ALTER TABLE PRODUCTO ADD COLUMN fecha_actualizacion "
                "TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"
            ),
        }

        disponible_agregada = "disponible" not in columnas_producto
        for columna, consulta in migraciones_producto.items():
            if columna not in columnas_producto:
                cursor.execute(consulta)

        if disponible_agregada and "activo" in columnas_producto:
            cursor.execute("UPDATE PRODUCTO SET disponible = activo")

        cursor.execute("SHOW INDEX FROM PRODUCTO")
        indices_producto = {
            indice["Key_name"]
            for indice in cursor.fetchall()
        }
        if "idx_producto_catalogo" not in indices_producto:
            cursor.execute(
                "CREATE INDEX idx_producto_catalogo "
                "ON PRODUCTO (disponible, categoria)"
            )

        print("Tabla PRODUCTO verificada.")

        # ==========================================
        # GUARDAR CAMBIOS
        # ==========================================

        conexion.commit()

        print("\nBase de datos inicializada correctamente.")

    except Exception as e:

        if conexion:
            conexion.rollback()

        print(f"Error al inicializar la base de datos: {e}")
        raise

    finally:

        if cursor:
            cursor.close()

        if conexion and conexion.is_connected():
            conexion.close()


# Ejecutar solamente si se abre este archivo directamente
if __name__ == "__main__":
    inicializar_base_datos()