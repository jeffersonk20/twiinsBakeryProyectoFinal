"""
Script de limpieza para la base de datos LOCAL (SQLite - twins_bakery.db).
Elimina todos los datos de prueba locales (clientes, reservas, pagos, pasteles, etc.)
y conserva ÚNICAMENTE las credenciales del ADMINISTRADOR oficial.
"""

import os
import sqlite3
from werkzeug.security import generate_password_hash


def limpiar_base_datos_local():
    db_path = os.path.join(os.path.dirname(__file__), "twins_bakery.db")

    print("\n=======================================================")
    print("  LIMPIEZA DE BASE DE DATOS LOCAL (SQLite)")
    print(f"  Archivo: {db_path}")
    print("=======================================================\n")

    if not os.path.exists(db_path):
        print("El archivo twins_bakery.db no existe en la carpeta.")
        return

    conexion = sqlite3.connect(db_path)
    cursor = conexion.cursor()

    try:
        # 1. Obtener todas las tablas existentes en SQLite excepto ADMINISTRADOR
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
        tablas = [fila[0] for fila in cursor.fetchall() if fila[0].upper() != "ADMINISTRADOR"]

        print(f"Tablas encontradas en base local: {len(tablas)}")

        # 2. Desactivar foreign keys temporalmente
        cursor.execute("PRAGMA foreign_keys = OFF;")

        for tabla in tablas:
            try:
                cursor.execute(f"DELETE FROM `{tabla}`;")
                # Reiniciar autoincrement de sqlite si existe sqlite_sequence
                cursor.execute(f"DELETE FROM sqlite_sequence WHERE name='{tabla}';")
                print(f"  ✓ Tabla local '{tabla}' vaciada.")
            except Exception as e:
                print(f"  ⚠ Aviso en tabla '{tabla}': {e}")

        cursor.execute("PRAGMA foreign_keys = ON;")

        # 3. Configurar Administrador oficial
        clave_hash = generate_password_hash("admin1234")
        cursor.execute("DELETE FROM ADMINISTRADOR;")
        cursor.execute(
            """
            INSERT INTO ADMINISTRADOR (id_admin, nombre, correo, contrasena)
            VALUES (1, 'Administrador Twins Bakery', 'adminbakery@gmail.com', ?);
            """,
            (clave_hash,)
        )
        print("\n  ✓ Administrador oficial configurado en base local:")
        print("    - Correo: adminbakery@gmail.com")
        print("    - Clave:  admin1234")

        conexion.commit()

        print("\n=======================================================")
        print("  ¡BASE DE DATOS LOCAL LIMPIADA CON ÉXITO!")
        print("  - No hay clientes registrados.")
        print("  - No hay pasteles ni productos.")
        print("  - No hay reservas ni pagos.")
        print("  - Solo existe tu cuenta de ADMINISTRADOR lista.")
        print("=======================================================\n")

    finally:
        cursor.close()
        conexion.close()


if __name__ == "__main__":
    limpiar_base_datos_local()
