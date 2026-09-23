import mysql.connector

try:
    conexion = mysql.connector.connect(
        host="mysql-1afe1a93-jeffersonk20castillo-ee98.k.aivencloud.com",
        port=11537,
        user="#",
        password="#",
        database="defaultdb",
        ssl_disabled=False
    )

    print("Conexion exitosa a Aiven")

    cursor = conexion.cursor()

    # Consulta para crear la tabla CLIENTE
    crear_tabla_query = """
    CREATE TABLE IF NOT EXISTS CLIENTE (
        id_cliente INT AUTO_INCREMENT PRIMARY KEY,
        nombre VARCHAR(100) NOT NULL,
        correo VARCHAR(150) NOT NULL UNIQUE,
        contrasena VARCHAR(255) NOT NULL,
        fecha_registro DATE DEFAULT (CURRENT_DATE)
    );
    """

    cursor.execute(crear_tabla_query)
    conexion.commit()

    print("Tabla 'CLIENTE' lista y verificada (sin duplicaciones).")

    #las columnas en Aiven para verificar la estructura
    cursor.execute("DESCRIBE CLIENTE;")
    columnas = cursor.fetchall()

    print("\nEstructura de la tabla CLIENTE en Aiven:")
    print("-" * 55)
    for col in columnas:
        print(f"Columna: {col[0]:<16} Tipo: {col[1]:<15} Clave: {col[3]}")
    print("-" * 55)

    cursor.close()
    conexion.close()

except Exception as e:
    print(f"Error de conexion o al crear la tabla: {e}")
