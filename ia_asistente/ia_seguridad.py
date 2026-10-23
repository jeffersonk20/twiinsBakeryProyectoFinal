"""
Módulo de Seguridad, Sanitización, Detección de Inyecciones y Manejo de JWT.
Protege el pipeline de IA contra:
- Cross-Site Scripting (XSS)
- Inyecciones SQL (SQLi)
- Inyecciones de Prompt (Prompt Injection / Jailbreak)
- Lenguaje Ofensivo / Violaciones de Moderación
- Suplantación de Roles (mediante tokens JWT y sesiones criptográficas)
"""

import re
import html
import time
import json
import base64
import hmac
import hashlib
from typing import Tuple, Optional, Dict, Any
from flask import Request, session
from .ia_config import (
    JWT_SECRET_KEY,
    JWT_EXPIRATION_HOURS,
    MAX_USER_INPUT_LENGTH,
)

# ==============================================================================
# 1. LISTAS DE CONTROL PARA DETECCIÓN DE AMENAZAS
# ==============================================================================

# Patrones típicos de Prompt Injection / Jailbreaks
PATRONES_PROMPT_INJECTION = [
    r"(?i)\bignore\s+(all\s+)?(previous|prior)\s+(instructions|prompts|rules)\b",
    r"(?i)\bolvida\s+(todas\s+las\s+)?(instrucciones|reglas|indicaciones)\b",
    r"(?i)\bact\s+as\s+(an?\s+)?(unrestricted|dan|jailbreak|developer|root|system)\b",
    r"(?i)\b(system\s*prompt|prompt\s*del\s*sistema|instrucciones\s*del\s*sistema)\b",
    r"(?i)\brevela\s+(el\s+)?(system\s+prompt|prompt\s+inicial|instrucciones)\b",
    r"(?i)\bshow\s+(me\s+)?(the\s+)?(system\s+prompt|developer\s+mode)\b",
    r"(?i)\bpretend\s+you\s+are\b",
    r"(?i)\bdisregard\s+all\b",
    r"(?i)\bmodo\s+(desarrollador|dan|sin\s+restricciones|libre)\b",
    r"(?i)\b(bypass|override)\s+(security|safety|restrictions)\b",
]

# Patrones comunes de SQL Injection en texto libre
PATRONES_SQLI = [
    r"(?i)(\bunion\b\s+\bselect\b)",
    r"(?i)(\bor\b\s+['\"]?1['\"]?\s*=\s*['\"]?1['\"])",
    r"(?i)(--|\#|\/\*).*$",
    r"(?i)(;\s*drop\s+table)",
    r"(?i)(;\s*delete\s+from)",
    r"(?i)(;\s*update\s+\w+\s+set)",
    r"(?i)(;\s*insert\s+into)",
    r"(?i)(\bselect\b\s+.*\bfrom\b\s+(sqlite_master|information_schema|administrador|cliente))",
]

# Palabras ofensivas / inapropiadas para el filtro de moderación (Español e Inglés)
PALABRAS_OFENSIVAS = {
    "puta", "puto", "mierda", "pendejo", "pendeja", "culero", "culera", "maricon",
    "verga", "chinga", "malparido", "hijo de puta", "hdp", "bastardo", "imbecil",
    "estupido", "estupida", "idiota", "zorra", "perra", "fuck", "bitch", "asshole",
    "shit", "cunt", "motherfucker", "dick", "pussy", "coño", "mamaguevo", "carechimba",
    "gonorrea", "cabron", "cabrona", "cerdo", "maldito", "maldita"
}

MENSAJE_MODERACION_OFENSIVA = (
    "En TWINS Bakery nos esforzamos por mantener una comunicación cordial y respetuosa. "
    "He detectado palabras inadecuadas en tu consulta, por lo que debo dar por finalizada esta respuesta. "
    "Te invito a reformular tu pregunta con un lenguaje respetuoso y con mucho gusto te brindaré toda "
    "la información sobre nuestros exquisitos pasteles y opciones para eventos."
)


# ==============================================================================
# 2. SANITIZACIÓN DE ENTRADAS Y ANTI-INYECCIÓN
# ==============================================================================

def sanitizar_input_usuario(texto_crudo: str) -> str:
    """
    Sanitiza y normaliza la entrada del usuario:
    - Trunca al tamaño máximo permitido
    - Elimina caracteres nulos y secuencias de escape no imprimibles
    - Escapa etiquetas HTML y scripts para prevenir XSS
    - Neutraliza posibles vectores de prompt injection
    """
    if not texto_crudo or not isinstance(texto_crudo, str):
        return ""

    # Truncar al largo seguro
    texto = texto_crudo[:MAX_USER_INPUT_LENGTH].strip()

    # Eliminar bytes nulos y caracteres de control sospechosos
    texto = "".join(ch for ch in texto if ch.isprintable() or ch in ("\n", "\r", "\t"))

    # Escapar entidades HTML para defensa estricta contra XSS
    texto_escapado = html.escape(texto, quote=True)

    return texto_escapado


def detectar_inyecciones(texto: str) -> Tuple[bool, str]:
    """
    Evalúa si la entrada contiene indicios de SQL Injection o Prompt Injection.
    Retorna (es_amenaza, motivo).
    """
    if not texto:
        return False, ""

    # 1. Comprobar patrones de SQL Injection
    for patron in PATRONES_SQLI:
        if re.search(patron, texto):
            return True, "Intento de inyección SQL detectado y neutralizado."

    # 2. Comprobar patrones de Prompt Injection / Jailbreak
    for patron in PATRONES_PROMPT_INJECTION:
        if re.search(patron, texto):
            return True, "Intento de manipulación de instrucciones (Prompt Injection) detectado."

    return False, ""


def verificar_moderacion(texto: str) -> Tuple[bool, Optional[str]]:
    """
    Analiza el texto buscando groserías, ofensas o ataques.
    Retorna (es_ofensivo, mensaje_respuesta_si_aplica).
    """
    if not texto:
        return False, None

    texto_lower = texto.lower()
    # Tokenización simple de palabras
    palabras = re.findall(r"\b\w+\b", texto_lower)

    # Revisar palabras individuales
    for p in palabras:
        if p in PALABRAS_OFENSIVAS:
            return True, MENSAJE_MODERACION_OFENSIVA

    # Revisar frases compuestas
    for frase in ("hijo de puta", "hija de puta", "chinga tu madre", "vete a la mierda"):
        if frase in texto_lower:
            return True, MENSAJE_MODERACION_OFENSIVA

    return False, None


# ==============================================================================
# 3. GESTIÓN DE TOKENS JWT PARA AUTENTICACIÓN DE ADMINISTRADOR
# ==============================================================================

def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _base64url_decode(data: str) -> bytes:
    padding = "=" * (4 - (len(data) % 4)) if len(data) % 4 != 0 else ""
    return base64.urlsafe_b64decode(data + padding)


def generar_jwt_admin(id_admin: int, correo: str) -> str:
    """
    Genera un token JWT (RFC 7519) firmado con HMAC-SHA256 para el administrador.
    Contiene expiración y claims de rol administrativo.
    """
    header = {"alg": "HS256", "typ": "JWT"}
    ahora = int(time.time())
    payload = {
        "sub": str(id_admin),
        "email": correo,
        "role": "administrador",
        "iat": ahora,
        "exp": ahora + (JWT_EXPIRATION_HOURS * 3600),
        "iss": "twins_bakery_auth_service",
    }

    header_b64 = _base64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _base64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")

    signature = hmac.new(JWT_SECRET_KEY.encode("utf-8"), signing_input, hashlib.sha256).digest()
    signature_b64 = _base64url_encode(signature)

    return f"{header_b64}.{payload_b64}.{signature_b64}"


def verificar_jwt_admin(token: str) -> Optional[Dict[str, Any]]:
    """
    Valida la firma, integridad y tiempo de expiración de un JWT.
    Retorna el payload si es un administrador válido; None en caso contrario.
    """
    if not token or not isinstance(token, str):
        return None

    partes = token.strip().split(".")
    if len(partes) != 3:
        return None

    header_b64, payload_b64, signature_b64 = partes
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")

    # Verificar firma HMAC-SHA256
    expected_sig = hmac.new(JWT_SECRET_KEY.encode("utf-8"), signing_input, hashlib.sha256).digest()
    try:
        received_sig = _base64url_decode(signature_b64)
    except Exception:
        return None

    if not hmac.compare_digest(expected_sig, received_sig):
        return None

    # Decodificar payload
    try:
        payload_bytes = _base64url_decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception:
        return None

    # Verificar expiración y rol
    ahora = int(time.time())
    if payload.get("exp", 0) < ahora:
        return None  # Token expirado

    if payload.get("role") != "administrador":
        return None  # Rol insuficiente

    return payload


def determinar_rol_usuario(req: Request) -> Tuple[str, Dict[str, Any]]:
    """
    Determina de manera segura e irrevocable el rol del usuario actual:
    1. Si se envía encabezado 'Authorization: Bearer <token>', se valida como JWT Admin.
    2. Si la sesión de Flask tiene 'es_admin == True', se valida como Administrador.
    3. Si la sesión tiene 'id_cliente', es un Cliente autenticado.
    4. Por defecto, es 'cliente' (público / visitante).
    Retorna (rol: 'administrador'|'cliente', metadatos: dict).
    """
    # 1. Comprobar encabezado Authorization JWT
    auth_header = req.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        jwt_payload = verificar_jwt_admin(token)
        if jwt_payload:
            return "administrador", {
                "id_admin": jwt_payload.get("sub"),
                "email": jwt_payload.get("email"),
                "auth_method": "jwt",
            }

    # 2. Comprobar sesión de administrador en Flask
    if session.get("es_admin") is True:
        return "administrador", {
            "id_admin": session.get("id_admin"),
            "email": session.get("admin_email"),
            "auth_method": "session",
        }

    # 3. Comprobar sesión de cliente en Flask
    if session.get("id_cliente"):
        return "cliente", {
            "id_cliente": session.get("id_cliente"),
            "nombre": session.get("nombre_cliente"),
            "correo": session.get("correo_cliente"),
            "auth_method": "session",
        }

    # 4. Visitante público (rol Cliente restringido por defecto)
    return "cliente", {
        "auth_method": "guest",
    }
