"""
Módulo de servicios de correo electrónico para TWINS Bakery.
Utiliza smtplib estándar de Python con soporte para Gmail y servidores SMTP seguros.
Los envíos se realizan de forma asíncrona mediante hilos para no retrasar la experiencia del usuario.
"""

import os
import smtplib
import ssl
import threading
import logging
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

logger = logging.getLogger("twins_bakery_correo")

# ==============================================================================
# CONFIGURACIÓN DEL CORREO EMISOR (SE SUBE A GIT Y SE COMPARTE CON EL EQUIPO)
#
# Coloca aquí el correo de Gmail y la contraseña de aplicación de 16 caracteres.
# Como este archivo sí se sube a Git, cuando tus compañeros clonen el repositorio
# les funcionará el envío de correos automáticamente sin configurar ningún .env.
# ==============================================================================
CORREO_EMISOR = ""       # Escribe aquí tu correo: "ejemplo@gmail.com"
PASSWORD_EMISOR = ""     # Escribe aquí la contraseña de aplicación: "abcd efgh ijkl mnop"
NOMBRE_REMITENTE = "TWINS Bakery"


def _obtener_configuracion_correo():
    """Obtiene la configuración usando las variables del código o el .env si existe."""
    servidor = os.getenv("MAIL_SERVER", "smtp.gmail.com").strip()
    puerto_raw = os.getenv("MAIL_PORT", "587").strip()
    try:
        puerto = int(puerto_raw)
    except ValueError:
        puerto = 587

    use_tls_str = os.getenv("MAIL_USE_TLS", "true").strip().lower()
    usar_tls = use_tls_str in {"true", "1", "yes", "si", "on"}

    # Prioridad: si está en .env lo usa; si no, usa las constantes del código para el equipo
    usuario = (os.getenv("MAIL_USERNAME") or CORREO_EMISOR).strip()
    contrasena = (os.getenv("MAIL_PASSWORD") or PASSWORD_EMISOR).strip().replace(" ", "")

    remitente = os.getenv("MAIL_DEFAULT_SENDER", "").strip()
    if not remitente and usuario:
        remitente = formataddr((NOMBRE_REMITENTE, usuario))
    elif not remitente:
        remitente = f"{NOMBRE_REMITENTE} <notificaciones@twinsbakery.com>"

    return {
        "servidor": servidor,
        "puerto": puerto,
        "usar_tls": usar_tls,
        "usuario": usuario,
        "contrasena": contrasena,
        "remitente": remitente,
    }


def _plantilla_base_html(titulo_cabecera, subtitulo_cabecera, contenido_html):
    """Genera el contenedor HTML estilizado con la identidad visual de TWINS Bakery."""
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{titulo_cabecera}</title>
</head>
<body style="margin:0; padding:0; background-color:#fff5f7; font-family:'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color:#2d3748; line-height:1.6;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background-color:#fff5f7; padding:30px 15px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" style="max-width:600px; background-color:#ffffff; border-radius:16px; overflow:hidden; box-shadow:0 8px 30px rgba(224,83,116,0.12); border:1px solid #fed7e2;">
          
          <!-- CABECERA -->
          <tr>
            <td style="background: linear-gradient(135deg, #e05374 0%, #f687b3 100%); padding:35px 30px; text-align:center; color:#ffffff;">
              <div style="font-size:32px; line-height:1; margin-bottom:10px;">🎂</div>
              <h1 style="margin:0; font-size:26px; font-weight:800; letter-spacing:1px; text-transform:uppercase;">TWINS <span style="font-weight:300; font-size:20px;">BAKERY</span></h1>
              <p style="margin:8px 0 0; font-size:14px; opacity:0.95; font-weight:500;">{subtitulo_cabecera}</p>
            </td>
          </tr>

          <!-- CONTENIDO PRINCIPAL -->
          <tr>
            <td style="padding:35px 30px 25px;">
              {contenido_html}
            </td>
          </tr>

          <!-- PIE DE CORREO -->
          <tr>
            <td style="background-color:#fff0f3; padding:25px 30px; text-align:center; border-top:1px solid #fed7e2; font-size:13px; color:#718096;">
              <p style="margin:0 0 8px; font-weight:600; color:#e05374;">TWINS Bakery · Pastelería Artesanal con Amor 💗</p>
              <p style="margin:0; font-size:12px; color:#a0aec0;">Este es un mensaje automático para notificarte sobre la actividad en tu cuenta o tus pedidos.</p>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def _enviar_correo_sincrono(destinatario, asunto, cuerpo_html, cuerpo_texto):
    """Envía el correo mediante SMTP de forma directa con manejo exhaustivo de excepciones."""
    if not destinatario or "@" not in destinatario:
        logger.warning("No se puede enviar correo: destinatario no válido (%s)", destinatario)
        return False

    config = _obtener_configuracion_correo()

    # Si aún no se configuraron credenciales en el archivo .env
    if not config["usuario"] or not config["contrasena"]:
        logger.info(
            "Correo no enviado a %s: MAIL_USERNAME o MAIL_PASSWORD no configurados en .env",
            destinatario
        )
        try:
            print(f"[TWINS BAKERY - CORREO PENDIENTE DE CONFIGURACION] Destinatario: {destinatario} | Asunto: {asunto}")
            print("[INFO] Para que este correo llegue a la bandeja de entrada, anade MAIL_USERNAME y MAIL_PASSWORD en tu archivo .env")
        except Exception:
            pass
        return False

    try:
        mensaje = MIMEMultipart("alternative")
        mensaje["Subject"] = asunto
        mensaje["From"] = config["remitente"]
        mensaje["To"] = destinatario

        # Parte en texto plano para clientes sin soporte HTML o lectores de pantalla
        parte_texto = MIMEText(cuerpo_texto, "plain", "utf-8")
        mensaje.attach(parte_texto)

        # Parte en HTML
        parte_html = MIMEText(cuerpo_html, "html", "utf-8")
        mensaje.attach(parte_html)

        servidor_smtp = config["servidor"]
        puerto_smtp = config["puerto"]

        contexto_ssl = ssl.create_default_context()

        # Puerto 465 utiliza SSL directo; puerto 587 utiliza STARTTLS
        if puerto_smtp == 465:
            with smtplib.SMTP_SSL(servidor_smtp, puerto_smtp, context=contexto_ssl, timeout=15) as servidor:
                servidor.login(config["usuario"], config["contrasena"])
                servidor.sendmail(config["usuario"], destinatario, mensaje.as_string())
        else:
            with smtplib.SMTP(servidor_smtp, puerto_smtp, timeout=15) as servidor:
                if config["usar_tls"]:
                    servidor.starttls(context=contexto_ssl)
                servidor.login(config["usuario"], config["contrasena"])
                servidor.sendmail(config["usuario"], destinatario, mensaje.as_string())

        logger.info("Correo enviado exitosamente a %s: %s", destinatario, asunto)
        try:
            print(f"[OK CORREO ENVIADO] A: {destinatario} | Asunto: {asunto}")
        except Exception:
            pass
        return True

    except Exception as e:
        logger.exception("Error al enviar correo a %s: %s", destinatario, str(e))
        try:
            print(f"[ERROR CORREO] No se pudo enviar correo a {destinatario}: {e}")
        except Exception:
            pass
        return False


def _despachar_asincrono(destinatario, asunto, cuerpo_html, cuerpo_texto):
    """Ejecuta el envío de correo en un hilo secundario para evitar bloquear el servidor web."""
    hilo = threading.Thread(
        target=_enviar_correo_sincrono,
        args=(destinatario, asunto, cuerpo_html, cuerpo_texto),
        daemon=True
    )
    hilo.start()


# ==============================================================================
# 1. BIENVENIDA TRAS REGISTRO DE CLIENTE
# ==============================================================================

def enviar_correo_bienvenida(destinatario, nombre):
    """Envía un correo de bienvenida cálido y estilizado al nuevo cliente registrado."""
    nombre_seguro = nombre.strip() if nombre else "amigo/a"
    asunto = "¡Bienvenido a TWINS Bakery! 🎂💗"

    contenido_html = f"""
      <h2 style="color:#e05374; margin-top:0; font-size:22px; font-weight:700;">¡Hola, {nombre_seguro}! 💗</h2>
      <p style="font-size:15px; color:#4a5568;">
        ¡Qué alegría tenerte en nuestra familia! Tu cuenta en <strong>TWINS Bakery</strong> ha sido creada exitosamente con este correo.
      </p>
      <p style="font-size:15px; color:#4a5568;">
        A partir de ahora podrás explorar nuestros postres y pasteles artesanales, realizar reservas para tus cumpleaños y eventos especiales, y darle un toque dulce a cada momento.
      </p>

      <div style="background-color:#fff5f7; border-left:4px solid #e05374; padding:15px 18px; margin:25px 0; border-radius:0 10px 10px 0;">
        <p style="margin:0; font-size:14px; color:#70243b; font-weight:600;">
          🍰 Hecho artesanalmente con amor y los mejores ingredientes.
        </p>
      </div>

      <p style="font-size:15px; color:#4a5568;">
        Para ingresar a tu cuenta cuando gustes, ve al inicio de sesión e ingresa con tu correo y contraseña.
      </p>

      <p style="margin:30px 0 10px; font-size:15px; color:#4a5568;">
        ¡Esperamos endulzar tu día muy pronto!<br>
        <strong>El equipo de TWINS Bakery</strong>
      </p>
    """

    cuerpo_texto = f"""¡Hola, {nombre_seguro}!

¡Bienvenido a la familia de TWINS Bakery! 💗

Tu cuenta ha sido creada exitosamente. A partir de ahora podrás explorar nuestro catálogo de pasteles artesanales, realizar reservas para tus celebraciones y eventos especiales, y disfrutar de nuestros mejores postres.

Para ingresar a tu cuenta cuando gustes, ve a la página de inicio de sesión e ingresa tu correo y contraseña.

¡Gracias por unirte a nosotros!
El equipo de TWINS Bakery.
"""

    html_completo = _plantilla_base_html("Bienvenido a TWINS Bakery", "Pastelería Artesanal Hecha con Amor", contenido_html)
    _despachar_asincrono(destinatario, asunto, html_completo, cuerpo_texto)


# ==============================================================================
# 2. NOTIFICACIÓN DE INICIO DE SESIÓN
# ==============================================================================

def enviar_correo_inicio_sesion(destinatario, nombre, fecha_hora=None):
    """Envía una notificación al correo del cliente cuando inicia sesión exitosamente."""
    nombre_seguro = nombre.strip() if nombre else "estimado/a cliente"
    asunto = "Inicio de sesión exitoso en TWINS Bakery 🔐"

    if not fecha_hora:
        fecha_hora = datetime.now().strftime("%d/%m/%Y a las %I:%M %p")

    contenido_html = f"""
      <h2 style="color:#e05374; margin-top:0; font-size:22px; font-weight:700;">Hola, {nombre_seguro} 🔐</h2>
      <p style="font-size:15px; color:#4a5568;">
        Te informamos que se ha iniciado sesión correctamente en tu cuenta de <strong>TWINS Bakery</strong>.
      </p>

      <div style="background-color:#edf2f7; border-radius:10px; padding:18px 20px; margin:22px 0;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="font-size:14px; color:#4a5568;">
          <tr>
            <td style="padding:4px 0; font-weight:600; width:140px;">📅 Fecha y hora:</td>
            <td style="padding:4px 0;">{fecha_hora}</td>
          </tr>
          <tr>
            <td style="padding:4px 0; font-weight:600;">✉️ Correo de cuenta:</td>
            <td style="padding:4px 0;">{destinatario}</td>
          </tr>
          <tr>
            <td style="padding:4px 0; font-weight:600;">🌐 Estado:</td>
            <td style="padding:4px 0; color:#38a169; font-weight:700;">Sesión iniciada con éxito</td>
          </tr>
        </table>
      </div>

      <p style="font-size:14px; color:#718096;">
        Si fuiste tú quien ingresó, no tienes que hacer nada, ¡disfruta de nuestros postres! Si no reconoces este inicio de sesión, te recomendamos cambiar tu contraseña de inmediato para proteger tu cuenta.
      </p>

      <p style="margin:25px 0 0; font-size:14px; color:#4a5568;">
        Atentamente,<br>
        <strong>Seguridad TWINS Bakery</strong>
      </p>
    """

    cuerpo_texto = f"""Hola, {nombre_seguro}

Te notificamos que se ha iniciado sesión en tu cuenta de TWINS Bakery el {fecha_hora}.

Si fuiste tú, puedes ignorar este mensaje. Si no reconoces esta actividad, cambia tu contraseña de inmediato.

Atentamente,
El equipo de TWINS Bakery.
"""

    html_completo = _plantilla_base_html("Inicio de sesión en TWINS Bakery", "Notificación de Seguridad", contenido_html)
    _despachar_asincrono(destinatario, asunto, html_completo, cuerpo_texto)


# ==============================================================================
# 3. NOTIFICACIÓN DE RESERVA REALIZADA (PASTELES Y EVENTOS)
# ==============================================================================

def enviar_correo_reserva_creada(
    destinatario,
    nombre,
    codigo,
    nombre_producto,
    categoria,
    cantidad,
    total,
    anticipo,
    fecha_retiro,
    metodo_pago
):
    """
    Envía confirmación al cliente tras registrar su reserva.
    Si es un pastel o un evento, destaca la instrucción obligatoria de pasar a dejar
    el 50% de anticipo a la sucursal.
    """
    nombre_seguro = nombre.strip() if nombre else "estimado/a cliente"
    asunto = f"Reserva Registrada [Código: {codigo}] - TWINS Bakery 🎂"

    # Determinar si aplica aviso de pasteles o eventos
    categoria_texto = (categoria or "").strip().lower()
    prod_texto = (nombre_producto or "").strip().lower()
    es_pastel_o_evento = any(
        palabra in categoria_texto or palabra in prod_texto
        for palabra in ["pastel", "evento", "boda", "cumpleaños", "fiesta", "aniversario"]
    )

    # Formateo amigable de la fecha de retiro
    if isinstance(fecha_retiro, datetime):
        fecha_retiro_str = fecha_retiro.strftime("%d/%m/%Y a las %I:%M %p")
    else:
        fecha_retiro_str = str(fecha_retiro)

    nombre_metodo = "Efectivo en tienda" if metodo_pago == "EFECTIVO_TIENDA" else "Pago en línea con tarjeta (Wompi)"

    aviso_anticipo_html = ""
    aviso_anticipo_texto = ""

    if es_pastel_o_evento:
        aviso_anticipo_html = f"""
        <div style="background-color:#fffaf0; border:2px solid #dd6b20; border-radius:12px; padding:18px 20px; margin:25px 0;">
          <h3 style="color:#c05621; margin:0 0 8px; font-size:16px; font-weight:800; display:flex; align-items:center;">
            ⚠️ RECORDATORIO IMPORTANTE PARA PASTELES Y EVENTOS
          </h3>
          <p style="margin:0; font-size:14px; color:#7b341e; line-height:1.5;">
            Para que nuestro equipo comience la elaboración artesanal de tu pedido, 
            <strong>debes pasar a dejar la mitad del dinero (${float(anticipo):.2f} USD) a nuestra sucursal de TWINS Bakery</strong> 
            presentando tu código de reserva: <strong>{codigo}</strong>.
          </p>
        </div>
        """
        aviso_anticipo_texto = f"""
==============================================================
⚠️ RECORDATORIO IMPORTANTE PARA PASTELES Y EVENTOS:
Para que nuestro equipo comience la elaboración de tu pedido,
debes pasar a dejar la mitad del dinero (${float(anticipo):.2f} USD)
a nuestra sucursal de TWINS Bakery con tu código: {codigo}.
==============================================================
"""
    else:
        aviso_anticipo_html = f"""
        <div style="background-color:#fff5f7; border-left:4px solid #e05374; border-radius:8px; padding:15px; margin:22px 0;">
          <p style="margin:0; font-size:14px; color:#70243b;">
            Anticipo requerido para confirmar tu pedido: <strong>${float(anticipo):.2f} USD (50%)</strong>.
          </p>
        </div>
        """

    contenido_html = f"""
      <h2 style="color:#e05374; margin-top:0; font-size:22px; font-weight:700;">¡Tu reserva ha sido recibida! 🍰</h2>
      <p style="font-size:15px; color:#4a5568;">
        Hola <strong>{nombre_seguro}</strong>, hemos registrado tu solicitud de reserva en <strong>TWINS Bakery</strong>.
      </p>

      {aviso_anticipo_html}

      <!-- RESUMEN DEL PEDIDO -->
      <div style="background-color:#ffffff; border:1px solid #e2e8f0; border-radius:12px; padding:20px; margin:20px 0; box-shadow:0 2px 8px rgba(0,0,0,0.03);">
        <div style="text-align:center; padding-bottom:15px; border-bottom:1px dashed #cbd5e0; margin-bottom:15px;">
          <span style="font-size:12px; text-transform:uppercase; letter-spacing:1px; color:#718096; font-weight:600;">Código de Reserva</span>
          <div style="font-size:24px; font-weight:800; color:#e05374; letter-spacing:2px; margin-top:4px;">{codigo}</div>
        </div>

        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="font-size:14px; color:#4a5568;">
          <tr>
            <td style="padding:6px 0; font-weight:600;">🍰 Producto:</td>
            <td style="padding:6px 0; text-align:right;">{nombre_producto}</td>
          </tr>
          <tr>
            <td style="padding:6px 0; font-weight:600;">📦 Cantidad:</td>
            <td style="padding:6px 0; text-align:right;">{cantidad} unidad(es)</td>
          </tr>
          <tr>
            <td style="padding:6px 0; font-weight:600;">💵 Total del pedido:</td>
            <td style="padding:6px 0; text-align:right; font-weight:700;">${float(total):.2f} USD</td>
          </tr>
          <tr style="color:#e05374;">
            <td style="padding:6px 0; font-weight:700;">⭐ Anticipo (50%):</td>
            <td style="padding:6px 0; text-align:right; font-weight:800; font-size:15px;">${float(anticipo):.2f} USD</td>
          </tr>
          <tr>
            <td style="padding:6px 0; font-weight:600;">📅 Fecha y hora de retiro:</td>
            <td style="padding:6px 0; text-align:right;">{fecha_retiro_str}</td>
          </tr>
          <tr>
            <td style="padding:6px 0; font-weight:600;">💳 Método de pago:</td>
            <td style="padding:6px 0; text-align:right;">{nombre_metodo}</td>
          </tr>
        </table>
      </div>

      <p style="font-size:14px; color:#718096;">
        Una vez que verifiquemos tu anticipo en tienda o en línea, el administrador aceptará tu reserva y recibirás una notificación de confirmación en este correo.
      </p>

      <p style="margin:25px 0 0; font-size:15px; color:#4a5568;">
        ¡Gracias por elegirnos!<br>
        <strong>TWINS Bakery</strong>
      </p>
    """

    cuerpo_texto = f"""¡Tu reserva ha sido recibida! 🍰

Hola {nombre_seguro},

Hemos registrado tu solicitud de reserva en TWINS Bakery.

Código de Reserva: {codigo}
Producto: {nombre_producto}
Cantidad: {cantidad}
Total: ${float(total):.2f} USD
Anticipo requerido (50%): ${float(anticipo):.2f} USD
Fecha de retiro: {fecha_retiro_str}
Método de pago: {nombre_metodo}
{aviso_anticipo_texto}
Una vez que el administrador acepte tu reserva en tienda o mediante tu anticipo, recibirás un correo de confirmación oficial.

¡Gracias por confiar en TWINS Bakery!
"""

    html_completo = _plantilla_base_html(f"Reserva {codigo}", "Confirmación de Reserva", contenido_html)
    _despachar_asincrono(destinatario, asunto, html_completo, cuerpo_texto)


# ==============================================================================
# 4. NOTIFICACIÓN DE RESERVA ACEPTADA POR EL ADMINISTRADOR
# ==============================================================================

def enviar_correo_reserva_aceptada(
    destinatario,
    nombre,
    codigo,
    nombre_producto,
    cantidad,
    total,
    monto_pagado,
    fecha_retiro
):
    """Envía la notificación final al cliente indicando que su reserva fue aceptada por el administrador."""
    nombre_seguro = nombre.strip() if nombre else "estimado/a cliente"
    asunto = f"¡Tu reserva ha sido aceptada! [Código: {codigo}] - TWINS Bakery 🎉"

    if isinstance(fecha_retiro, datetime):
        fecha_retiro_str = fecha_retiro.strftime("%d/%m/%Y a las %I:%M %p")
    else:
        fecha_retiro_str = str(fecha_retiro)

    total_f = float(total)
    pagado_f = float(monto_pagado)
    saldo_restante = max(0.0, total_f - pagado_f)

    contenido_html = f"""
      <div style="text-align:center; margin-bottom:20px;">
        <span style="display:inline-block; background-color:#c6f6d5; color:#22543d; font-size:13px; font-weight:800; padding:6px 16px; border-radius:50px; text-transform:uppercase; letter-spacing:1px;">
          ✓ Reserva Confirmada
        </span>
      </div>

      <h2 style="color:#22543d; margin-top:0; font-size:23px; font-weight:800; text-align:center;">
        ¡Buenas noticias, {nombre_seguro}! 🎉
      </h2>

      <p style="font-size:15px; color:#4a5568; text-align:center;">
        Tu reserva con código <strong>{codigo}</strong> para <strong>{nombre_producto}</strong> ha sido 
        <strong style="color:#38a169;">aceptada correctamente</strong> por el equipo de TWINS Bakery.
      </p>

      <div style="background-color:#f0fff4; border:1px solid #9ae6b4; border-radius:12px; padding:20px; margin:25px 0;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="font-size:14px; color:#2d3748;">
          <tr>
            <td style="padding:6px 0; font-weight:600;">🔖 Código de reserva:</td>
            <td style="padding:6px 0; text-align:right; font-weight:800; color:#22543d;">{codigo}</td>
          </tr>
          <tr>
            <td style="padding:6px 0; font-weight:600;">🍰 Producto:</td>
            <td style="padding:6px 0; text-align:right;">{nombre_producto}</td>
          </tr>
          <tr>
            <td style="padding:6px 0; font-weight:600;">📦 Cantidad:</td>
            <td style="padding:6px 0; text-align:right;">{cantidad} unidad(es)</td>
          </tr>
          <tr>
            <td style="padding:6px 0; font-weight:600;">💵 Total:</td>
            <td style="padding:6px 0; text-align:right;">${total_f:.2f} USD</td>
          </tr>
          <tr>
            <td style="padding:6px 0; font-weight:600;">💰 Anticipo registrado:</td>
            <td style="padding:6px 0; text-align:right; font-weight:700; color:#38a169;">${pagado_f:.2f} USD</td>
          </tr>
          <tr>
            <td style="padding:6px 0; font-weight:600;">🏷️ Saldo al retirar:</td>
            <td style="padding:6px 0; text-align:right; font-weight:700;">${saldo_restante:.2f} USD</td>
          </tr>
          <tr style="border-top:1px dashed #cbd5e0;">
            <td style="padding:10px 0 0; font-weight:700; color:#e05374;">📅 Fecha y hora de entrega:</td>
            <td style="padding:10px 0 0; text-align:right; font-weight:800; color:#e05374;">{fecha_retiro_str}</td>
          </tr>
        </table>
      </div>

      <div style="background-color:#fff5f7; border-left:4px solid #e05374; border-radius:8px; padding:15px; margin:22px 0;">
        <p style="margin:0; font-size:14px; color:#70243b;">
          💡 <strong>¿Qué sigue?</strong> Nuestro equipo ya tiene agendado tu pedido para prepararlo fresco. Recuerda presentarte en la sucursal de TWINS Bakery el día y hora indicados con tu código <strong>{codigo}</strong> para retirar tu pedido y cancelar el saldo restante.
        </p>
      </div>

      <p style="margin:25px 0 0; font-size:15px; color:#4a5568;">
        ¡Muchas gracias por tu preferencia!<br>
        <strong>El equipo de TWINS Bakery 💗</strong>
      </p>
    """

    cuerpo_texto = f"""¡Tu reserva ha sido aceptada! 🎉

Hola {nombre_seguro},

Nos complace informarte que tu reserva con código {codigo} ha sido ACEPTADA y CONFIRMADA por el administrador de TWINS Bakery.

Detalles de la reserva:
- Código: {codigo}
- Producto: {nombre_producto}
- Cantidad: {cantidad}
- Total: ${total_f:.2f} USD
- Anticipo registrado: ${pagado_f:.2f} USD
- Saldo restante al retirar: ${saldo_restante:.2f} USD
- Fecha y hora programada de entrega: {fecha_retiro_str}

Tu pedido ya está agendado para su preparación. Te esperamos en la sucursal en la fecha indicada con tu código de reserva.

¡Gracias por elegir TWINS Bakery! 💗
"""

    html_completo = _plantilla_base_html(f"Reserva {codigo} Aceptada", "Reserva Aceptada por el Administrador", contenido_html)
    _despachar_asincrono(destinatario, asunto, html_completo, cuerpo_texto)


# ==============================================================================
# 5. NOTIFICACIÓN DE RESERVA LISTA PARA RETIRAR EN EL LOCAL
# ==============================================================================

def enviar_correo_reserva_lista(
    destinatario,
    nombre,
    codigo,
    nombre_producto,
    cantidad,
    total,
    monto_pagado,
    fecha_retiro
):
    """Envía la notificación al cliente avisando que su pedido ya está listo para ser retirado en el local."""
    nombre_seguro = nombre.strip() if nombre else "estimado/a cliente"
    asunto = f"¡Tu pedido está listo para retirar! [Código: {codigo}] - TWINS Bakery 🎂🎉"

    if isinstance(fecha_retiro, datetime):
        fecha_retiro_str = fecha_retiro.strftime("%d/%m/%Y a las %I:%M %p")
    else:
        fecha_retiro_str = str(fecha_retiro)

    total_f = float(total)
    pagado_f = float(monto_pagado)
    saldo_restante = max(0.0, total_f - pagado_f)

    if saldo_restante <= 0.001:
        saldo_html = '<span style="color:#22543d; font-weight:700;">¡Totalmente pagado! ($0.00 USD)</span>'
        saldo_txt = "Totalmente pagado ($0.00 USD)"
    else:
        saldo_html = f'<span style="color:#e05374; font-weight:800; font-size:15px;">${saldo_restante:.2f} USD</span> <span style="font-size:12px; color:#718096;">(cancelar al retirar)</span>'
        saldo_txt = f"${saldo_restante:.2f} USD (a cancelar al retirar en tienda)"

    contenido_html = f"""
      <div style="text-align:center; margin-bottom:20px;">
        <span style="display:inline-block; background-color:#d6bcfa; color:#44337a; font-size:13px; font-weight:800; padding:6px 16px; border-radius:50px; text-transform:uppercase; letter-spacing:1px;">
          ✨ ¡Listo para Retirar!
        </span>
      </div>

      <h2 style="color:#153e49; margin-top:0; font-size:23px; font-weight:800; text-align:center;">
        ¡Tu pedido está listo, {nombre_seguro}! 🎂🎉
      </h2>

      <p style="font-size:15px; color:#4a5568; text-align:center;">
        Nos complace informarte que tu pedido correspondiente a la reserva <strong>{codigo}</strong> para 
        <strong>{nombre_producto}</strong> ya está recién elaborado, empaquetado con amor y 
        <strong style="color:#20b7b2;">listo para que pases a retirarlo al local</strong>.
      </p>

      <div style="background-color:#f0fff4; border:1px solid #9ae6b4; border-radius:12px; padding:20px; margin:25px 0;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="font-size:14px; color:#2d3748;">
          <tr>
            <td style="padding:6px 0; font-weight:600;">🔖 Código de reserva:</td>
            <td style="padding:6px 0; text-align:right; font-weight:800; color:#e05374; font-size:16px;">{codigo}</td>
          </tr>
          <tr>
            <td style="padding:6px 0; font-weight:600;">🍰 Producto:</td>
            <td style="padding:6px 0; text-align:right;">{nombre_producto}</td>
          </tr>
          <tr>
            <td style="padding:6px 0; font-weight:600;">📦 Cantidad:</td>
            <td style="padding:6px 0; text-align:right;">{cantidad} unidad(es)</td>
          </tr>
          <tr>
            <td style="padding:6px 0; font-weight:600;">💵 Total del pedido:</td>
            <td style="padding:6px 0; text-align:right;">${total_f:.2f} USD</td>
          </tr>
          <tr>
            <td style="padding:6px 0; font-weight:600;">💰 Anticipo pagado:</td>
            <td style="padding:6px 0; text-align:right; font-weight:700; color:#38a169;">${pagado_f:.2f} USD</td>
          </tr>
          <tr>
            <td style="padding:6px 0; font-weight:600;">🏷️ Saldo pendiente:</td>
            <td style="padding:6px 0; text-align:right;">{saldo_html}</td>
          </tr>
          <tr style="border-top:1px dashed #cbd5e0;">
            <td style="padding:10px 0 0; font-weight:700; color:#153e49;">📅 Horario programado:</td>
            <td style="padding:10px 0 0; text-align:right; font-weight:800; color:#153e49;">{fecha_retiro_str}</td>
          </tr>
        </table>
      </div>

      <div style="background-color:#ebf8ff; border-left:4px solid #3182ce; border-radius:8px; padding:15px; margin:22px 0;">
        <p style="margin:0; font-size:14px; color:#2b6cb0;">
          📍 <strong>Instrucciones para retirar tu pedido:</strong><br>
          • Pasa por nuestro local de <strong>TWINS Bakery</strong>.<br>
          • Presenta tu código de reserva: <strong>{codigo}</strong>.<br>
          • Si tienes saldo pendiente ({saldo_txt}), podrás cancelarlo al retirar en efectivo o con tarjeta.<br>
          • ¡Te entregaremos tu pedido fresco y listo para celebrar!
        </p>
      </div>

      <p style="margin:25px 0 0; font-size:15px; color:#4a5568;">
        ¡Muchísimas gracias por confiar en TWINS Bakery!<br>
        <strong>El equipo de TWINS Bakery 💗</strong>
      </p>
    """

    cuerpo_texto = f"""¡Tu pedido está listo para retirar! 🎂🎉

Hola {nombre_seguro},

Nos complace informarte que tu pedido correspondiente a la reserva con código {codigo} ({nombre_producto}) ya está completamente preparado y listo para retirar en nuestro local de TWINS Bakery.

Detalles de tu pedido:
- Código de reserva: {codigo}
- Producto: {nombre_producto}
- Cantidad: {cantidad} unidad(es)
- Total: ${total_f:.2f} USD
- Anticipo registrado: ${pagado_f:.2f} USD
- Saldo pendiente al retirar: {saldo_txt}
- Fecha y horario programado: {fecha_retiro_str}

Instrucciones para retirar:
1. Pasa por nuestro local de TWINS Bakery.
2. Presenta tu código de reserva ({codigo}) en recepción.
3. Si tienes saldo pendiente, lo abonas al recibir tu pastel.

¡Esperamos que disfrutes de tu pedido!
El equipo de TWINS Bakery 💗
"""

    html_completo = _plantilla_base_html(f"¡Pedido {codigo} Listo!", "Tu pedido está listo en TWINS Bakery", contenido_html)
    _despachar_asincrono(destinatario, asunto, html_completo, cuerpo_texto)
