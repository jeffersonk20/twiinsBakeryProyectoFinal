import os
import re
import socket
import ssl as ssl_mod
import sqlite3
import datetime
import logging
from decimal import Decimal
from dotenv import load_dotenv
import mysql.connector

# Configuración del logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)
logger = logging.getLogger("twins_bakery_db")

load_dotenv()


# =====================================================================
# WRAPPER COMPATIBLE PARA SQLITE (Permite ejecutar el proyecto sin MySQL)
# =====================================================================

class SmartDateTime(str):
    """Cadena con soporte para el método strftime en caso de que Jinja lo invoque."""
    def strftime(self, fmt):
        try:
            clean = self.replace(" ", "T") if " " in self else self
            return datetime.datetime.fromisoformat(clean).strftime(fmt)
        except Exception:
            return str(self)


def _parse_sqlite_value(val):
    """Convierte cadenas ISO de SQLite a objetos datetime o date nativos."""
    if isinstance(val, str):
        if len(val) >= 19 and val[4] == "-" and val[7] == "-":
            try:
                return datetime.datetime.fromisoformat(val.replace(" ", "T"))
            except Exception:
                return SmartDateTime(val)
        elif len(val) == 10 and val[4] == "-" and val[7] == "-":
            try:
                return datetime.date.fromisoformat(val)
            except Exception:
                return SmartDateTime(val)
    return val


class SQLiteRow(dict):
    """
    Fila compatible con dict y con tupla/lista (permite row['campo'] y row[0]).
    Satisface isinstance(row, dict) requerido por app.py.
    Convierte automáticamente campos de fecha/hora en objetos datetime reales.
    """
    def __init__(self, cursor, row):
        super().__init__()
        parsed = []
        for idx, col in enumerate(cursor.description):
            v = _parse_sqlite_value(row[idx])
            self[col[0]] = v
            parsed.append(v)
        self._row = tuple(parsed)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._row[key]
        return super().__getitem__(key)

    def get(self, key, default=None):
        if isinstance(key, int):
            return self._row[key] if 0 <= key < len(self._row) else default
        return super().get(key, default)



class SQLiteCursorWrapper:
    """Cursor compatible con la interfaz de mysql.connector."""

    def __init__(self, connection, dictionary=False):
        self._conn = connection
        self._dictionary = dictionary
        self._cursor = connection._sqlite_conn.cursor()
        self.rowcount = -1
        self.lastrowid = None
        self.description = None
        self._custom_rows = None
        self._custom_idx = 0

    def execute(self, query, params=None):
        q = query.strip()

        # Emulación de comandos MySQL SHOW para compatibilidad
        if re.match(r"^SHOW\s+COLUMNS\s+FROM\s+(\w+)", q, re.IGNORECASE):
            m = re.match(r"^SHOW\s+COLUMNS\s+FROM\s+(\w+)", q, re.IGNORECASE)
            table = m.group(1)
            self._cursor.execute(f"PRAGMA table_info({table})")
            cols = self._cursor.fetchall()
            rows = []
            for col in cols:
                rows.append({
                    "Field": col[1],
                    "Type": col[2],
                    "Null": "NO" if col[3] else "YES",
                    "Key": "PRI" if col[5] else "",
                    "Default": col[4],
                    "Extra": ""
                })
            self._custom_rows = rows
            self._custom_idx = 0
            self.description = [("Field",), ("Type",), ("Null",), ("Key",), ("Default",), ("Extra",)]
            self.rowcount = len(rows)
            return self

        if re.match(r"^SHOW\s+(?:FULL\s+)?TABLES\s+LIKE\s+['\"](.*?)['\"]", q, re.IGNORECASE):
            m = re.search(r"LIKE\s+['\"](.*?)['\"]", q, re.IGNORECASE)
            pattern = m.group(1).replace("%", "*")
            self._cursor.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view')")
            all_tables = self._cursor.fetchall()
            import fnmatch
            filtered = [r for r in all_tables if fnmatch.fnmatch(r[0], pattern)]
            rows = [{"Tables_in_db": r[0], "Table_type": "VIEW" if r[1] == "view" else "BASE TABLE"} for r in filtered]
            self._custom_rows = rows
            self._custom_idx = 0
            self.description = [("Tables_in_db",), ("Table_type",)]
            self.rowcount = len(rows)
            return self

        if re.match(r"^SHOW\s+INDEX\s+FROM\s+(\w+)", q, re.IGNORECASE):
            m = re.match(r"^SHOW\s+INDEX\s+FROM\s+(\w+)", q, re.IGNORECASE)
            table = m.group(1)
            self._cursor.execute(f"PRAGMA index_list({table})")
            rows = [{"Key_name": r[1]} for r in self._cursor.fetchall()]
            self._custom_rows = rows
            self._custom_idx = 0
            self.description = [("Key_name",)]
            self.rowcount = len(rows)
            return self

        if re.match(r"^SHOW\s+CREATE\s+TABLE\s+(\w+)", q, re.IGNORECASE):
            m = re.match(r"^SHOW\s+CREATE\s+TABLE\s+(\w+)", q, re.IGNORECASE)
            table = m.group(1)
            self._cursor.execute("SELECT sql FROM sqlite_master WHERE name = ?", (table,))
            res = self._cursor.fetchone()
            sql_def = res[0] if res else ""
            self._custom_rows = [{"Table": table, "Create Table": sql_def}]
            self._custom_idx = 0
            self.description = [("Table",), ("Create Table",)]
            self.rowcount = 1 if res else 0
            return self

        self._custom_rows = None

        # Transformaciones de sintaxis MySQL a SQLite
        # 1. Quitar FOR UPDATE
        q = re.sub(r"\s+FOR\s+UPDATE\b", "", q, flags=re.IGNORECASE)
        # 2. Quitar ENGINE=InnoDB
        q = re.sub(r"\s*ENGINE\s*=\s*\w+", "", q, flags=re.IGNORECASE)
        # 3. AUTO_INCREMENT -> AUTOINCREMENT
        q = re.sub(r"\bAUTO_INCREMENT\b", "AUTOINCREMENT", q, flags=re.IGNORECASE)
        # 4. En SQLite AUTOINCREMENT solo es válido en INTEGER PRIMARY KEY
        q = re.sub(r"\bINT\s+AUTOINCREMENT\s+PRIMARY\s+KEY\b", "INTEGER PRIMARY KEY AUTOINCREMENT", q, flags=re.IGNORECASE)
        q = re.sub(r"\bINT\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b", "INTEGER PRIMARY KEY AUTOINCREMENT", q, flags=re.IGNORECASE)
        # 5. MEDIUMBLOB -> BLOB
        q = re.sub(r"\bMEDIUMBLOB\b", "BLOB", q, flags=re.IGNORECASE)

        # 6. Reemplazar %s por ? respetando comillas
        parts = []
        in_quote = False
        quote_char = ''
        i = 0
        while i < len(q):
            c = q[i]
            if not in_quote and (c == "'" or c == '"'):
                in_quote = True
                quote_char = c
                parts.append(c)
            elif in_quote and c == quote_char:
                if i + 1 < len(q) and q[i+1] == quote_char:
                    parts.append(c)
                    parts.append(q[i+1])
                    i += 1
                else:
                    in_quote = False
                    parts.append(c)
            elif not in_quote and c == '%' and i + 1 < len(q) and q[i+1] == 's':
                parts.append('?')
                i += 1
            else:
                parts.append(c)
            i += 1
        q = "".join(parts)

        # Convertir tipos de parámetros incompatibles con sqlite3
        conv_params = []
        if params is not None:
            for p in params:
                if isinstance(p, Decimal):
                    conv_params.append(float(p))
                elif isinstance(p, (datetime.date, datetime.datetime, datetime.time)):
                    conv_params.append(str(p))
                else:
                    conv_params.append(p)
            params = tuple(conv_params)

        try:
            if params:
                self._cursor.execute(q, params)
            else:
                self._cursor.execute(q)
            self.rowcount = self._cursor.rowcount
            self.lastrowid = self._cursor.lastrowid
            self.description = self._cursor.description
        except sqlite3.IntegrityError as e:
            err_str = str(e)
            if "UNIQUE" in err_str or "PRIMARY KEY" in err_str:
                raise mysql.connector.Error(msg=err_str, errno=1062)
            raise mysql.connector.Error(msg=err_str, errno=1000)
        except sqlite3.Error as e:
            raise mysql.connector.Error(msg=str(e), errno=1000)

        return self

    def fetchone(self):
        if self._custom_rows is not None:
            if self._custom_idx < len(self._custom_rows):
                res = self._custom_rows[self._custom_idx]
                self._custom_idx += 1
                if self._dictionary:
                    return res
                return tuple(res.values())
            return None

        row = self._cursor.fetchone()
        if row is None:
            return None
        if self._dictionary:
            return SQLiteRow(self._cursor, row)
        return tuple(_parse_sqlite_value(v) for v in row)

    def fetchall(self):
        if self._custom_rows is not None:
            res = self._custom_rows[self._custom_idx:]
            self._custom_idx = len(self._custom_rows)
            if self._dictionary:
                return res
            return [tuple(r.values()) for r in res]

        rows = self._cursor.fetchall()
        if self._dictionary:
            return [SQLiteRow(self._cursor, r) for r in rows]
        return [tuple(_parse_sqlite_value(v) for v in r) for r in rows]

    def close(self):
        try:
            self._cursor.close()
        except Exception:
            pass

    def __iter__(self):
        return iter(self.fetchall())

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


class SQLiteConnectionWrapper:
    """Wrapper sobre sqlite3.Connection compatible con mysql.connector."""

    def __init__(self, db_path):
        self.db_path = db_path
        self._sqlite_conn = sqlite3.connect(db_path, check_same_thread=False)
        self._is_open = True
        self._sqlite_conn.execute("PRAGMA foreign_keys = ON;")
        self._setup_functions()

    def _setup_functions(self):
        conn = self._sqlite_conn
        conn.create_function("NOW", 0, lambda: datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        conn.create_function("CURRENT_DATE", 0, lambda: datetime.datetime.now().strftime("%Y-%m-%d"))
        conn.create_function("CONCAT", -1, lambda *args: "".join(str(a) if a is not None else "" for a in args))
        conn.create_function("TIMESTAMP", 2, lambda d, t: f"{d} {t}")

    def cursor(self, dictionary=False, **kwargs):
        return SQLiteCursorWrapper(self, dictionary=dictionary)

    def commit(self):
        self._sqlite_conn.commit()

    def rollback(self):
        self._sqlite_conn.rollback()

    def start_transaction(self):
        pass  # SQLite maneja transacciones en sentencias DML

    def is_connected(self):
        return self._is_open

    def close(self):
        self._is_open = False
        try:
            self._sqlite_conn.close()
        except Exception:
            pass


# =====================================================================
# CONEXIÓN MYSQL / AIVEN
# =====================================================================

def _verificar_conectividad(host, port, timeout=4):
    """Verifica que el servidor sea alcanzable via TCP antes de intentar SSL."""
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        sock.close()
        return True
    except (socket.timeout, socket.error, OSError) as e:
        logger.warning("No se puede conectar al servidor MySQL %s:%s - %s", host, port, e)
        return False


def _intentar_mysql_connector(config, timeout):
    """Intenta conectar usando mysql-connector-python."""
    ruta_ca = os.path.join(os.path.dirname(__file__), "ca.pem")

    # Si tienen el certificado oficial de Aiven (ca.pem) en la raíz
    if os.path.exists(ruta_ca):
        try:
            conn = mysql.connector.connect(**config, ssl_ca=ruta_ca)
            logger.info("mysql-connector conectado exitosamente usando ca.pem.")
            return conn
        except Exception as e:
            logger.warning("mysql-connector con ssl_ca falló: %s", e)

    # Variantes con TLS relajado
    variantes = [
        {"use_pure": True, "ssl_verify_cert": False, "ssl_verify_identity": False},
        {"ssl_disabled": True},
        {},
    ]

    for i, extra in enumerate(variantes, 1):
        try:
            cfg = dict(config)
            cfg.update(extra)
            conn = mysql.connector.connect(**cfg)
            logger.info("mysql-connector conectado exitosamente (variante %d).", i)
            return conn
        except Exception as e:
            logger.debug("mysql-connector variante %d falló: %s", i, e)

    return None


def _intentar_pymysql(config):
    """Intenta conectar usando PyMySQL como fallback."""
    try:
        import pymysql
    except ImportError:
        return None

    ssl_context = ssl_mod.create_default_context()
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl_mod.CERT_NONE

    ruta_ca = os.path.join(os.path.dirname(__file__), "ca.pem")
    if os.path.exists(ruta_ca):
        try:
            ssl_context.load_verify_locations(ruta_ca)
        except Exception:
            pass

    try:
        conn = pymysql.connect(
            host=config["host"],
            port=config["port"],
            user=config["user"],
            password=config["password"],
            database=config["database"],
            ssl=ssl_context,
            connect_timeout=config.get("connection_timeout", 5),
            read_timeout=config.get("connection_timeout", 5),
            write_timeout=config.get("connection_timeout", 5),
        )
        logger.info("PyMySQL conectado exitosamente.")
        return conn
    except Exception as e:
        logger.warning("PyMySQL falló: %s", e)
        return None


class PyMySQLCursorWrapper:
    """Wrapper para que el cursor de PyMySQL soporte dictionary=True como mysql-connector."""

    def __init__(self, conn):
        import pymysql.cursors
        self._cursor = conn.cursor(pymysql.cursors.DictCursor)

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    def __iter__(self):
        return iter(self._cursor)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self._cursor.close()


class ConnectionWrapper:
    """Wrapper para unificar la interfaz entre mysql-connector y PyMySQL."""

    def __init__(self, conn, driver="mysql-connector"):
        self._conn = conn
        self._driver = driver

    def cursor(self, dictionary=False, **kwargs):
        if self._driver == "pymysql" and dictionary:
            return PyMySQLCursorWrapper(self._conn)
        elif self._driver == "pymysql":
            return self._conn.cursor()
        return self._conn.cursor(dictionary=dictionary, **kwargs)

    def is_connected(self):
        if self._driver == "pymysql":
            return bool(getattr(self._conn, "open", False))
        return self._conn.is_connected()

    def start_transaction(self):
        if hasattr(self._conn, "start_transaction"):
            self._conn.start_transaction()
        elif hasattr(self._conn, "begin"):
            self._conn.begin()

    def __getattr__(self, name):
        return getattr(self._conn, name)


# =====================================================================
# FUNCIÓN PRINCIPAL DE CONEXIÓN
# =====================================================================

def obtener_conexion():
    """
    Obtiene la conexión a la base de datos.
    Soporta MySQL (Aiven/Local) y SQLite como fallback automático.
    Configurable vía DB_TYPE ('mysql', 'sqlite', o 'auto').
    """
    db_type = os.getenv("DB_TYPE", "auto").strip().lower()
    sqlite_path = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "twins_bakery.db"))

    # Si se pide explícitamente SQLite
    if db_type == "sqlite":
        logger.info("Conectando a base de datos SQLite: %s", sqlite_path)
        return SQLiteConnectionWrapper(sqlite_path)

    # Parámetros MySQL
    db_host = os.getenv("DB_HOST")
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD", "")
    db_name = os.getenv("DB_NAME", "defaultdb")
    db_port = int(os.getenv("DB_PORT", 11537))
    connection_timeout = int(os.getenv("DB_TIMEOUT", "4"))

    # Si faltan credenciales y estamos en modo auto, ir a SQLite
    if not db_host or not db_user:
        if db_type == "auto":
            logger.warning("No hay credenciales MySQL completas en .env. Usando base de datos local SQLite.")
            return SQLiteConnectionWrapper(sqlite_path)
        raise ValueError("Faltan variables de entorno DB_HOST o DB_USER en .env")

    config = {
        "host": db_host,
        "port": db_port,
        "user": db_user,
        "password": db_password,
        "database": db_name,
        "connection_timeout": connection_timeout,
    }

    # Intentar conexión MySQL
    logger.info("Intentando conectar a MySQL en %s:%s...", db_host, db_port)
    if _verificar_conectividad(db_host, db_port, timeout=connection_timeout):
        conn = _intentar_mysql_connector(config, connection_timeout)
        if conn:
            return conn

        conn = _intentar_pymysql(config)
        if conn:
            return ConnectionWrapper(conn, driver="pymysql")

    # Si falló la conexión a MySQL:
    if db_type == "auto":
        logger.warning(
            "⚠️ No se pudo conectar al servidor MySQL (%s:%s). "
            "Activando respaldo automático a base de datos local SQLite: %s",
            db_host, db_port, sqlite_path
        )
        return SQLiteConnectionWrapper(sqlite_path)

    # Si db_type == 'mysql' y falló, lanzar error descriptivo
    error_msg = (
        f"\n{'='*60}\n"
        f"ERROR: No se pudo conectar a la base de datos MySQL en {db_host}:{db_port}\n"
        f"{'='*60}\n"
        f"Si estás trabajando localmente y no tienes acceso a Aiven, añade:\n"
        f"  DB_TYPE=sqlite\n"
        f"en tu archivo .env para usar la base de datos local automática.\n"
        f"{'='*60}\n"
    )
    logger.error(error_msg)
    raise ConnectionError(error_msg)