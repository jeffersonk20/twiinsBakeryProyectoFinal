import os
import mysql.connector
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

load_dotenv()


def obtener_conexion():
    # Verificar que las variables de entorno estén cargadas
    db_host = os.getenv("DB_HOST")
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")
    db_name = os.getenv("DB_NAME")
    db_port = int(os.getenv("DB_PORT", 11537))

    if not db_host or not db_user:
        raise ValueError("Faltan las variables de entorno de la base de datos en el archivo .env")

    config = {
        "host": db_host,
        "port": db_port,
        "user": db_user,
        "password": db_password,
        "database": db_name,
    }

    # Si tienen el certificado oficial de Aiven (ca.pem) en la raíz del proyecto
    ruta_ca = os.path.join(os.path.dirname(__file__), "ca.pem")
    if os.path.exists(ruta_ca):
        config["ssl_ca"] = ruta_ca
        return mysql.connector.connect(**config)

    # Si no tienen el ca.pem, intentar primero con ssl_disabled=True
    try:
        return mysql.connector.connect(**config, ssl_disabled=True)
    except Exception:
        # Fallback para versiones o sistemas donde ssl_disabled no es soportado
        return mysql.connector.connect(**config)