import os
from werkzeug.security import generate_password_hash
# pyrefly: ignore[missing-import]
from conexion import obtener_conexion, SQLiteConnectionWrapper


def _migrar_detalle_producto_sqlite(conexion, cursor):
    cursor.execute("PRAGMA table_info(DETALLE_RESERVA)")
    columna_producto = next(
        (columna for columna in cursor.fetchall() if columna[1] == "id_pastel"),
        None,
    )
    cursor.execute("PRAGMA foreign_key_list(DETALLE_RESERVA)")
    referencia_producto = next(
        (
            referencia
            for referencia in cursor.fetchall()
            if referencia[3] == "id_pastel" and referencia[2] == "PRODUCTO"
        ),
        None,
    )
    if (
        columna_producto
        and columna_producto[3] == 0
        and referencia_producto
        and referencia_producto[6].upper() == "SET NULL"
    ):
        return

    conexion.commit()
    cursor.execute("PRAGMA foreign_keys = OFF")
    try:
        cursor.execute("DROP TABLE IF EXISTS DETALLE_RESERVA_NUEVA")
        cursor.execute("""
        CREATE TABLE DETALLE_RESERVA_NUEVA (
            id_detalle INTEGER PRIMARY KEY AUTOINCREMENT,
            id_reserva INT NOT NULL,
            id_pastel INT NULL,
            nombre_producto TEXT NOT NULL,
            precio_unitario NUMERIC NOT NULL,
            cantidad INT NOT NULL,
            FOREIGN KEY (id_reserva) REFERENCES RESERVA(id_reserva) ON DELETE CASCADE,
            FOREIGN KEY (id_pastel) REFERENCES PRODUCTO(id_producto) ON DELETE SET NULL
        );
        """)
        cursor.execute("""
        INSERT INTO DETALLE_RESERVA_NUEVA
            (id_detalle, id_reserva, id_pastel, nombre_producto, precio_unitario, cantidad)
        SELECT id_detalle, id_reserva, id_pastel, nombre_producto, precio_unitario, cantidad
        FROM DETALLE_RESERVA
        """)
        cursor.execute("DROP TABLE DETALLE_RESERVA")
        cursor.execute("ALTER TABLE DETALLE_RESERVA_NUEVA RENAME TO DETALLE_RESERVA")
        conexion.commit()
    except Exception:
        conexion.rollback()
        raise
    finally:
        cursor.execute("PRAGMA foreign_keys = ON")


def _migrar_detalle_producto_mysql(cursor):
    cursor.execute(
        """
        SELECT rc.CONSTRAINT_NAME, rc.DELETE_RULE
        FROM INFORMATION_SCHEMA.REFERENTIAL_CONSTRAINTS rc
        JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE kcu
          ON kcu.CONSTRAINT_SCHEMA = rc.CONSTRAINT_SCHEMA
         AND kcu.TABLE_NAME = rc.TABLE_NAME
         AND kcu.CONSTRAINT_NAME = rc.CONSTRAINT_NAME
        WHERE rc.CONSTRAINT_SCHEMA = DATABASE()
          AND rc.TABLE_NAME = 'DETALLE_RESERVA'
          AND kcu.COLUMN_NAME = 'id_pastel'
          AND kcu.REFERENCED_TABLE_NAME = 'PRODUCTO'
          AND kcu.REFERENCED_COLUMN_NAME = 'id_producto'
        """
    )
    referencia_producto = cursor.fetchone()
    cursor.execute(
        """
        SELECT IS_NULLABLE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = 'DETALLE_RESERVA'
          AND COLUMN_NAME = 'id_pastel'
        """
    )
    columna_producto = cursor.fetchone()
    if (
        referencia_producto
        and referencia_producto[1].upper() == "SET NULL"
        and columna_producto
        and columna_producto[0].upper() == "YES"
    ):
        return

    if referencia_producto:
        nombre_restriccion = referencia_producto[0].replace("`", "``")
        cursor.execute(
            f"ALTER TABLE DETALLE_RESERVA DROP FOREIGN KEY `{nombre_restriccion}`"
        )
    cursor.execute(
        """
        ALTER TABLE DETALLE_RESERVA
        MODIFY id_pastel INT NULL,
        ADD CONSTRAINT fk_detalle_producto
            FOREIGN KEY (id_pastel) REFERENCES PRODUCTO(id_producto) ON DELETE SET NULL
        """
    )


def _inicializar_sqlite(conexion, cursor):
    """Inicializa la base de datos utilizando sintaxis nativa de SQLite."""
    print("Configurando esquema para SQLite...")

    # 1. CLIENTE
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS CLIENTE (
        id_cliente INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        correo TEXT NOT NULL UNIQUE,
        contrasena TEXT NOT NULL,
        fecha_registro DATE DEFAULT (CURRENT_DATE),
        correo_verificado BOOLEAN NOT NULL DEFAULT 1
    );
    """)
    try:
        cursor.execute("ALTER TABLE CLIENTE ADD COLUMN correo_verificado BOOLEAN NOT NULL DEFAULT 1;")
    except Exception:
        pass

    # 2. ADMINISTRADOR
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ADMINISTRADOR (
        id_admin INTEGER PRIMARY KEY,
        nombre TEXT NOT NULL,
        correo TEXT NOT NULL UNIQUE,
        contrasena TEXT NOT NULL,
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT chk_unico_administrador CHECK (id_admin = 1)
    );
    """)

    # 3. PRODUCTO
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS PRODUCTO (
        id_producto INTEGER PRIMARY KEY AUTOINCREMENT,
        id_admin INT NULL,
        nombre TEXT NOT NULL,
        categoria TEXT NULL,
        precio NUMERIC NOT NULL,
        descripcion TEXT NOT NULL,
        disponible BOOLEAN NOT NULL DEFAULT 1,
        en_vitrina BOOLEAN NOT NULL DEFAULT 0,
        imagen BLOB NULL,
        tipo_imagen TEXT NULL,
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (id_admin) REFERENCES ADMINISTRADOR(id_admin) ON DELETE SET NULL
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_producto_catalogo ON PRODUCTO (disponible, categoria);")

    # 4. RESERVA
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS RESERVA (
        id_reserva INTEGER PRIMARY KEY AUTOINCREMENT,
        codigo TEXT NOT NULL UNIQUE,
        id_cliente INT NULL,
        fecha_reserva TIMESTAMP NOT NULL,
        fecha_retiro TIMESTAMP NOT NULL,
        estado TEXT NOT NULL DEFAULT 'PENDIENTE_PAGO',
        nombre_cliente TEXT NOT NULL,
        correo TEXT NULL,
        telefono TEXT NOT NULL,
        total NUMERIC NOT NULL,
        anticipo_requerido NUMERIC NOT NULL,
        monto_pagado NUMERIC NOT NULL DEFAULT 0,
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (id_cliente) REFERENCES CLIENTE(id_cliente) ON DELETE CASCADE
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reserva_cliente ON RESERVA (id_cliente);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reserva_estado_fecha ON RESERVA (estado, fecha_retiro);")

    # 5. DETALLE_RESERVA
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS DETALLE_RESERVA (
        id_detalle INTEGER PRIMARY KEY AUTOINCREMENT,
        id_reserva INT NOT NULL,
        id_pastel INT NULL,
        nombre_producto TEXT NOT NULL,
        precio_unitario NUMERIC NOT NULL,
        cantidad INT NOT NULL,
        FOREIGN KEY (id_reserva) REFERENCES RESERVA(id_reserva) ON DELETE CASCADE,
        FOREIGN KEY (id_pastel) REFERENCES PRODUCTO(id_producto) ON DELETE SET NULL
    );
    """)
    _migrar_detalle_producto_sqlite(conexion, cursor)

    # 6. PAGO
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS PAGO (
        id_pago INTEGER PRIMARY KEY AUTOINCREMENT,
        id_reserva INT NOT NULL,
        metodo_pago TEXT NOT NULL,
        monto NUMERIC NOT NULL,
        fecha_pago TIMESTAMP NULL,
        estado TEXT NOT NULL DEFAULT 'PENDIENTE',
        referencia TEXT NOT NULL UNIQUE,
        referencia_wompi TEXT NULL,
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (id_reserva) REFERENCES RESERVA(id_reserva) ON DELETE CASCADE
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_pago_reserva_estado ON PAGO (id_reserva, estado);")

    # 7. INVENTARIO
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS INVENTARIO (
        id_inventario INTEGER PRIMARY KEY AUTOINCREMENT,
        id_pastel INT NOT NULL UNIQUE,
        stock INT NOT NULL DEFAULT 0,
        FOREIGN KEY (id_pastel) REFERENCES PRODUCTO(id_producto) ON DELETE CASCADE
    );
    """)

    # 8. MOVIMIENTO_INVENTARIO
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS MOVIMIENTO_INVENTARIO (
        id_movimiento INTEGER PRIMARY KEY AUTOINCREMENT,
        id_inventario INT NOT NULL,
        id_admin INT NULL,
        cantidad INT NOT NULL,
        fecha_movimiento TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        tipo_movimiento TEXT NOT NULL,
        FOREIGN KEY (id_inventario) REFERENCES INVENTARIO(id_inventario) ON DELETE CASCADE,
        FOREIGN KEY (id_admin) REFERENCES ADMINISTRADOR(id_admin) ON DELETE SET NULL
    );
    """)

    # 9. CHAT
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS CHAT (
        id_chat INTEGER PRIMARY KEY AUTOINCREMENT,
        id_cliente INT NOT NULL,
        id_admin INT NULL,
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (id_cliente) REFERENCES CLIENTE(id_cliente) ON DELETE CASCADE,
        FOREIGN KEY (id_admin) REFERENCES ADMINISTRADOR(id_admin) ON DELETE SET NULL
    );
    """)

    # 10. MENSAJE
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS MENSAJE (
        id_mensaje INTEGER PRIMARY KEY AUTOINCREMENT,
        id_chat INT NOT NULL,
        rol TEXT NOT NULL,
        mensaje TEXT NOT NULL,
        fecha_envio TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (id_chat) REFERENCES CHAT(id_chat) ON DELETE CASCADE
    );
    """)

    # 11. VISTA PASTEL
    cursor.execute("DROP VIEW IF EXISTS PASTEL;")
    cursor.execute("""
    CREATE VIEW PASTEL AS
    SELECT id_producto AS id_pastel, id_admin, nombre,
           categoria AS tipo_venta, precio
    FROM PRODUCTO;
    """)

    # 12. DASHBOARD
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS DASHBOARD (
        id_snapshot INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha_snapshot TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        reservas_hoy INTEGER NOT NULL DEFAULT 0,
        reservas_pendientes INTEGER NOT NULL DEFAULT 0,
        reservas_confirmadas INTEGER NOT NULL DEFAULT 0,
        reservas_en_preparacion INTEGER NOT NULL DEFAULT 0,
        reservas_listas INTEGER NOT NULL DEFAULT 0,
        reservas_entregadas INTEGER NOT NULL DEFAULT 0,
        reservas_canceladas INTEGER NOT NULL DEFAULT 0,
        productos_activos INTEGER NOT NULL DEFAULT 0
    );
    """)

    # Telefono en CLIENTE
    try:
        cursor.execute("ALTER TABLE CLIENTE ADD COLUMN telefono TEXT NULL;")
    except Exception:
        pass

    # 13. SOLICITUD_PLANIFICACION
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS SOLICITUD_PLANIFICACION (
        id_solicitud INTEGER PRIMARY KEY AUTOINCREMENT,
        id_cliente INT NOT NULL,
        tipo_evento TEXT NOT NULL,
        num_invitados INT NOT NULL,
        presupuesto_estimado NUMERIC NULL,
        fecha_evento DATE NOT NULL,
        lugar_evento TEXT NULL,
        servicios TEXT NULL,
        estado TEXT NOT NULL DEFAULT 'NUEVA',
        fecha_solicitud TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (id_cliente) REFERENCES CLIENTE(id_cliente) ON DELETE CASCADE
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_solicitud_cliente ON SOLICITUD_PLANIFICACION (id_cliente);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_solicitud_estado ON SOLICITUD_PLANIFICACION (estado);")

    # 14. CHAT_EVENTO (Relación 1:1 estricta con SOLICITUD_PLANIFICACION via id_solicitud UNIQUE)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS CHAT_EVENTO (
        id_chat_evento INTEGER PRIMARY KEY AUTOINCREMENT,
        id_solicitud INT NOT NULL UNIQUE,
        id_cliente INT NOT NULL,
        id_admin INT NULL,
        titulo TEXT NOT NULL,
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (id_solicitud) REFERENCES SOLICITUD_PLANIFICACION(id_solicitud) ON DELETE CASCADE,
        FOREIGN KEY (id_cliente) REFERENCES CLIENTE(id_cliente) ON DELETE CASCADE,
        FOREIGN KEY (id_admin) REFERENCES ADMINISTRADOR(id_admin) ON DELETE SET NULL
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chatevento_solicitud ON CHAT_EVENTO (id_solicitud);")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_chatevento_cliente ON CHAT_EVENTO (id_cliente);")

    # 15. MENSAJE_EVENTO
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS MENSAJE_EVENTO (
        id_mensaje_evento INTEGER PRIMARY KEY AUTOINCREMENT,
        id_chat_evento INT NOT NULL,
        rol TEXT NOT NULL,
        mensaje TEXT NOT NULL,
        fecha_envio TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (id_chat_evento) REFERENCES CHAT_EVENTO(id_chat_evento) ON DELETE CASCADE
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_msgevento_chat ON MENSAJE_EVENTO (id_chat_evento);")

    # Unicidad 1:1 en chat general cliente-administrador
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_cliente_unico ON CHAT (id_cliente);")

    # 16. CODIGO_VERIFICACION
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS CODIGO_VERIFICACION (
        id_codigo INTEGER PRIMARY KEY AUTOINCREMENT,
        correo TEXT NOT NULL,
        codigo TEXT NOT NULL,
        tipo TEXT NOT NULL DEFAULT 'REGISTRO',
        intentos INTEGER NOT NULL DEFAULT 0,
        usado BOOLEAN NOT NULL DEFAULT 0,
        expira_en TIMESTAMP NOT NULL,
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_codigo_correo ON CODIGO_VERIFICACION (correo, usado);")


def _inicializar_mysql(conexion, cursor):
    """Inicializa la base de datos utilizando sintaxis de MySQL / MariaDB."""
    print("Configurando esquema para MySQL...")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS CLIENTE (
        id_cliente INT AUTO_INCREMENT PRIMARY KEY,
        nombre VARCHAR(100) NOT NULL,
        correo VARCHAR(150) NOT NULL UNIQUE,
        contrasena VARCHAR(255) NOT NULL,
        fecha_registro DATE DEFAULT (CURRENT_DATE),
        correo_verificado BOOLEAN NOT NULL DEFAULT TRUE
    ) ENGINE=InnoDB;
    """)
    try:
        cursor.execute("ALTER TABLE CLIENTE ADD COLUMN correo_verificado BOOLEAN NOT NULL DEFAULT TRUE;")
    except Exception:
        pass

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ADMINISTRADOR (
        id_admin INT NOT NULL PRIMARY KEY,
        nombre VARCHAR(100) NOT NULL,
        correo VARCHAR(150) NOT NULL UNIQUE,
        contrasena VARCHAR(255) NOT NULL,
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT chk_unico_administrador CHECK (id_admin = 1)
    ) ENGINE=InnoDB;
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS PRODUCTO (
        id_producto INT AUTO_INCREMENT PRIMARY KEY,
        id_admin INT NULL,
        nombre VARCHAR(80) NOT NULL,
        categoria VARCHAR(30) NULL,
        precio DECIMAL(8, 2) NOT NULL,
        descripcion VARCHAR(300) NOT NULL,
        disponible BOOLEAN NOT NULL DEFAULT TRUE,
        en_vitrina BOOLEAN NOT NULL DEFAULT FALSE,
        imagen MEDIUMBLOB NULL,
        tipo_imagen VARCHAR(30) NULL,
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
        INDEX idx_producto_catalogo (disponible, categoria),
        CONSTRAINT fk_producto_admin FOREIGN KEY (id_admin) REFERENCES ADMINISTRADOR(id_admin) ON DELETE SET NULL
    ) ENGINE=InnoDB;
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS RESERVA (
        id_reserva INT AUTO_INCREMENT PRIMARY KEY,
        codigo VARCHAR(20) NOT NULL UNIQUE,
        id_cliente INT NULL,
        fecha_reserva DATETIME NOT NULL,
        fecha_retiro DATETIME NOT NULL,
        estado VARCHAR(30) NOT NULL DEFAULT 'PENDIENTE_PAGO',
        nombre_cliente VARCHAR(100) NOT NULL,
        correo VARCHAR(150) NULL,
        telefono VARCHAR(30) NOT NULL,
        total DECIMAL(10, 2) NOT NULL,
        anticipo_requerido DECIMAL(10, 2) NOT NULL,
        monto_pagado DECIMAL(10, 2) NOT NULL DEFAULT 0,
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_reserva_cliente (id_cliente),
        INDEX idx_reserva_estado_fecha (estado, fecha_retiro),
        CONSTRAINT fk_reserva_cliente FOREIGN KEY (id_cliente) REFERENCES CLIENTE(id_cliente) ON DELETE CASCADE
    ) ENGINE=InnoDB;
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS DETALLE_RESERVA (
        id_detalle INT AUTO_INCREMENT PRIMARY KEY,
        id_reserva INT NOT NULL,
        id_pastel INT NULL,
        nombre_producto VARCHAR(120) NOT NULL,
        precio_unitario DECIMAL(10, 2) NOT NULL,
        cantidad INT NOT NULL,
        CONSTRAINT fk_detalle_reserva FOREIGN KEY (id_reserva) REFERENCES RESERVA(id_reserva) ON DELETE CASCADE,
        CONSTRAINT fk_detalle_producto FOREIGN KEY (id_pastel) REFERENCES PRODUCTO(id_producto) ON DELETE SET NULL
    ) ENGINE=InnoDB;
    """)
    _migrar_detalle_producto_mysql(cursor)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS PAGO (
        id_pago INT AUTO_INCREMENT PRIMARY KEY,
        id_reserva INT NOT NULL,
        metodo_pago VARCHAR(30) NOT NULL,
        monto DECIMAL(10, 2) NOT NULL,
        fecha_pago DATETIME NULL,
        estado VARCHAR(20) NOT NULL DEFAULT 'PENDIENTE',
        referencia VARCHAR(100) NOT NULL UNIQUE,
        referencia_wompi VARCHAR(100) NULL,
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_pago_reserva_estado (id_reserva, estado),
        CONSTRAINT fk_pago_reserva FOREIGN KEY (id_reserva) REFERENCES RESERVA(id_reserva) ON DELETE CASCADE
    ) ENGINE=InnoDB;
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS INVENTARIO (
        id_inventario INT AUTO_INCREMENT PRIMARY KEY,
        id_pastel INT NOT NULL UNIQUE,
        stock INT NOT NULL DEFAULT 0,
        CONSTRAINT fk_inventario_producto FOREIGN KEY (id_pastel) REFERENCES PRODUCTO(id_producto) ON DELETE CASCADE
    ) ENGINE=InnoDB;
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS MOVIMIENTO_INVENTARIO (
        id_movimiento INT AUTO_INCREMENT PRIMARY KEY,
        id_inventario INT NOT NULL,
        id_admin INT NULL,
        cantidad INT NOT NULL,
        fecha_movimiento DATETIME DEFAULT CURRENT_TIMESTAMP,
        tipo_movimiento VARCHAR(40) NOT NULL,
        CONSTRAINT fk_movimiento_inventario FOREIGN KEY (id_inventario) REFERENCES INVENTARIO(id_inventario) ON DELETE CASCADE,
        CONSTRAINT fk_movimiento_admin FOREIGN KEY (id_admin) REFERENCES ADMINISTRADOR(id_admin) ON DELETE SET NULL
    ) ENGINE=InnoDB;
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS CHAT (
        id_chat INT AUTO_INCREMENT PRIMARY KEY,
        id_cliente INT NOT NULL,
        id_admin INT NULL,
        fecha_creacion DATETIME DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_chat_cliente FOREIGN KEY (id_cliente) REFERENCES CLIENTE(id_cliente) ON DELETE CASCADE,
        CONSTRAINT fk_chat_admin FOREIGN KEY (id_admin) REFERENCES ADMINISTRADOR(id_admin) ON DELETE SET NULL
    ) ENGINE=InnoDB;
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS MENSAJE (
        id_mensaje INT AUTO_INCREMENT PRIMARY KEY,
        id_chat INT NOT NULL,
        rol VARCHAR(20) NOT NULL,
        mensaje TEXT NOT NULL,
        fecha_envio DATETIME DEFAULT CURRENT_TIMESTAMP,
        CONSTRAINT fk_mensaje_chat FOREIGN KEY (id_chat) REFERENCES CHAT(id_chat) ON DELETE CASCADE
    ) ENGINE=InnoDB;
    """)

    cursor.execute("""
    CREATE OR REPLACE VIEW PASTEL AS
    SELECT id_producto AS id_pastel, id_admin, nombre,
           categoria AS tipo_venta, precio
    FROM PRODUCTO;
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS DASHBOARD (
        id_snapshot INT AUTO_INCREMENT PRIMARY KEY,
        fecha_snapshot TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        reservas_hoy INT NOT NULL DEFAULT 0,
        reservas_pendientes INT NOT NULL DEFAULT 0,
        reservas_confirmadas INT NOT NULL DEFAULT 0,
        reservas_en_preparacion INT NOT NULL DEFAULT 0,
        reservas_listas INT NOT NULL DEFAULT 0,
        reservas_entregadas INT NOT NULL DEFAULT 0,
        reservas_canceladas INT NOT NULL DEFAULT 0,
        productos_activos INT NOT NULL DEFAULT 0
    ) ENGINE=InnoDB;
    """)

    # Telefono en CLIENTE
    try:
        cursor.execute("ALTER TABLE CLIENTE ADD COLUMN telefono VARCHAR(30) NULL;")
    except Exception:
        pass

    # 13. SOLICITUD_PLANIFICACION
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS SOLICITUD_PLANIFICACION (
        id_solicitud INT AUTO_INCREMENT PRIMARY KEY,
        id_cliente INT NOT NULL,
        tipo_evento VARCHAR(100) NOT NULL,
        num_invitados INT NOT NULL,
        presupuesto_estimado DECIMAL(10, 2) NULL,
        fecha_evento DATE NOT NULL,
        lugar_evento VARCHAR(150) NULL,
        servicios VARCHAR(255) NULL,
        estado VARCHAR(30) NOT NULL DEFAULT 'NUEVA',
        fecha_solicitud DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_solicitud_cliente (id_cliente),
        INDEX idx_solicitud_estado (estado),
        CONSTRAINT fk_solicitud_cliente FOREIGN KEY (id_cliente) REFERENCES CLIENTE(id_cliente) ON DELETE CASCADE
    ) ENGINE=InnoDB;
    """)

    # 14. CHAT_EVENTO (Restricción 1:1 con SOLICITUD_PLANIFICACION mediante UNIQUE en id_solicitud)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS CHAT_EVENTO (
        id_chat_evento INT AUTO_INCREMENT PRIMARY KEY,
        id_solicitud INT NOT NULL UNIQUE,
        id_cliente INT NOT NULL,
        id_admin INT NULL,
        titulo VARCHAR(150) NOT NULL,
        fecha_creacion DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_chatevento_solicitud (id_solicitud),
        INDEX idx_chatevento_cliente (id_cliente),
        CONSTRAINT fk_chatevento_solicitud FOREIGN KEY (id_solicitud) REFERENCES SOLICITUD_PLANIFICACION(id_solicitud) ON DELETE CASCADE,
        CONSTRAINT fk_chatevento_cliente FOREIGN KEY (id_cliente) REFERENCES CLIENTE(id_cliente) ON DELETE CASCADE,
        CONSTRAINT fk_chatevento_admin FOREIGN KEY (id_admin) REFERENCES ADMINISTRADOR(id_admin) ON DELETE SET NULL
    ) ENGINE=InnoDB;
    """)

    # 15. MENSAJE_EVENTO
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS MENSAJE_EVENTO (
        id_mensaje_evento INT AUTO_INCREMENT PRIMARY KEY,
        id_chat_evento INT NOT NULL,
        rol VARCHAR(20) NOT NULL,
        mensaje TEXT NOT NULL,
        fecha_envio DATETIME DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_msgevento_chat (id_chat_evento),
        CONSTRAINT fk_msgevento_chat FOREIGN KEY (id_chat_evento) REFERENCES CHAT_EVENTO(id_chat_evento) ON DELETE CASCADE
    ) ENGINE=InnoDB;
    """)

    try:
        cursor.execute("CREATE UNIQUE INDEX idx_chat_cliente_unico ON CHAT (id_cliente);")
    except Exception:
        pass

    # 16. CODIGO_VERIFICACION
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS CODIGO_VERIFICACION (
        id_codigo INT AUTO_INCREMENT PRIMARY KEY,
        correo VARCHAR(150) NOT NULL,
        codigo VARCHAR(10) NOT NULL,
        tipo VARCHAR(30) NOT NULL DEFAULT 'REGISTRO',
        intentos INT NOT NULL DEFAULT 0,
        usado BOOLEAN NOT NULL DEFAULT FALSE,
        expira_en DATETIME NOT NULL,
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        INDEX idx_codigo_correo (correo, usado)
    ) ENGINE=InnoDB;
    """)


def _sembrar_datos_iniciales(cursor):
    """Inserta el administrador por defecto y datos iniciales de solicitudes si no existen."""
    # 1. Administrador por defecto
    cursor.execute("SELECT COUNT(*) FROM ADMINISTRADOR WHERE id_admin = 1")
    fila_admin = cursor.fetchone()
    conteo_admin = fila_admin[0] if isinstance(fila_admin, (list, tuple)) else fila_admin.get("COUNT(*)", 0)

    if conteo_admin == 0:
        cursor.execute(
            """
            INSERT INTO ADMINISTRADOR (id_admin, nombre, correo, contrasena)
            VALUES (1, %s, %s, %s)
            """,
            ("Administrador Twins", "admin@twinsbakery.com", generate_password_hash("admin1234")),
        )
        print(" -> Administrador inicial verificado: admin@twinsbakery.com / clave: admin1234")

    # 2. Solicitudes de ejemplo para panel administrativo de eventos si está vacía
    cursor.execute("SELECT COUNT(*) FROM SOLICITUD_PLANIFICACION")
    fila_sol = cursor.fetchone()
    conteo_sol = fila_sol[0] if isinstance(fila_sol, (list, tuple)) else fila_sol.get("COUNT(*)", 0)

    if conteo_sol == 0:
        # Clientes de demostración reflejados en el diseño de la imagen
        clientes_demo = [
            ("Laura Gómez", "laura.gomez@gmail.com", "7712-3401"),
            ("Daniel Hernández", "daniel.hernandez@gmail.com", "7845-9012"),
            ("Paola Rivera", "paola.rivera@gmail.com", "7123-4567"),
            ("Miguel Cruz", "miguel.cruz@gmail.com", "7999-8877"),
        ]

        ids_clientes = {}
        for nom, cor, tel in clientes_demo:
            cursor.execute("SELECT id_cliente FROM CLIENTE WHERE correo = %s", (cor,))
            fila_c = cursor.fetchone()
            if fila_c:
                c_id = fila_c[0] if isinstance(fila_c, (list, tuple)) else fila_c.get("id_cliente")
            else:
                cursor.execute(
                    """
                    INSERT INTO CLIENTE (nombre, correo, contrasena, telefono)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (nom, cor, generate_password_hash("cliente123"), tel),
                )
                c_id = cursor.lastrowid
            ids_clientes[nom] = c_id

        # Insertar solicitudes de la imagen
        solicitudes_demo = [
            ("Laura Gómez", "Cumpleaños", 50, 500.00, "2026-10-05", "San Salvador", "Pastel, Cupcakes", "NUEVA"),
            ("Daniel Hernández", "Graduación", 80, 700.00, "2026-10-10", "Santa Tecla", "Pastel, Decoración", "NUEVA"),
            ("Paola Rivera", "Baby Shower", 35, 350.00, "2026-10-15", "Antiguo Cuscatlán", "Pastel, Mesa de postres", "NUEVA"),
            ("Miguel Cruz", "Empresarial", 100, 1000.00, "2026-10-20", "San Salvador", "Bebidas, Pastel, Galletas", "NUEVA"),
        ]

        for nom, tipo, inv, pres, fec, lug, serv, est in solicitudes_demo:
            c_id = ids_clientes.get(nom)
            if c_id:
                cursor.execute(
                    """
                    INSERT INTO SOLICITUD_PLANIFICACION 
                    (id_cliente, tipo_evento, num_invitados, presupuesto_estimado, fecha_evento, lugar_evento, servicios, estado)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (c_id, tipo, inv, pres, fec, lug, serv, est),
                )
        print(" -> Solicitudes iniciales de eventos agregadas según diseño.")



def inicializar_base_datos():
    conexion = None
    cursor = None

    try:
        conexion = obtener_conexion()
        cursor = conexion.cursor()

        es_sqlite = isinstance(conexion, SQLiteConnectionWrapper) or "sqlite" in type(conexion).__name__.lower()

        if es_sqlite:
            _inicializar_sqlite(conexion, cursor)
        else:
            _inicializar_mysql(conexion, cursor)

        # Sembrar datos por defecto (admin y productos)
        _sembrar_datos_iniciales(cursor)

        conexion.commit()

        motor = "SQLite local (twins_bakery.db)" if es_sqlite else "MySQL / Aiven"
        print(f"\n=======================================================")
        print(f"  ¡Base de datos inicializada correctamente en {motor}!")
        print(f"=======================================================")
        print(f"  Tablas creadas y verificadas:")
        print(f"    - CLIENTE, ADMINISTRADOR, PRODUCTO, RESERVA")
        print(f"    - DETALLE_RESERVA, PAGO, INVENTARIO, MOVIMIENTO_INVENTARIO")
        print(f"    - CHAT, MENSAJE, VISTA PASTEL, DASHBOARD")
        print(f"")
        print(f"  Acceso Administrador por defecto:")
        print(f"    - URL:   /admin/login")
        print(f"    - Email: admin@twinsbakery.com")
        print(f"    - Clave: admin1234")
        print(f"=======================================================\n")

    except Exception as e:
        if conexion:
            conexion.rollback()
        print(f"\nError al inicializar la base de datos: {e}")
        raise

    finally:
        if cursor:
            cursor.close()
        if conexion and conexion.is_connected():
            conexion.close()


if __name__ == "__main__":
    inicializar_base_datos()