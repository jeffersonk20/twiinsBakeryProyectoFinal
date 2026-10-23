"""
Módulo de Configuración Segura - Asistente IA TWINS Bakery
Gestiona variables de entorno, llaves criptográficas, credenciales de BD de solo lectura
y parámetros para la API de Gemini (Google AI Studio).
"""

import os
import base64
import hashlib
from dotenv import load_dotenv

# Cargar variables de entorno desde el archivo .env
load_dotenv()

# ==============================================================================
# 1. CREDENCIALES DE GOOGLE GEMINI (GOOGLE AI STUDIO)
# ==============================================================================
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash").strip()
GEMINI_API_VERSION = os.getenv("GEMINI_API_VERSION", "v1beta").strip()
GEMINI_BASE_URL = f"https://generativelanguage.googleapis.com/{GEMINI_API_VERSION}/models/{GEMINI_MODEL}:generateContent"

# Timeout en segundos para peticiones a la API externa de Gemini
GEMINI_TIMEOUT_SECONDS = int(os.getenv("GEMINI_TIMEOUT_SECONDS", "15"))

# ==============================================================================
# 2. CIFRADO DE DATOS PERSONALES (PII) Y SEGURIDAD JWT
# ==============================================================================
# Clave secreta base de Flask
SECRET_KEY = os.getenv("SECRET_KEY", "twins_bakery_fallback_secret_key_2026")

# Clave simétrica para cifrado de PII (debe ser base64 URL-safe de 32 bytes para Fernet)
def _obtener_llave_cifrado() -> bytes:
    custom_key = os.getenv("IA_ENCRYPTION_KEY", "").strip()
    if custom_key:
        try:
            # Validar que sea decodificable
            decoded = base64.urlsafe_b64decode(custom_key)
            if len(decoded) == 32:
                return custom_key.encode("utf-8")
        except Exception:
            pass
    # Derivación determinista basada en SECRET_KEY con PBKDF2
    salt = b"twins_bakery_pii_salt_2026"
    kdf = hashlib.pbkdf2_hmac("sha256", SECRET_KEY.encode("utf-8"), salt, 100_000, dklen=32)
    return base64.urlsafe_b64encode(kdf)

IA_ENCRYPTION_KEY = _obtener_llave_cifrado()

# Clave para firmar JWT de administrador
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", SECRET_KEY)
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "8"))

# ==============================================================================
# 3. BASE DE DATOS - CREDENCIALES DE SOLO LECTURA (DEFENSA EN PROFUNDIDAD)
# ==============================================================================
# La IA NUNCA debe conectarse con credenciales administrativas ni de escritura.
DB_TYPE = os.getenv("DB_TYPE", "auto").strip().lower()
DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "twins_bakery.db"))

# Credenciales de solo lectura para MySQL / MariaDB / Cloud DB
DB_RO_USER = os.getenv("DB_RO_USER", "").strip()
DB_RO_PASSWORD = os.getenv("DB_RO_PASSWORD", "").strip()
DB_RO_HOST = os.getenv("DB_RO_HOST", os.getenv("DB_HOST", "")).strip()
DB_RO_PORT = int(os.getenv("DB_RO_PORT", os.getenv("DB_PORT", "3306")))
DB_RO_NAME = os.getenv("DB_RO_NAME", os.getenv("DB_NAME", "defaultdb")).strip()
DB_TIMEOUT = int(os.getenv("DB_TIMEOUT", "4"))

# ==============================================================================
# 4. RESTRICCIONES DE ENTRADA Y MODERACIÓN
# ==============================================================================
MAX_USER_INPUT_LENGTH = 1000  # Caracteres máximos por mensaje de usuario
MAX_CONVERSATION_HISTORY = 10  # Turnos máximos de conversación en memoria
PRIMARY_BRAND_COLOR = "#B1F2D2"  # Color institucional requerido para la UI de IA
