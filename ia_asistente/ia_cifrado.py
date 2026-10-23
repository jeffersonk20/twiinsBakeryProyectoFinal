"""
Módulo de Cifrado y Protección de PII (Personally Identifiable Information)
Implementa cifrado simétrico robusto autenticado (AES-128-CBC + HMAC-SHA256 vía Fernet)
para datos personales de clientes en base de datos y utilidades de enmascaramiento.
"""

import logging
from typing import Optional, Dict, Any
from cryptography.fernet import Fernet, InvalidToken
from .ia_config import IA_ENCRYPTION_KEY

logger = logging.getLogger("twins_ia_cifrado")

# Instancia global de cifrador Fernet
try:
    _cipher = Fernet(IA_ENCRYPTION_KEY)
except Exception as e:
    logger.error("Error al inicializar el cifrador Fernet: %s", e)
    _cipher = None


def cifrar_texto(texto: Optional[str]) -> str:
    """
    Cifra un texto plano usando Fernet (AES-128 autenticado).
    Si el texto ya está vacío o cifrado, lo retorna sin alteraciones.
    """
    if not texto or not _cipher:
        return texto or ""

    texto_str = str(texto).strip()
    if es_cifrado(texto_str):
        return texto_str

    try:
        token_bytes = _cipher.encrypt(texto_str.encode("utf-8"))
        return token_bytes.decode("utf-8")
    except Exception as exc:
        logger.error("Error al cifrar texto: %s", exc)
        return texto_str


def descifrar_texto(token_o_texto: Optional[str]) -> str:
    """
    Descifra un token cifrado. Si no está cifrado (texto plano legado),
    lo retorna directamente sin generar error.
    """
    if not token_o_texto or not _cipher:
        return token_o_texto or ""

    texto_str = str(token_o_texto).strip()
    if not es_cifrado(texto_str):
        return texto_str

    try:
        bytes_descifrados = _cipher.decrypt(texto_str.encode("utf-8"))
        return bytes_descifrados.decode("utf-8")
    except InvalidToken:
        # No era un token válido de Fernet o la llave difiere; devolver como estaba
        return texto_str
    except Exception as exc:
        logger.warning("Fallo en descifrado de dato: %s", exc)
        return texto_str


def es_cifrado(texto: str) -> bool:
    """
    Detecta de forma heurística si una cadena corresponde a un token Fernet.
    Los tokens Fernet inician con 'gAAAAA' y tienen longitud mínima de 100 caracteres base64.
    """
    if not texto or not isinstance(texto, str):
        return False
    return texto.startswith("gAAAAA") and len(texto) >= 100


def enmascarar_nombre(nombre: Optional[str]) -> str:
    """Enmascara nombres para reportes analíticos de IA (ej: 'Daniel Castillo' -> 'Daniel C.')."""
    if not nombre:
        return "Cliente"
    texto = descifrar_texto(nombre).strip()
    partes = texto.split()
    if len(partes) == 1:
        return partes[0][:2] + "***" if len(partes[0]) > 2 else partes[0]
    return f"{partes[0]} {partes[1][0]}." if len(partes) >= 2 else partes[0]


def enmascarar_correo(correo: Optional[str]) -> str:
    """Enmascara correo electrónico (ej: 'usuario@gmail.com' -> 'u***o@gmail.com')."""
    if not correo:
        return "no_disponible@anon.com"
    texto = descifrar_texto(correo).strip()
    if "@" not in texto:
        return "***"
    usuario, dominio = texto.split("@", 1)
    if len(usuario) <= 2:
        usuario_enmascarado = usuario[0] + "***"
    else:
        usuario_enmascarado = usuario[0] + "***" + usuario[-1]
    return f"{usuario_enmascarado}@{dominio}"


def enmascarar_telefono(telefono: Optional[str]) -> str:
    """Enmascara número telefónico preservando solo los últimos 4 dígitos."""
    if not telefono:
        return "****-****"
    texto = descifrar_texto(telefono).strip()
    numeros = "".join(filter(str.isdigit, texto))
    if len(numeros) >= 4:
        return f"****-{numeros[-4:]}"
    return "****"


def procesar_registro_cliente_cifrado(registro: Dict[str, Any]) -> Dict[str, Any]:
    """Crea una copia de un registro de cliente descifrando sus campos para uso interno autorizado."""
    copia = dict(registro)
    for campo in ("nombre", "nombre_cliente", "correo", "telefono"):
        if campo in copia and copia[campo]:
            copia[campo] = descifrar_texto(str(copia[campo]))
    return copia
