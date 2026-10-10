
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

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ADMINISTRADOR (
                id_admin INT NOT NULL PRIMARY KEY,
                nombre VARCHAR(100) NOT NULL,
                correo VARCHAR(150) NOT NULL UNIQUE,
                contrasena VARCHAR(255) NOT NULL,
                fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT chk_unico_administrador CHECK (id_admin = 1)
            ) ENGINE=InnoDB
            """
        )

        cursor.execute("SHOW COLUMNS FROM ADMINISTRADOR")
        columnas_admin = {
            columna["Field"]
            for columna in cursor.fetchall()
        }
        if "id_admin" not in columnas_admin:
            if "id_administrador" not in columnas_admin:
                raise RuntimeError(
                    "La tabla ADMINISTRADOR no contiene una columna de identificador compatible."
                )
            cursor.execute(
                "ALTER TABLE ADMINISTRADOR "
                "CHANGE COLUMN id_administrador id_admin INT NOT NULL"
            )

        cursor.execute("SHOW COLUMNS FROM PRODUCTO")
        columnas_producto = {
            columna["Field"] for columna in cursor.fetchall()
        }
        if "id_admin" not in columnas_producto:
            cursor.execute(
                "ALTER TABLE PRODUCTO ADD COLUMN id_admin INT NULL"
            )

        cursor.execute("SHOW CREATE TABLE PRODUCTO")
        definicion_producto = " ".join(str(valor) for valor in cursor.fetchone().values())
        if "fk_producto_admin" not in definicion_producto:
            cursor.execute(
                """
                ALTER TABLE PRODUCTO
                ADD CONSTRAINT fk_producto_admin
                FOREIGN KEY (id_admin) REFERENCES ADMINISTRADOR(id_admin)
                ON DELETE SET NULL
                """
            )

        cursor.execute("SHOW FULL TABLES LIKE 'RESERVA'")
        reserva_existente = cursor.fetchone()
        if reserva_existente:
            cursor.execute("SHOW COLUMNS FROM RESERVA")
            columnas_reserva = {
                columna["Field"]
                for columna in cursor.fetchall()
            }
            columnas_reserva_actual = {
                "codigo",
                "id_cliente",
                "fecha_reserva",
                "fecha_retiro",
                "estado",
                "nombre_cliente",
                "telefono",
                "total",
                "anticipo_requerido",
                "monto_pagado",
            }
            if not columnas_reserva_actual.issubset(columnas_reserva):
                cursor.execute("SHOW FULL TABLES LIKE 'RESERVA_LEGACY'")
                if cursor.fetchone():
                    raise RuntimeError(
                        "RESERVA tiene una estructura anterior y RESERVA_LEGACY ya existe; "
                        "se conservaron ambas tablas sin modificarlas."
                    )
                cursor.execute("RENAME TABLE RESERVA TO RESERVA_LEGACY")

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS RESERVA (
                id_reserva INT AUTO_INCREMENT PRIMARY KEY,
                codigo VARCHAR(20) NOT NULL UNIQUE,
                id_cliente INT NULL,
                fecha_reserva DATETIME NOT NULL,
                fecha_retiro DATETIME NOT NULL,
                estado VARCHAR(30) NOT NULL DEFAULT 'PENDIENTE_PAGO',
                nombre_cliente VARCHAR(100) NOT NULL,
                telefono VARCHAR(30) NOT NULL,
                total DECIMAL(10, 2) NOT NULL,
                anticipo_requerido DECIMAL(10, 2) NOT NULL,
                monto_pagado DECIMAL(10, 2) NOT NULL DEFAULT 0,
                fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_reserva_cliente (id_cliente),
                INDEX idx_reserva_estado_fecha (estado, fecha_retiro),
                CONSTRAINT fk_reserva_cliente
                    FOREIGN KEY (id_cliente) REFERENCES CLIENTE(id_cliente)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB
            """
        )

        cursor.execute("SHOW FULL TABLES LIKE 'RESERVA_LEGACY'")
        reserva_legacy = cursor.fetchone()
        if reserva_legacy:
            cursor.execute("SHOW COLUMNS FROM RESERVA_LEGACY")
            columnas_legacy = {
                columna["Field"]
                for columna in cursor.fetchall()
            }
            columnas_legacy_necesarias = {
                "id_reserva",
                "codigo",
                "id_producto",
                "cantidad",
                "precio_unitario",
                "fecha_reserva",
                "hora_recogida",
                "nombre_cliente",
                "telefono",
                "total",
                "anticipo_requerido",
                "anticipo_pagado",
                "estado",
                "metodo_pago",
            }
            if not columnas_legacy_necesarias.issubset(columnas_legacy):
                raise RuntimeError(
                    "RESERVA_LEGACY no tiene la estructura esperada; "
                    "sus datos se conservaron para revisión manual."
                )

            cursor.execute(
                """
                SELECT DISTINCT estado
                FROM RESERVA_LEGACY
                WHERE UPPER(estado) NOT IN (
                    'PENDIENTE DE ANTICIPO', 'PENDIENTE_PAGO',
                    'CONFIRMADA', 'EN PREPARACION', 'EN_PREPARACION',
                    'LISTA', 'LISTA PARA RETIRAR', 'ENTREGADA',
                    'CANCELADA'
                )
                """
            )
            estados_legacy_desconocidos = cursor.fetchall()
            if estados_legacy_desconocidos:
                raise RuntimeError(
                    "RESERVA_LEGACY contiene estados que requieren mapeo manual."
                )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS DETALLE_RESERVA (
                id_detalle INT AUTO_INCREMENT PRIMARY KEY,
                id_reserva INT NOT NULL,
                id_pastel INT NOT NULL,
                nombre_producto VARCHAR(120) NOT NULL,
                precio_unitario DECIMAL(10, 2) NOT NULL,
                cantidad INT NOT NULL,
                CONSTRAINT fk_detalle_reserva
                    FOREIGN KEY (id_reserva) REFERENCES RESERVA(id_reserva)
                    ON DELETE CASCADE,
                CONSTRAINT fk_detalle_producto
                    FOREIGN KEY (id_pastel) REFERENCES PRODUCTO(id_producto)
                    ON DELETE RESTRICT
            ) ENGINE=InnoDB
            """
        )

        cursor.execute(
            """
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
                CONSTRAINT fk_pago_reserva
                    FOREIGN KEY (id_reserva) REFERENCES RESERVA(id_reserva)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB
            """
        )

        if reserva_legacy:
            cursor.execute(
                """
                INSERT INTO RESERVA
                    (codigo, id_cliente, fecha_reserva, fecha_retiro, estado,
                     nombre_cliente, telefono, total, anticipo_requerido, monto_pagado)
                SELECT
                    legado.codigo,
                    NULL,
                    COALESCE(legado.fecha_creacion, NOW()),
                    TIMESTAMP(legado.fecha_reserva, legado.hora_recogida),
                    CASE UPPER(legado.estado)
                        WHEN 'PENDIENTE DE ANTICIPO' THEN 'PENDIENTE_PAGO'
                        WHEN 'PENDIENTE_PAGO' THEN 'PENDIENTE_PAGO'
                        WHEN 'CONFIRMADA' THEN 'CONFIRMADA'
                        WHEN 'EN PREPARACION' THEN 'EN_PREPARACION'
                        WHEN 'EN_PREPARACION' THEN 'EN_PREPARACION'
                        WHEN 'LISTA' THEN 'LISTA'
                        WHEN 'LISTA PARA RETIRAR' THEN 'LISTA'
                        WHEN 'ENTREGADA' THEN 'ENTREGADA'
                        WHEN 'CANCELADA' THEN 'CANCELADA'
                    END,
                    legado.nombre_cliente,
                    legado.telefono,
                    legado.total,
                    legado.anticipo_requerido,
                    CASE WHEN legado.anticipo_pagado THEN legado.anticipo_requerido ELSE 0 END
                FROM RESERVA_LEGACY AS legado
                LEFT JOIN RESERVA AS actual ON actual.codigo = legado.codigo
                WHERE actual.id_reserva IS NULL
                """
            )
            cursor.execute(
                """
                INSERT INTO DETALLE_RESERVA
                    (id_reserva, id_pastel, nombre_producto, precio_unitario, cantidad)
                SELECT
                    nueva.id_reserva,
                    legado.id_producto,
                    producto.nombre,
                    legado.precio_unitario,
                    legado.cantidad
                FROM RESERVA_LEGACY AS legado
                JOIN RESERVA AS nueva ON nueva.codigo = legado.codigo
                JOIN PRODUCTO AS producto ON producto.id_producto = legado.id_producto
                LEFT JOIN DETALLE_RESERVA AS detalle
                    ON detalle.id_reserva = nueva.id_reserva
                WHERE detalle.id_detalle IS NULL
                """
            )
            cursor.execute(
                """
                INSERT INTO PAGO
                    (id_reserva, metodo_pago, monto, fecha_pago, estado, referencia)
                SELECT
                    nueva.id_reserva,
                    legado.metodo_pago,
                    legado.anticipo_requerido,
                    CASE
                        WHEN legado.anticipo_pagado
                        THEN COALESCE(legado.fecha_creacion, NOW())
                        ELSE NULL
                    END,
                    CASE WHEN legado.anticipo_pagado THEN 'PAGADO' ELSE 'PENDIENTE' END,
                    CONCAT('LEGACY-', legado.id_reserva)
                FROM RESERVA_LEGACY AS legado
                JOIN RESERVA AS nueva ON nueva.codigo = legado.codigo
                LEFT JOIN PAGO AS pago ON pago.id_reserva = nueva.id_reserva
                WHERE pago.id_pago IS NULL
                """
            )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS INVENTARIO (
                id_inventario INT AUTO_INCREMENT PRIMARY KEY,
                id_pastel INT NOT NULL UNIQUE,
                stock INT NOT NULL DEFAULT 0,
                CONSTRAINT fk_inventario_producto
                    FOREIGN KEY (id_pastel) REFERENCES PRODUCTO(id_producto)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS MOVIMIENTO_INVENTARIO (
                id_movimiento INT AUTO_INCREMENT PRIMARY KEY,
                id_inventario INT NOT NULL,
                id_admin INT NULL,
                cantidad INT NOT NULL,
                fecha_movimiento DATETIME DEFAULT CURRENT_TIMESTAMP,
                tipo_movimiento VARCHAR(40) NOT NULL,
                CONSTRAINT fk_movimiento_inventario
                    FOREIGN KEY (id_inventario) REFERENCES INVENTARIO(id_inventario)
                    ON DELETE CASCADE,
                CONSTRAINT fk_movimiento_admin
                    FOREIGN KEY (id_admin) REFERENCES ADMINISTRADOR(id_admin)
                    ON DELETE SET NULL
            ) ENGINE=InnoDB
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS CHAT (
                id_chat INT AUTO_INCREMENT PRIMARY KEY,
                id_cliente INT NOT NULL,
                id_admin INT NULL,
                fecha_creacion DATETIME DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_chat_cliente
                    FOREIGN KEY (id_cliente) REFERENCES CLIENTE(id_cliente)
                    ON DELETE CASCADE,
                CONSTRAINT fk_chat_admin
                    FOREIGN KEY (id_admin) REFERENCES ADMINISTRADOR(id_admin)
                    ON DELETE SET NULL
            ) ENGINE=InnoDB
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS MENSAJE (
                id_mensaje INT AUTO_INCREMENT PRIMARY KEY,
                id_chat INT NOT NULL,
                rol VARCHAR(20) NOT NULL,
                mensaje TEXT NOT NULL,
                fecha_envio DATETIME DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_mensaje_chat
                    FOREIGN KEY (id_chat) REFERENCES CHAT(id_chat)
                    ON DELETE CASCADE
            ) ENGINE=InnoDB
            """
        )

        cursor.execute("SHOW FULL TABLES LIKE 'PASTEL'")
        pastel_existente = cursor.fetchone()
        if not pastel_existente or "VIEW" in str(tuple(pastel_existente.values())).upper():
            # Keep the diagram's PASTEL name while reusing the existing PRODUCTO catalog.
            cursor.execute(
                """
                CREATE OR REPLACE VIEW PASTEL AS
                SELECT id_producto AS id_pastel, id_admin, nombre,
                       categoria AS tipo_venta, precio
                FROM PRODUCTO
                """
            )

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