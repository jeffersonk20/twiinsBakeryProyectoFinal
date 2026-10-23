"""
Módulo de Acceso a Base de Datos de Solo Lectura (Read-Only) y Aislamiento Físico de Contexto.
Cumple con el principio de Mínimo Privilegio (Principle of Least Privilege):
1. Las consultas del Asistente de IA se ejecutan con usuario de BD de SOLO LECTURA (SELECT).
2. Para SQLite, fuerza conexión URI con 'mode=ro' y 'PRAGMA query_only = ON'.
3. Aislamiento Físico: El rol 'cliente' NUNCA ejecuta consultas hacia tablas de usuarios,
   reservas o pagos, y NUNCA expone el conteo numérico de stock (solo 'Disponible'/'Agotado').
"""

import os
import re
import sqlite3
import logging
from typing import Dict, Any, List
import mysql.connector
from .ia_config import (
    DB_TYPE,
    DB_PATH,
    DB_RO_USER,
    DB_RO_PASSWORD,
    DB_RO_HOST,
    DB_RO_PORT,
    DB_RO_NAME,
    DB_TIMEOUT,
)
from .ia_cifrado import descifrar_texto

logger = logging.getLogger("twins_ia_database")

# Palabras clave prohibidas en el canal de solo lectura de la IA
PALABRAS_PROHIBIDAS_RO = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|EXEC|EXECUTE|GRANT|REVOKE|ATTACH|DETACH)\b",
    re.IGNORECASE,
)


def _validar_consulta_solo_lectura(sql: str) -> None:
    """Verifica sintácticamente que la sentencia comience por SELECT o WITH y no contenga mutaciones."""
    sql_limpio = sql.strip()
    if not (sql_limpio.upper().startswith("SELECT") or sql_limpio.upper().startswith("WITH")):
        raise PermissionError(
            f"Violación de Seguridad: La IA solo tiene permitido ejecutar sentencias SELECT. Consulta rechazada: {sql_limpio[:40]}..."
        )
    if PALABRAS_PROHIBIDAS_RO.search(sql_limpio):
        raise PermissionError(
            "Violación de Seguridad: Detectada palabra clave de mutación en consulta de solo lectura."
        )


def _obtener_conexion_solo_lectura():
    """
    Establece una conexión estrictamente de SOLO LECTURA.
    - En SQLite: 'file:path?mode=ro' + 'PRAGMA query_only = ON'.
    - En MySQL: Credenciales DB_RO_USER o sesión 'SET SESSION TRANSACTION READ ONLY'.
    """
    tipo = DB_TYPE

    # Si es SQLite o modo auto sin host MySQL configurado
    if tipo == "sqlite" or (tipo == "auto" and not DB_RO_HOST):
        if not os.path.exists(DB_PATH):
            raise FileNotFoundError(f"Base de datos SQLite no encontrada en {DB_PATH}")
        # Abrir SQLite en modo lectura estricta mediante URI
        uri_ro = f"file:{os.path.abspath(DB_PATH)}?mode=ro"
        conn = sqlite3.connect(uri_ro, uri=True, timeout=DB_TIMEOUT)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("PRAGMA query_only = ON;")
        cursor.close()
        return conn, "sqlite"

    # Conexión MySQL / MariaDB / Cloud
    usuario_ro = DB_RO_USER if DB_RO_USER else os.getenv("DB_USER", "")
    password_ro = DB_RO_PASSWORD if DB_RO_PASSWORD else os.getenv("DB_PASSWORD", "")

    config = {
        "host": DB_RO_HOST,
        "port": DB_RO_PORT,
        "user": usuario_ro,
        "password": password_ro,
        "database": DB_RO_NAME,
        "connection_timeout": DB_TIMEOUT,
    }

    try:
        conn = mysql.connector.connect(**config)
        # Forzar transacción de solo lectura a nivel de sesión MySQL
        cursor = conn.cursor()
        try:
            cursor.execute("SET SESSION TRANSACTION READ ONLY;")
        except Exception:
            pass
        finally:
            cursor.close()
        return conn, "mysql"
    except Exception as exc:
        if tipo == "auto":
            logger.warning(
                "No se pudo conectar a MySQL con usuario de lectura (%s). Usando respaldo SQLite RO.", exc
            )
            uri_ro = f"file:{os.path.abspath(DB_PATH)}?mode=ro"
            conn = sqlite3.connect(uri_ro, uri=True, timeout=DB_TIMEOUT)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("PRAGMA query_only = ON;")
            cursor.close()
            return conn, "sqlite"
        raise exc


# ==============================================================================
# PAQUETES DE EVENTOS (PÚBLICOS - CONTEXTO PARA CLIENTES Y ADMINISTRADORES)
# ==============================================================================
PAQUETES_EVENTOS_INFO = [
    {
        "tipo": "Bodas",
        "titulo": "Bodas & Nupcias Soñadas",
        "descripcion": "Pasteles de alta gama de 2 o 3 niveles, mesa de degustación previa, mini postres artesanales y montaje.",
        "condiciones": "Reserva con 15 a 30 días de anticipación. Anticipo del 50%.",
    },
    {
        "tipo": "Graduaciones",
        "titulo": "Logros & Graduaciones",
        "descripcion": "Pasteles temáticos con birretes y diplomas en fondant comestible, docena de galletas alusivas y topper.",
        "condiciones": "Reserva mínima con 5 días de anticipación. Anticipo del 50%.",
    },
    {
        "tipo": "Baby Shower",
        "titulo": "Baby Shower & Revelación de Género",
        "descripcion": "Pasteles en tonos pastel con relleno sorpresa secreto (rosa o azul) para gender reveal y cupcakes a juego.",
        "condiciones": "Reserva con 5 días de anticipación. Entrega de sobre cerrado para revelación.",
    },
    {
        "tipo": "Aniversarios",
        "titulo": "Aniversarios & Fechas Románticas",
        "descripcion": "Pasteles estilo vintage en forma de corazón (estilo Lambeth), caja de fresas cubiertas con chocolate belga y empaque de lujo.",
        "condiciones": "Reserva de 3 a 5 días de anticipación. Anticipo del 50%.",
    },
]


# ==============================================================================
# AISLAMIENTO FÍSICO 1: CONTEXTO PARA VISTA CLIENTE
# ==============================================================================

def obtener_contexto_cliente() -> Dict[str, Any]:
    """
    Consulta estrictamente los datos públicos de PRODUCTOS y EVENTOS.
    REGLA DE SEGURIDAD CRÍTICA:
    - NO consulta tablas CLIENTE, RESERVA, PAGO, ADMINISTRADOR ni INVENTARIO numérico.
    - El stock numérico NUNCA se extrae. Solo se clasifica en 'Disponible' o 'Agotado'.
    """
    productos = []
    conexion = None
    cursor = None

    try:
        conexion, motor = _obtener_conexion_solo_lectura()
        # Consulta segura: solo productos marcados como disponibles
        query = """
            SELECT p.id_producto, p.nombre, p.categoria, p.precio, p.descripcion, p.disponible,
                   COALESCE(i.stock, 1) as stock_indicador
            FROM PRODUCTO p
            LEFT JOIN INVENTARIO i ON p.id_producto = i.id_pastel
            WHERE p.disponible = 1
            ORDER BY p.categoria, p.nombre
        """
        _validar_consulta_solo_lectura(query)

        if motor == "sqlite":
            cursor = conexion.cursor()
            cursor.execute(query)
            filas = cursor.fetchall()
            for row in filas:
                stock_val = row["stock_indicador"] if "stock_indicador" in row.keys() else 1
                # Transformación obligatoria de privacidad:
                # El cliente JAMÁS recibe la cifra numérica, solo el estado cualitativo
                estado_disponibilidad = "Disponible" if (stock_val is not None and stock_val > 0) else "Agotado"
                productos.append({
                    "nombre": row["nombre"],
                    "categoria": row["categoria"] or "General",
                    "precio": float(row["precio"]),
                    "descripcion": row["descripcion"] or "Delicioso producto artesanal de TWINS Bakery.",
                    "disponibilidad": estado_disponibilidad,
                })
        else:
            cursor = conexion.cursor(dictionary=True)
            cursor.execute(query)
            filas = cursor.fetchall()
            for row in filas:
                stock_val = row.get("stock_indicador", 1)
                estado_disponibilidad = "Disponible" if (stock_val is not None and stock_val > 0) else "Agotado"
                productos.append({
                    "nombre": row["nombre"],
                    "categoria": row.get("categoria") or "General",
                    "precio": float(row["precio"]),
                    "descripcion": row.get("descripcion") or "Delicioso producto artesanal de TWINS Bakery.",
                    "disponibilidad": estado_disponibilidad,
                })

    except Exception as exc:
        logger.error("Error al obtener contexto para cliente: %s", exc)
    finally:
        if cursor:
            cursor.close()
        if conexion:
            conexion.close()

    return {
        "productos": productos,
        "eventos": PAQUETES_EVENTOS_INFO,
        "politicas": {
            "pedidos_a_domicilio": "TWINS Bakery NO realiza pedidos a domicilio. Todos los retiros son en tienda.",
            "reservas": "La IA no toma reservas. Las reservas se realizan manualmente a través de la página web o contactando directamente.",
            "anticipo": "Se requiere un 50% de anticipo para confirmar toda reserva.",
            "contacto_oficial": {
                "correo": "pedidos@twinsbakery.com",
                "telefono": "+503 2234-5678",
                "horario": "Lunes a Sábado de 8:00 AM a 6:00 PM",
            },
        },
    }


# ==============================================================================
# AISLAMIENTO FÍSICO 2: CONTEXTO PARA VISTA ADMINISTRADOR
# ==============================================================================

def obtener_contexto_administrador() -> Dict[str, Any]:
    """
    Consulta el contexto completo para la vista de Inteligencia de Negocios del Administrador.
    Solo se ejecuta tras validar la autenticación administrativa (JWT o sesión).
    Incluye:
    - Inventario con conteos numéricos reales.
    - Métricas de reservas por estado y montos financieros.
    - Últimas reservas registradas con nombres de clientes descifrados para seguimiento operativo.
    - Resumen de solicitudes de eventos.
    """
    conexion = None
    cursor = None

    contexto = {
        "inventario_real": [],
        "metricas_reservas": {},
        "resumen_financiero": {
            "total_reservas": 0,
            "monto_total_ventas": 0.0,
            "total_cobrado_anticipos": 0.0,
        },
        "ultimas_reservas": [],
        "eventos_catalogo": PAQUETES_EVENTOS_INFO,
    }

    try:
        conexion, motor = _obtener_conexion_solo_lectura()

        # 1. Inventario numérico real de productos
        q_inventario = """
            SELECT p.id_producto, p.nombre, p.categoria, p.precio, p.disponible,
                   COALESCE(i.stock, 0) as stock_real
            FROM PRODUCTO p
            LEFT JOIN INVENTARIO i ON p.id_producto = i.id_pastel
            ORDER BY stock_real ASC, p.nombre ASC
        """
        _validar_consulta_solo_lectura(q_inventario)

        if motor == "sqlite":
            cursor = conexion.cursor()
            cursor.execute(q_inventario)
            for r in cursor.fetchall():
                contexto["inventario_real"].append({
                    "id": r["id_producto"],
                    "nombre": r["nombre"],
                    "categoria": r["categoria"],
                    "precio": float(r["precio"]),
                    "stock_numerico": int(r["stock_real"]),
                    "activo_en_catalogo": bool(r["disponible"]),
                })
            cursor.close()

            # 2. Métricas de reservas agrupadas por estado
            q_estados = "SELECT estado, COUNT(*) as cantidad, COALESCE(SUM(total), 0) as total_monto FROM RESERVA GROUP BY estado"
            _validar_consulta_solo_lectura(q_estados)
            cursor = conexion.cursor()
            cursor.execute(q_estados)
            for r in cursor.fetchall():
                contexto["metricas_reservas"][r["estado"]] = {
                    "cantidad": int(r["cantidad"]),
                    "monto_total": float(r["total_monto"]),
                }
            cursor.close()

            # 3. Totales financieros globales (excluyendo canceladas)
            q_finanzas = """
                SELECT COUNT(*) as cant,
                       COALESCE(SUM(total), 0) as ventas,
                       COALESCE(SUM(monto_pagado), 0) as cobrado
                FROM RESERVA
                WHERE estado != 'CANCELADA'
            """
            _validar_consulta_solo_lectura(q_finanzas)
            cursor = conexion.cursor()
            cursor.execute(q_finanzas)
            fin_row = cursor.fetchone()
            if fin_row:
                contexto["resumen_financiero"] = {
                    "total_reservas_activas": int(fin_row["cant"]),
                    "monto_total_ventas": float(fin_row["ventas"]),
                    "total_cobrado_anticipos": float(fin_row["cobrado"]),
                }
            cursor.close()

            # 4. Últimas 10 reservas para análisis operativo
            q_recientes = """
                SELECT id_reserva, codigo, nombre_cliente, estado, total, anticipo_requerido, monto_pagado, fecha_retiro
                FROM RESERVA
                ORDER BY fecha_creacion DESC
                LIMIT 10
            """
            _validar_consulta_solo_lectura(q_recientes)
            cursor = conexion.cursor()
            cursor.execute(q_recientes)
            for r in cursor.fetchall():
                nombre_descifrado = descifrar_texto(r["nombre_cliente"])
                contexto["ultimas_reservas"].append({
                    "codigo": r["codigo"],
                    "cliente": nombre_descifrado,
                    "estado": r["estado"],
                    "total": float(r["total"]),
                    "anticipo_requerido": float(r["anticipo_requerido"]),
                    "monto_pagado": float(r["monto_pagado"]),
                    "fecha_retiro": str(r["fecha_retiro"])[:16],
                })
            cursor.close()

        else:
            # Motor MySQL
            cursor = conexion.cursor(dictionary=True)
            cursor.execute(q_inventario)
            for r in cursor.fetchall():
                contexto["inventario_real"].append({
                    "id": r["id_producto"],
                    "nombre": r["nombre"],
                    "categoria": r["categoria"],
                    "precio": float(r["precio"]),
                    "stock_numerico": int(r["stock_real"]),
                    "activo_en_catalogo": bool(r["disponible"]),
                })

            cursor.execute(
                "SELECT estado, COUNT(*) as cantidad, COALESCE(SUM(total), 0) as total_monto FROM RESERVA GROUP BY estado"
            )
            for r in cursor.fetchall():
                contexto["metricas_reservas"][r["estado"]] = {
                    "cantidad": int(r["cantidad"]),
                    "monto_total": float(r["total_monto"]),
                }

            cursor.execute(
                "SELECT COUNT(*) as cant, COALESCE(SUM(total), 0) as ventas, COALESCE(SUM(monto_pagado), 0) as cobrado FROM RESERVA WHERE estado != 'CANCELADA'"
            )
            fin_row = cursor.fetchone()
            if fin_row:
                contexto["resumen_financiero"] = {
                    "total_reservas_activas": int(fin_row["cant"]),
                    "monto_total_ventas": float(fin_row["ventas"]),
                    "total_cobrado_anticipos": float(fin_row["cobrado"]),
                }

            cursor.execute(
                "SELECT id_reserva, codigo, nombre_cliente, estado, total, anticipo_requerido, monto_pagado, fecha_retiro FROM RESERVA ORDER BY fecha_creacion DESC LIMIT 10"
            )
            for r in cursor.fetchall():
                nombre_descifrado = descifrar_texto(r["nombre_cliente"])
                contexto["ultimas_reservas"].append({
                    "codigo": r["codigo"],
                    "cliente": nombre_descifrado,
                    "estado": r["estado"],
                    "total": float(r["total"]),
                    "anticipo_requerido": float(r["anticipo_requerido"]),
                    "monto_pagado": float(r["monto_pagado"]),
                    "fecha_retiro": str(r["fecha_retiro"])[:16],
                })

    except Exception as exc:
        logger.error("Error al obtener contexto para administrador: %s", exc)
    finally:
        if cursor:
            cursor.close()
        if conexion:
            conexion.close()

    return contexto
