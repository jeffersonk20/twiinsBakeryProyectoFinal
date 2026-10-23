"""
Módulo de Rutas y Controlador Flask (Blueprint) para el Asistente de IA.
Interpreta las solicitudes asíncronas (fetch/AJAX), aplica la cadena de seguridad,
orquesta el RAG aislado según el rol y gestiona la sesión / tokens JWT.
"""

import datetime
import logging
from flask import Blueprint, request, jsonify, session
from .ia_config import (
    PRIMARY_BRAND_COLOR,
    GEMINI_API_KEY,
    GEMINI_MODEL,
)
from .ia_seguridad import (
    sanitizar_input_usuario,
    detectar_inyecciones,
    verificar_moderacion,
    determinar_rol_usuario,
    generar_jwt_admin,
)
from .ia_rag import construir_prompt_rag
from .ia_gemini import enviar_consulta_gemini

logger = logging.getLogger("twins_ia_rutas")

# Definición del Blueprint para la API del asistente de IA
ia_bp = Blueprint("ia_asistente", __name__, url_prefix="/api/ia")


@ia_bp.after_request
def aplicar_cabeceras_seguridad(response):
    """Fuerza directivas de seguridad HTTP en todas las respuestas del módulo de IA."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@ia_bp.route("/info", methods=["GET"])
def info_asistente():
    """
    Retorna metadatos de configuración para la interfaz del chat:
    - Rol detectado para el usuario actual ('cliente' o 'administrador').
    - Estado del proxy de Gemini (activo con API Key o modo de prueba seguro).
    - Color institucional (#B1F2D2).
    - Preguntas rápidas recomendadas según el rol.
    """
    rol, meta = determinar_rol_usuario(request)

    if rol == "administrador":
        prompts_rapidos = [
            "📊 Resumen de ventas y anticipos",
            "📦 ¿Qué productos tienen stock bajo?",
            "📋 Estado de las reservas activas",
            "📈 Rendimiento general del negocio",
        ]
        etiqueta_rol = "Administrador (Twins Analytics)"
    else:
        prompts_rapidos = [
            "🍰 ¿Qué pasteles tienen disponibles?",
            "💰 Precios y opciones de porciones",
            "📅 ¿Cómo puedo realizar una reserva?",
            "💍 ¿Qué paquetes ofrecen para bodas?",
            "👶 Opciones para Baby Shower",
        ]
        etiqueta_rol = "Cliente (Asistente Virtual Twins)"

    return jsonify({
        "success": True,
        "rol": rol,
        "etiqueta_rol": etiqueta_rol,
        "color_primario": PRIMARY_BRAND_COLOR,
        "modo_gemini": "api_live" if GEMINI_API_KEY else "local_fallback",
        "modelo": GEMINI_MODEL,
        "prompts_rapidos": prompts_rapidos,
        "autenticado": meta.get("auth_method") != "guest",
    })


@ia_bp.route("/token-admin", methods=["POST"])
def generar_token_admin_endpoint():
    """
    Genera un token JWT para administradores autenticados vía sesión de Flask.
    Permite que la interfaz frontend del panel admin almacene el JWT para peticiones seguras.
    """
    if not session.get("es_admin"):
        return jsonify({
            "success": False,
            "error": "Acceso denegado: solo disponible para administradores autenticados."
        }), 403

    id_admin = session.get("id_admin", 1)
    correo_admin = session.get("admin_email", "admin@twinsbakery.com")
    token_jwt = generar_jwt_admin(id_admin, correo_admin)

    return jsonify({
        "success": True,
        "token": token_jwt,
        "rol": "administrador",
        "expira_en_horas": 8,
    })


@ia_bp.route("/chat", methods=["POST"])
def chat_asistente():
    """
    Punto de entrada principal para la interacción asíncrona (fetch) del chat:
    1. Valida el formato del payload JSON.
    2. Determina el rol de manera segura (JWT o Sesión).
    3. Sanitiza la entrada contra XSS y ataques de control.
    4. Detecta intentos de Prompt Injection y SQL Injection.
    5. Ejecuta el filtro de moderación (lenguaje ofensivo).
    6. Construye el contexto RAG con aislamiento estricto de base de datos.
    7. Envía el System Prompt y la consulta al proxy de Gemini.
    8. Retorna la respuesta generada con metadatos.
    """
    if not request.is_json:
        return jsonify({
            "success": False,
            "error": "El cuerpo de la petición debe ser JSON válido."
        }), 400

    datos = request.get_json() or {}
    mensaje_crudo = datos.get("mensaje", "")
    historial = datos.get("historial", [])

    if not isinstance(mensaje_crudo, str) or not mensaje_crudo.strip():
        return jsonify({
            "success": False,
            "error": "El mensaje no puede estar vacío."
        }), 400

    # 1. Determinación infalsificable del rol
    rol, meta = determinar_rol_usuario(request)

    # 2. Sanitización estricta de la entrada
    mensaje_sanitizado = sanitizar_input_usuario(mensaje_crudo)

    # 3. Detección de inyecciones (SQLi / Prompt Injection)
    es_amenaza, motivo = detectar_inyecciones(mensaje_sanitizado)
    if es_amenaza:
        logger.warning("Alerta de seguridad interceptada: %s (Usuario IP: %s)", motivo, request.remote_addr)
        return jsonify({
            "success": True,
            "respuesta": (
                "🛡️ **Aviso de Seguridad:** Tu mensaje contiene patrones no permitidos o instrucciones "
                "que intentan alterar las directivas de seguridad del sistema. Por favor, realiza una consulta "
                "directa sobre los servicios de TWINS Bakery."
            ),
            "rol": rol,
            "timestamp": datetime.datetime.now().isoformat(),
        })

    # 4. Filtro de moderación (Lenguaje ofensivo / faltas de respeto)
    es_ofensivo, mensaje_moderacion = verificar_moderacion(mensaje_sanitizado)
    if es_ofensivo:
        logger.info("Consulta bloqueada por moderación de lenguaje ofensivo.")
        return jsonify({
            "success": True,
            "respuesta": mensaje_moderacion,
            "rol": rol,
            "timestamp": datetime.datetime.now().isoformat(),
            "bloqueado_por_moderacion": True,
        })

    try:
        # 5. Flujo RAG: Obtener contexto aislado de solo lectura y construir System Prompt
        system_prompt, contexto_crudo = construir_prompt_rag(rol)

        # 6. Proxy a Gemini (Google AI Studio)
        respuesta_ia = enviar_consulta_gemini(
            system_prompt=system_prompt,
            historial_mensajes=historial if isinstance(historial, list) else [],
            mensaje_actual=mensaje_sanitizado,
            rol=rol,
            contexto_crudo=contexto_crudo,
        )

        return jsonify({
            "success": True,
            "respuesta": respuesta_ia,
            "rol": rol,
            "timestamp": datetime.datetime.now().isoformat(),
            "color_primario": PRIMARY_BRAND_COLOR,
        })

    except PermissionError as perm_err:
        logger.error("Violación de permisos en capa de datos: %s", perm_err)
        return jsonify({
            "success": False,
            "error": "Violación de seguridad de base de datos detectada y neutralizada.",
        }), 403

    except Exception as exc:
        logger.exception("Error interno procesando chat con IA: %s", exc)
        return jsonify({
            "success": False,
            "error": "Ocurrió un inconveniente temporal al procesar la respuesta. Por favor, intenta de nuevo.",
        }), 500
