"""
Módulo de Comunicación con la API de Google Gemini (Google AI Studio).
Actúa como Proxy Seguro en Python:
- El navegador jamás se comunica directamente con la API de Gemini ni ve la API_KEY.
- Forzado de TLS/HTTPS en todas las llamadas remotas.
- Envío de API_KEY vía encabezado 'x-goog-api-key' (previene exposición en logs de URL).
- Soporte para System Instructions nativas y Safety Settings de Google.
- Modo Simulación/Fallback inteligente si no se ha configurado la API Key en .env.
"""

import logging
import requests
from typing import List, Dict, Any, Optional
from .ia_config import (
    GEMINI_API_KEY,
    GEMINI_BASE_URL,
    GEMINI_TIMEOUT_SECONDS,
    GEMINI_MODEL,
)

logger = logging.getLogger("twins_ia_gemini")


def _generar_respuesta_local_fallback(
    mensaje_usuario: str, rol: str, contexto: Dict[str, Any]
) -> str:
    """
    Genera una respuesta determinista y contextual cuando GEMINI_API_KEY no está configurada en .env.
    Permite validar completamente el frontend, la seguridad y el flujo RAG sin interrumpir el desarrollo.
    """
    msg = mensaje_usuario.lower()

    if rol == "administrador":
        # Comprobar si pide modificar algo para probar la Hard Rule
        palabras_mutacion = ["crea", "modif", "cancel", "cambi", "actualiz", "edit", "elimin", "borr", "anul", "insert"]
        if any(p in msg for p in palabras_mutacion):
            return (
                "⚠️ **Acción Denegada por Seguridad (Hard Rule)**\n\n"
                "Como Asistente de IA para TWINS Bakery opero estrictamente en modalidad de **Solo Lectura**. "
                "Tengo terminantemente prohibido modificar, crear o cancelar registros de reservas o existencias en la base de datos.\n\n"
                "👉 *Por favor, realiza esta operación manualmente desde el apartado correspondiente en el Panel Administrativo.*"
            )

        if "venta" in msg or "financiero" in msg or "ingreso" in msg or "dinero" in msg:
            fin = contexto.get("resumen_financiero", {})
            return (
                f"📊 **Resumen Financiero TWINS Bakery:**\n\n"
                f"- **Reservas Activas:** {fin.get('total_reservas_activas', 0)}\n"
                f"- **Ventas Proyectadas:** ${fin.get('monto_total_ventas', 0.0):.2f}\n"
                f"- **Anticipos Cobrados:** ${fin.get('total_cobrado_anticipos', 0.0):.2f}\n\n"
                f"*Métricas obtenidas en tiempo real de la base de datos.*"
            )

        if "inventario" in msg or "stock" in msg or "producto" in msg:
            inv = contexto.get("inventario_real", [])
            items_str = "\n".join(
                [f"- **{it['nombre']}**: {it['stock_numerico']} unidades (${it['precio']:.2f})" for it in inv[:5]]
            )
            return (
                f"📦 **Estado de Inventario (Solo Administración):**\n\n"
                f"{items_str}\n\n"
                f"*Para reabastecer o dar de baja productos, utiliza el módulo 'Productos' del panel.*"
            )

        return (
            "👋 **Panel Analítico de TWINS Bakery (Modo IA Admin)**\n\n"
            "Tengo acceso de solo lectura a tus métricas de ventas, reservas activas y existencias en inventario. "
            "¿Deseas consultar el resumen financiero, reservas pendientes o el estado de productos críticos?\n\n"
            "*(Nota: Puedes configurar tu `GEMINI_API_KEY` en el archivo `.env` para activar respuestas generativas completas desde Google AI Studio).*"
        )

    # Rol Cliente
    if "reserva" in msg or "reservar" in msg or "apartar" in msg:
        return (
            "🎂 **Información sobre Reservas en TWINS Bakery:**\n\n"
            "Con gusto te oriento: por políticas de la pastelería, como asistente virtual **no puedo tomar reservas directamente en el chat**.\n\n"
            "Para asegurar tu pastel:\n"
            "1. Haz clic en el botón **'Reservar'** en nuestro catálogo web.\n"
            "2. O contáctanos directamente a nuestro WhatsApp oficial: **+503 2234-5678** o correo **pedidos@twinsbakery.com**.\n\n"
            "Recuerda que solicitamos un 50% de anticipo y que todos los pedidos se retiran en nuestra sucursal (no contamos con servicio a domicilio). 💗"
        )

    if "domicilio" in msg or "envio" in msg or "delivery" in msg:
        return (
            "🚗 **Política de Retiro:**\n\n"
            "En TWINS Bakery **no realizamos envíos a domicilio**. Todos nuestros deliciosos pasteles y postres "
            "se preparan cuidadosamente para ser retirados directamente en nuestra pastelería física. ¡Te esperamos!"
        )

    # Catálogo o productos
    prods = contexto.get("productos", [])
    if prods:
        ejemplos = "\n".join([f"- **{p['nombre']}** ({p['categoria']}): ${p['precio']:.2f} — *{p['disponibilidad']}*" for p in prods[:4]])
        return (
            f"🍰 **¡Bienvenido a TWINS Bakery!**\n\n"
            f"Te comparto algunas de nuestras especialidades disponibles:\n\n"
            f"{ejemplos}\n\n"
            f"¿Te gustaría conocer detalles de porciones, maridajes o paquetes para eventos especiales (bodas, baby shower, graduaciones)?\n\n"
            f"*(Nota: Configura `GEMINI_API_KEY` en `.env` para activar la IA en vivo de Google AI Studio).*"
        )

    return (
        "🍰 **¡Hola! Soy tu asistente de TWINS Bakery.**\n\n"
        "Puedo asesorarte sobre nuestros pasteles artesanales, precios y eventos. ¿En qué ocasión especial te gustaría endulzar tu día?"
    )


def enviar_consulta_gemini(
    system_prompt: str,
    historial_mensajes: List[Dict[str, str]],
    mensaje_actual: str,
    rol: str,
    contexto_crudo: Dict[str, Any],
) -> str:
    """
    Envía la consulta procesada a la API de Gemini (Google AI Studio) mediante HTTPS.
    Si GEMINI_API_KEY no está configurada, utiliza el motor fallback local determinista.
    """
    if not GEMINI_API_KEY:
        logger.info("GEMINI_API_KEY no detectada en .env; utilizando motor local de demostración seguro.")
        return _generar_respuesta_local_fallback(mensaje_actual, rol, contexto_crudo)

    # Construir historial para la API de Gemini
    # Estructura: {"role": "user"|"model", "parts": [{"text": ...}]}
    contents = []
    for m in historial_mensajes[-6:]:  # Limitar contexto histórico reciente para prevenir saturación
        role = "user" if m.get("rol") == "usuario" else "model"
        texto = m.get("texto", "").strip()
        if texto:
            contents.append({
                "role": role,
                "parts": [{"text": texto}],
            })

    # Agregar el mensaje actual del usuario
    contents.append({
        "role": "user",
        "parts": [{"text": mensaje_actual}],
    })

    # Cargar payload con directiva de sistema (System Instruction)
    payload = {
        "system_instruction": {
            "parts": [{"text": system_prompt}]
        },
        "contents": contents,
        "generationConfig": {
            "temperature": 0.2 if rol == "administrador" else 0.4,
            "maxOutputTokens": 900,
            "topP": 0.8,
        },
        "safetySettings": [
            {
                "category": "HARM_CATEGORY_HARASSMENT",
                "threshold": "BLOCK_MEDIUM_AND_ABOVE",
            },
            {
                "category": "HARM_CATEGORY_HATE_SPEECH",
                "threshold": "BLOCK_MEDIUM_AND_ABOVE",
            },
            {
                "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                "threshold": "BLOCK_MEDIUM_AND_ABOVE",
            },
            {
                "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                "threshold": "BLOCK_MEDIUM_AND_ABOVE",
            },
        ],
    }

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY,
    }

    try:
        # Petición HTTPS forzada con timeout estricto
        response = requests.post(
            GEMINI_BASE_URL,
            json=payload,
            headers=headers,
            timeout=GEMINI_TIMEOUT_SECONDS,
            verify=True,  # Forzar validación estricta de certificado TLS
        )

        if response.status_code == 200:
            datos = response.json()
            candidatos = datos.get("candidates", [])
            if candidatos and "content" in candidatos[0]:
                partes = candidatos[0]["content"].get("parts", [])
                if partes and "text" in partes[0]:
                    return partes[0]["text"].strip()
            return "No fue posible generar una respuesta adecuada en este momento. Por favor, intenta de nuevo."

        elif response.status_code == 429:
            logger.warning("Cuota de Gemini excedida (Rate Limit 429).")
            return "El asistente de IA ha alcanzado el límite momentáneo de consultas. Por favor, aguarda unos segundos y vuelve a intentar."

        elif response.status_code in (401, 403):
            logger.error("Credencial GEMINI_API_KEY inválida o sin permisos (HTTP %s).", response.status_code)
            return "La clave de acceso de Gemini no es válida o carece de permisos en Google AI Studio. Verifica la variable GEMINI_API_KEY en .env."

        else:
            logger.error("Error devuelto por Gemini API: HTTP %s - %s", response.status_code, response.text[:200])
            return _generar_respuesta_local_fallback(mensaje_actual, rol, contexto_crudo)

    except requests.exceptions.Timeout:
        logger.warning("Timeout al conectar con la API de Google Gemini.")
        return "El servicio de IA tardó demasiado en responder. Por favor, intenta de nuevo en unos momentos."

    except requests.exceptions.SSLError as ssl_err:
        logger.error("Error de TLS/SSL al conectar con Gemini: %s", ssl_err)
        return "Error de seguridad en la conexión cifrada con Google Gemini. Verifica los certificados del sistema."

    except Exception as exc:
        logger.error("Excepción inesperada al invocar Gemini: %s", exc)
        return _generar_respuesta_local_fallback(mensaje_actual, rol, contexto_crudo)
