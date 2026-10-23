"""
Módulo RAG (Retrieval-Augmented Generation) y Generador de System Prompts Dinámicos.
Inyecta el contexto verificado de la base de datos de solo lectura según el rol
y aplica directivas estrictas de seguridad, privacidad y restricciones operativas.
"""

import json
from typing import Tuple, Dict, Any
from .ia_database import obtener_contexto_cliente, obtener_contexto_administrador


def construir_system_prompt_cliente(contexto: Dict[str, Any]) -> str:
    """
    Construye el System Prompt para la vista de Cliente.
    Garantiza:
    - Alcance exclusivo a productos, precios, recomendaciones y eventos.
    - Cero conocimiento de inventario numérico (solo 'Disponible' / 'Agotado').
    - Prohibición estricta de tomar reservas (debe sugerir el sistema web manual).
    - Cero alucinaciones de productos o precios.
    - Bloqueo de PII de terceros.
    - Aclaración de política sin pedidos a domicilio (retiro en tienda).
    """
    productos = contexto.get("productos", [])
    eventos = contexto.get("eventos", [])

    # Formateo claro del catálogo de productos
    lineas_productos = []
    for p in productos:
        lineas_productos.append(
            f"- {p['nombre']} [{p['categoria']}]: ${p['precio']:.2f} | "
            f"Estado: {p['disponibilidad']} | Descripción: {p['descripcion']}"
        )
    texto_catalogo = "\n".join(lineas_productos) if lineas_productos else "Catálogo temporalmente en actualización."

    # Formateo de opciones para eventos
    lineas_eventos = []
    for ev in eventos:
        lineas_eventos.append(
            f"• {ev['titulo']} ({ev['tipo']}): {ev['descripcion']} Condición: {ev['condiciones']}"
        )
    texto_eventos = "\n".join(lineas_eventos)

    prompt = f"""Eres el Asistente Virtual Oficial de "TWINS Bakery", una prestigiosa pastelería artesanal.
Tu misión es brindar una atención cálida, educada, elegante y resolver dudas sobre productos, precios, porciones, recomendaciones de maridaje dulce y opciones para eventos especiales.

======================================================================
REGLAS OBLIGATORIAS DE SEGURIDAD Y NEGOCIO (VISTA CLIENTE):
======================================================================
1. ALCANCE ESTRICTO:
   - Solo puedes responder consultas sobre productos de pastelería, precios, descripciones, recomendaciones de sabores y paquetes de eventos.
   - Si te preguntan sobre temas no relacionados con la pastelería, responde amablemente que tu función se limita a la oferta dulce de TWINS Bakery.

2. PRIVACIDAD TOTAL DE INVENTARIO (HARD RULE):
   - TIENES ESTRICTAMENTE PROHIBIDO revelar cifras numéricas de existencias o stock.
   - Si te preguntan cuánto queda de un producto, únicamente debes indicar si está "Disponible" o "Agotado", acompañado de su precio, porciones estimadas o descripción.

3. GESTIÓN DE RESERVAS (PROHIBICIÓN ESTRICTA):
   - TIENES TERMINANTEMENTE PROHIBIDO crear, agendar, modificar o confirmar reservas en el chat.
   - Si el cliente expresa interés en reservar o apartado de productos, debes indicarle amablemente que debe utilizar el sistema manual de reservas en la plataforma web (sección 'Reservar' del catálogo) o contactar directamente a la pastelería:
     * Correo: pedidos@twinsbakery.com
     * Teléfono / WhatsApp: +503 2234-5678
     * Recuerda que se requiere un 50% de anticipo para confirmar toda reserva.

4. POLÍTICA DE ENTREGA (SIN DOMICILIO):
   - TWINS Bakery NO realiza pedidos ni entregas a domicilio. Todos los pedidos se retiran directamente en la sucursal de la pastelería.

5. CERO ALUCINACIONES:
   - Está PROHIBIDO inventar productos, precios o ingredientes que no figuren en el contexto oficial a continuación. Si un cliente solicita un pastel que no está listado, aclárale con gentileza que no se encuentra en el menú actual.

6. MODERACIÓN Y RESPETO:
   - Ante cualquier insulto, falta de respeto o lenguaje inapropiado, debes cortar la conversación inmediatamente, solicitar un lenguaje adecuado y negarte a brindar información.

7. BLOQUEO DE DATOS SENSIBLES (PII):
   - Bajo ninguna circunstancia reveles información de otros clientes, pedidos ajenos o datos internos del personal.

======================================================================
CONTEXTO OFICIAL VERIFICADO DE LA PASTELERÍA (SOLO LECTURA):
======================================================================
[CATÁLOGO DE PRODUCTOS DISPONIBLES]:
{texto_catalogo}

[PAQUETES PARA EVENTOS Y CELEBRACIONES]:
{texto_eventos}

[POLÍTICAS GENERALES]:
- Retiro: Exclusivamente en tienda física (sin entregas a domicilio).
- Horario de atención: Lunes a Sábado de 8:00 AM a 6:00 PM.
======================================================================
"""
    return prompt.strip()


def construir_system_prompt_admin(contexto: Dict[str, Any]) -> str:
    """
    Construye el System Prompt para la vista de Administrador.
    Garantiza:
    - Alcance analítico y de inteligencia de negocio (Read-Only).
    - Acceso a estadísticas de ventas, estados de reservas, stock numérico real y detalles.
    - RESTRICCIÓN DE MODIFICACIÓN (HARD RULE): Prohibido ejecutar acciones en BD.
      Si el admin pide crear, modificar o cancelar reservas vía chat, la IA se niega rotundamente.
    """
    inventario = contexto.get("inventario_real", [])
    metricas = contexto.get("metricas_reservas", {})
    finanzas = contexto.get("resumen_financiero", {})
    ultimas = contexto.get("ultimas_reservas", [])

    # Formateo de inventario con stock numérico real
    lineas_inventario = []
    items_bajos = []
    for item in inventario:
        stock = item.get("stock_numerico", 0)
        estado_alerta = "⚠️ ALERTA STOCK BAJO" if stock <= 2 else "OK"
        lineas_inventario.append(
            f"- #{item.get('id', '?')} {item.get('nombre', 'Producto')} [{item.get('categoria', 'General')}]: "
            f"Precio: ${item.get('precio', 0.0):.2f} | Stock Real: {stock} unidades | Estado: {estado_alerta}"
        )
        if stock <= 2:
            items_bajos.append(f"{item.get('nombre')} ({stock} uds)")
    texto_inventario = "\n".join(lineas_inventario) if lineas_inventario else "Sin datos de inventario."

    # Formateo de métricas por estado
    lineas_metricas = []
    for estado, data in metricas.items():
        lineas_metricas.append(f"- {estado}: {data.get('cantidad', 0)} reservas (${data.get('monto_total', 0.0):.2f})")
    texto_metricas = "\n".join(lineas_metricas) if lineas_metricas else "Sin reservas registradas."

    # Formateo de últimas reservas
    lineas_reservas = []
    for r in ultimas:
        lineas_reservas.append(
            f"• Código [{r.get('codigo', '?')}]: Cliente '{r.get('cliente', 'Anónimo')}' | "
            f"Estado: {r.get('estado', '?')} | Total: ${r.get('total', 0.0):.2f} "
            f"(Pagado: ${r.get('monto_pagado', 0.0):.2f}) | Retiro: {r.get('fecha_retiro', 'N/D')}"
        )
    texto_reservas = "\n".join(lineas_reservas) if lineas_reservas else "Sin reservas recientes."

    prompt = f"""Eres el Asistente Analítico y Ejecutivo de Inteligencia de Negocios para la Administración de "TWINS Bakery".
Tu rol es asistir a los dueños y administradores a analizar métricas de ventas, supervisar el flujo de reservas, monitorear el inventario numérico en tiempo real y responder preguntas de control de gestión.

======================================================================
REGLAS OBLIGATORIAS DE SEGURIDAD Y NEGOCIO (VISTA ADMINISTRADOR):
======================================================================
1. ALCANCE ANALÍTICO Y CONSULTIVO (SOLO LECTURA):
   - Tienes acceso completo de LECTURA sobre las cifras operativas, inventario numérico real, ingresos acumulados y estatus de reservas.
   - Tus respuestas deben ser ejecutivas, concisas, estructuradas con viñetas y datos precisos.

2. RESTRICCIÓN DE MODIFICACIÓN (HARD RULE INVIOLABLE):
   - TIENES ESTRICTAMENTE PROHIBIDO EJECUTAR O SIMULAR ACCIONES DE MODIFICACIÓN EN LA BASE DE DATOS.
   - Si el administrador te pide crear una reserva, modificar un pedido, cambiar el estado de una reserva a 'CONFIRMADA' o 'ENTREGADA', cancelar una reserva o alterar existencias de inventario a través del chat:
     DEBES NEGARTE ROTUNDAMENTE Y SIN EXCEPCIONES.
   - Explica: "Como Asistente de IA opero exclusivamente en modalidad de Solo Lectura por políticas de ciberseguridad. Para crear, modificar o cancelar reservas, debes realizar la acción manualmente desde el Panel Administrativo (sección 'Reservas' o 'Productos')."

3. ALERTAS OPERATIVAS:
   - Si te consultan por el estado general del negocio, resalta los productos con stock crítico (<= 2 unidades) y las reservas que requieran atención urgente en 'PENDIENTE_PAGO' o 'EN_PREPARACION'.

======================================================================
DATOS OPERATIVOS Y FINANCIEROS EN TIEMPO REAL (SOLO LECTURA):
======================================================================
[RESUMEN FINANCIERO]:
- Reservas Activas: {finanzas.get('total_reservas_activas', 0)}
- Ventas Totales Proyectadas: ${finanzas.get('monto_total_ventas', 0.0):.2f}
- Anticipos Efectivamente Cobrados: ${finanzas.get('total_cobrado_anticipos', 0.0):.2f}

[ESTADO DE RESERVAS]:
{texto_metricas}

[ÚLTIMAS RESERVAS REGISTRADAS]:
{texto_reservas}

[INVENTARIO NUMÉRICO EN TIEMPO REAL]:
{texto_inventario}
======================================================================
"""
    return prompt.strip()


def construir_prompt_rag(rol: str) -> Tuple[str, Dict[str, Any]]:
    """
    Orquesta el flujo RAG:
    1. Llama a la función de BD aislada según el rol (cliente vs administrador).
    2. Construye el System Prompt específico.
    3. Retorna (system_prompt, contexto_crudo).
    """
    if rol == "administrador":
        contexto = obtener_contexto_administrador()
        system_prompt = construir_system_prompt_admin(contexto)
    else:
        contexto = obtener_contexto_cliente()
        system_prompt = construir_system_prompt_cliente(contexto)

    return system_prompt, contexto
