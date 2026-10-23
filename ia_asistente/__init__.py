"""
Módulo del Asistente de Inteligencia Artificial para TWINS Bakery.
Integra Gemini (Google AI Studio), RAG con aislamiento estricto por rol,
defensa en profundidad para base de datos y cifrado de PII.
"""

from .ia_rutas import ia_bp

__all__ = ["ia_bp"]
