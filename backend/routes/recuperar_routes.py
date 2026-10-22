from flask import Blueprint, request, jsonify
from config import get_connection
import bcrypt
import random
import datetime

recuperar_bp = Blueprint('recuperar', __name__)


def _generar_codigo():
    return str(random.randint(100000, 999999))


import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

GMAIL_USER = "barriosjuan9865@gmail.com"
GMAIL_PASS = "cjiisrfhehcuhsga"


def _simular_envio(destinatario, canal, codigo, nombre='Usuario'):
    """Envío real por Gmail SMTP."""
    print(f"  [RECUPERACIÓN] Enviando código {codigo} a {destinatario} via {canal}")
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Código de recuperación - Hospital de Clínicas"
        msg["From"]    = f"Hospital de Clínicas <{GMAIL_USER}>"
        msg["To"]      = destinatario

        html = f"""
        <div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:32px;background:#f9fafb;border-radius:12px">
            <div style="text-align:center;margin-bottom:24px">
                <div style="display:inline-block;background:#0D1B3E;padding:12px 24px;border-radius:8px">
                    <span style="color:#2DD4BF;font-size:1.2rem;font-weight:bold">✚ Hospital de Clínicas</span>
                </div>
            </div>
            <h2 style="color:#0D1B3E;text-align:center;margin-bottom:8px">Recuperación de contraseña</h2>
            <p style="color:#6b7280;text-align:center;margin-bottom:28px">
                Estimado/a <strong style="color:#0D1B3E">{nombre}</strong>, usá el siguiente código
                para restablecer tu contraseña.<br>
                <strong>Expira en 5 minutos.</strong>
            </p>
            <div style="background:#0D1B3E;border-radius:12px;padding:28px;text-align:center;margin-bottom:24px">
                <p style="color:#9ca3af;font-size:0.8rem;margin:0 0 10px">Tu código de verificación</p>
                <span style="color:#2DD4BF;font-size:2.5rem;font-weight:bold;letter-spacing:12px">{codigo}</span>
            </div>
            <p style="color:#6b7280;font-size:0.85rem;text-align:center;margin-bottom:8px">
                ⏱ Este código expira en <strong>5 minutos</strong>.
            </p>
            <p style="color:#9ca3af;font-size:0.78rem;text-align:center">
                Si no solicitaste este código, ignorá este correo.<br>
                Tu contraseña no será modificada.
            </p>
            <hr style="border:none;border-top:1px solid #e5e7eb;margin:20px 0">
            <p style="color:#d1d5db;font-size:0.72rem;text-align:center">
                Hospital de Clínicas · Sistema de Gestión Médica
            </p>
        </div>
        """

        msg.attach(MIMEText(html, "html"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_PASS)
            server.sendmail(GMAIL_USER, destinatario, msg.as_string())

        print(f"  [RECUPERACIÓN] Correo enviado correctamente a {destinatario}")
    except Exception as e:
        print(f"  [RECUPERACIÓN ERROR SMTP] {e}")
        raise


def _enmascarar_email(email):
    partes = email.split('@')
    if len(partes) == 2:
        return partes[0][:2] + '***@' + partes[1]
    return '***'


def _enmascarar_telefono(telefono):
    t = str(telefono)
    return t[:2] + '****' + t[-2:] if len(t) >= 4 else '****'


# ══════════════════════════════════════════════════════════════
# POST /api/recuperar/solicitar
# Recibe teléfono o email, genera código y lo "envía"
# Solo para pacientes y médicos
# ══════════════════════════════════════════════════════════════
@recuperar_bp.route('/recuperar/solicitar', methods=['POST'])
def solicitar():
    data          = request.get_json(silent=True) or {}
    identificador = (data.get('identificador') or '').strip()

    if not identificador:
        return jsonify({"success": False, "message": "Ingresa tu teléfono o correo."}), 400

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        es_email = '@' in identificador

        if es_email:
            # Buscar por email en usuarios + traer teléfono desde pacientes o medicos
            cursor.execute("""
                SELECT u.id_usuario, u.email, u.estado, u.bloqueado,
                       r.nombre AS rol,
                       COALESCE(p.telefono, m.telefono) AS telefono,
                       COALESCE(p.nombre, m.nombre) AS nombre
                FROM usuarios u
                JOIN roles r ON u.id_rol = r.id_rol
                LEFT JOIN pacientes p ON p.id_paciente = u.id_paciente
                LEFT JOIN medicos   m ON m.id_medico   = u.id_medico
                WHERE LOWER(u.email) = %s
                LIMIT 1
            """, (identificador.lower(),))
        else:
            # Buscar por teléfono en pacientes o medicos
            telefono_limpio = ''.join(filter(str.isdigit, identificador))
            cursor.execute("""
                SELECT u.id_usuario, u.email, u.estado, u.bloqueado,
                       r.nombre AS rol,
                       COALESCE(p.telefono, m.telefono) AS telefono,
                       COALESCE(p.nombre, m.nombre) AS nombre
                FROM usuarios u
                JOIN roles r ON u.id_rol = r.id_rol
                LEFT JOIN pacientes p ON p.id_paciente = u.id_paciente
                LEFT JOIN medicos   m ON m.id_medico   = u.id_medico
                WHERE p.telefono = %s OR m.telefono = %s
                LIMIT 1
            """, (telefono_limpio, telefono_limpio))

        user = cursor.fetchone()

        # Siempre responder "éxito" aunque no exista (evitar enumeración de usuarios)
        if not user:
            return jsonify({
                "success":    True,
                "message":    "Si el dato está registrado, recibirás el código.",
                "destino":    "***",
                "id_usuario": None
            }), 200

        if user.get('rol') not in ('paciente', 'medico'):
            return jsonify({
                "success":    True,
                "message":    "Si el dato está registrado, recibirás el código.",
                "destino":    "***",
                "id_usuario": None
            }), 200

        if user['estado'] != 'activo':
            return jsonify({
                "success": False,
                "message": "Tu cuenta está inactiva. Contacta al administrador."
            }), 403

        # Invalidar códigos anteriores
        cursor.execute("""
            UPDATE recuperacion_password
            SET usado = 1
            WHERE id_usuario = %s AND usado = 0
        """, (user['id_usuario'],))

        # Generar nuevo código
        codigo = _generar_codigo()
        expira = datetime.datetime.now() + datetime.timedelta(minutes=5)

        cursor.execute("""
            INSERT INTO recuperacion_password (id_usuario, codigo, expira_en)
            VALUES (%s, %s, %s)
        """, (user['id_usuario'], codigo, expira))

        conn.commit()

        # Siempre enviar al email registrado (sin importar si ingresó teléfono o email)
        if user.get('email'):
            canal   = "correo electrónico"
            destino = user['email']
            visible = _enmascarar_email(user['email'])
        else:
            # No tiene email registrado — por ahora solo mostrar en consola
            canal   = "consola"
            destino = str(user.get('telefono') or identificador)
            visible = _enmascarar_telefono(destino)

        try:
            _simular_envio(destino, canal, codigo, user.get('nombre', 'Usuario'))
        except Exception as mail_err:
            print(f"  [RECUPERACIÓN WARN] No se pudo enviar: {mail_err}")
            # El código se guardó igual, continuar

        return jsonify({
            "success":    True,
            "message":    "Si el dato está registrado, recibirás el código.",
            "destino":    visible,
            "canal":      canal,
            "id_usuario": user['id_usuario']
        }), 200

    except Exception as e:
        print(f"[RECUPERAR SOLICITAR ERROR] {e}")
        return jsonify({"success": False, "message": "Error interno."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# POST /api/recuperar/verificar
# ══════════════════════════════════════════════════════════════
@recuperar_bp.route('/recuperar/verificar', methods=['POST'])
def verificar():
    data       = request.get_json(silent=True) or {}
    id_usuario = data.get('id_usuario')
    codigo     = (data.get('codigo') or '').strip()

    if not id_usuario or not codigo:
        return jsonify({"success": False, "message": "Datos incompletos."}), 400

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT id, expira_en
            FROM recuperacion_password
            WHERE id_usuario = %s AND codigo = %s AND usado = 0
            ORDER BY creado_en DESC
            LIMIT 1
        """, (id_usuario, codigo))

        registro = cursor.fetchone()

        if not registro:
            return jsonify({"success": False, "message": "Código incorrecto."}), 400

        if datetime.datetime.now() > registro['expira_en']:
            return jsonify({"success": False, "message": "El código expiró. Solicitá uno nuevo."}), 400

        return jsonify({"success": True, "id_recuperacion": registro['id']}), 200

    except Exception as e:
        print(f"[RECUPERAR VERIFICAR ERROR] {e}")
        return jsonify({"success": False, "message": "Error interno."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# POST /api/recuperar/nueva_password
# ══════════════════════════════════════════════════════════════
@recuperar_bp.route('/recuperar/nueva_password', methods=['POST'])
def nueva_password():
    data            = request.get_json(silent=True) or {}
    id_usuario      = data.get('id_usuario')
    id_recuperacion = data.get('id_recuperacion')
    password        = (data.get('password') or '').strip()
    password2       = (data.get('password2') or '').strip()

    if not all([id_usuario, id_recuperacion, password, password2]):
        return jsonify({"success": False, "message": "Datos incompletos."}), 400

    if password != password2:
        return jsonify({"success": False, "message": "Las contraseñas no coinciden."}), 400

    if len(password) < 8:
        return jsonify({"success": False, "message": "La contraseña debe tener al menos 8 caracteres."}), 400

    if not any(c.isupper() for c in password):
        return jsonify({"success": False, "message": "Debe incluir al menos una mayúscula."}), 400

    if not any(c.isdigit() for c in password):
        return jsonify({"success": False, "message": "Debe incluir al menos un número."}), 400

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT id FROM recuperacion_password
            WHERE id = %s AND id_usuario = %s AND usado = 0
            LIMIT 1
        """, (id_recuperacion, id_usuario))

        if not cursor.fetchone():
            return jsonify({"success": False, "message": "Sesión de recuperación inválida."}), 400

        nuevo_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        cursor.execute("""
            UPDATE usuarios
            SET password = %s,
                intentos_fallidos = 0,
                bloqueado = 0,
                fecha_bloqueo = NULL
            WHERE id_usuario = %s
        """, (nuevo_hash, id_usuario))

        cursor.execute("""
            UPDATE recuperacion_password SET usado = 1 WHERE id = %s
        """, (id_recuperacion,))

        conn.commit()

        return jsonify({"success": True, "message": "Contraseña actualizada correctamente."}), 200

    except Exception as e:
        print(f"[RECUPERAR NUEVA_PASSWORD ERROR] {e}")
        return jsonify({"success": False, "message": "Error interno."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()