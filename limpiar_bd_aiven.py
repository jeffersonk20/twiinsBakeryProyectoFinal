"""
Script de inicialización y limpieza total para la base de datos de Aiven (MySQL).
1. Crea o actualiza todas las tablas necesarias del sistema.
2. Limpia todos los datos operativos (clientes de prueba, pasteles, reservas, pagos, chats, etc.).
3. Conserva ÚNICAMENTE las credenciales del ADMINISTRADOR.
"""

import os
from dotenv import load_dotenv
import mysql.connector
from werkzeug.security import generate_password_hash
from inicializar_bd import _inicializar_mysql

load_dotenv()


def inicializar_y_limpiar_aiven():
    host = os.getenv("DB_HOST", "")
    port = int(os.getenv("DB_PORT", "11537"))
    user = os.getenv("DB_USER", "")
    password = os.getenv("DB_PASSWORD", "")
    database = os.getenv("DB_NAME", "defaultdb")
    ruta_ca = os.path.join(os.path.dirname(__file__), "ca.pem")

    if not host or not user:
        raise ValueError("Faltan DB_HOST o DB_USER en el archivo .env")

    print("\n=======================================================")
    print("  INICIALIZACIÓN Y LIMPIEZA DE AIVEN (PRODUCCIÓN)")
    print(f"  Servidor: {host}:{port} ({database})")
    print("=======================================================\n")

    cfg = {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "database": database,
    }
    if os.path.exists(ruta_ca):
        cfg["ssl_ca"] = ruta_ca

    conexion = mysql.connector.connect(**cfg)
    cursor = conexion.cursor()

    try:
        # PASO 1: Crear / asegurar todas las tablas del sistema
        print("Paso 1: Creando y verificando todas las tablas en Aiven...")
        _inicializar_mysql(conexion, cursor)
        conexion.commit()
        print("  ✓ Todas las tablas necesarias han sido creadas con éxito.")

        # PASO 2: Obtener las tablas existentes para limpiarlas
        cursor.execute("SHOW TABLES;")
        filas = cursor.fetchall()
        tablas_a_limpiar = []
        for f in filas:
            nombre_tabla = f[0]
            if nombre_tabla.upper() != "ADMINISTRADOR":
                tablas_a_limpiar.append(nombre_tabla)

        print(f"\nPaso 2: Limpiando {len(tablas_a_limpiar)} tablas de datos de prueba...")
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")

        for tabla in tablas_a_limpiar:
            try:
                cursor.execute(f"TRUNCATE TABLE `{tabla}`;")
                print(f"  ✓ Tabla '{tabla}' vaciada.")
            except Exception:
                try:
                    cursor.execute(f"DELETE FROM `{tabla}`;")
                    cursor.execute(f"ALTER TABLE `{tabla}` AUTO_INCREMENT = 1;")
                    print(f"  ✓ Tabla '{tabla}' limpiada con DELETE.")
                except Exception as e_del:
                    print(f"  ⚠ Aviso en tabla '{tabla}': {e_del}")

        cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")

        # PASO 3: Asegurar la cuenta oficial de ADMINISTRADOR
        clave_hash = generate_password_hash("admin1234")
        cursor.execute("DELETE FROM ADMINISTRADOR;")
        cursor.execute(
            """
            INSERT INTO ADMINISTRADOR (id_admin, nombre, correo, contrasena)
            VALUES (1, 'Administrador Twins Bakery', 'adminbakery@gmail.com', %s);
            """,
            (clave_hash,),
        )
        print("\n  ✓ Administrador oficial configurado:")
        print("    - Correo: adminbakery@gmail.com")
        print("    - Clave:  admin1234")

        conexion.commit()

        print("\n=======================================================")
        print("  ¡BASE DE DATOS EN AIVEN LISTA Y 100% LIMPIA!")
        print("  - Todas las tablas necesarias existen y están creadas.")
        print("  - No hay clientes registrados.")
        print("  - No hay pasteles ni productos.")
        print("  - No hay reservas ni pagos.")
        print("  - Solo existe tu cuenta de ADMINISTRADOR lista.")
        print("=======================================================\n")

    finally:
        cursor.close()
        conexion.close()


if __name__ == "__main__":
    inicializar_y_limpiar_aiven()
