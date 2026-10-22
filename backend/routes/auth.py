from flask import Blueprint, request, jsonify
from config import get_connection, JWT_SECRET_KEY, JWT_EXPIRES_MIN
import bcrypt
import jwt
import datetime

auth = Blueprint('auth', __name__)

MAX_INTENTOS = 3


def _es_hash_bcrypt(valor):
    return isinstance(valor, str) and valor.startswith(("$2b$", "$2a$", "$2y$"))


def _verificar_password(password_ingresada, valor_bd):
    if _es_hash_bcrypt(valor_bd):
        es_valida = bcrypt.checkpw(
            password_ingresada.encode('utf-8'),
            valor_bd.encode('utf-8')
        )
        return es_valida, False
    else:
        es_valida = (password_ingresada == valor_bd)
        return es_valida, es_valida


def _registrar_auditoria(cursor, id_usuario, accion, ip):
    try:
        cursor.execute("""
            INSERT INTO auditoria (id_usuario, accion, fecha)
            VALUES (%s, %s, NOW())
        """, (id_usuario, f"{accion} ip={ip}"))
    except Exception as e:
        print(f"[AUDITORIA WARN] {e}")


@auth.route('/login', methods=['POST'])
def login():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "message": "Solicitud inválida."}), 400

    identificador = (data.get('email') or data.get('identificador') or '').strip()
    password      = (data.get('password') or '').strip()
    ip            = request.remote_addr or 'desconocida'

    if not identificador or not password:
        return jsonify({"success": False, "message": "Completa todos los campos."}), 400

    # Login universal: si contiene '@' se busca por email, si no, por CI
    es_email = '@' in identificador

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        if es_email:
            cursor.execute("""
                SELECT u.id_usuario,
                       u.email,
                       u.password,
                       u.estado,
                       u.bloqueado,
                       u.intentos_fallidos,
                       u.perfil_completo,
                       u.cuenta_autogenerada,
                       r.nombre AS rol
                FROM usuarios u
                JOIN roles r ON u.id_rol = r.id_rol
                WHERE LOWER(u.email) = %s
                LIMIT 1
            """, (identificador.lower(),))
        else:
            cursor.execute("""
                SELECT u.id_usuario,
                       u.email,
                       u.password,
                       u.estado,
                       u.bloqueado,
                       u.intentos_fallidos,
                       u.perfil_completo,
                       u.cuenta_autogenerada,
                       r.nombre AS rol
                FROM usuarios u
                JOIN roles r ON u.id_rol = r.id_rol
                WHERE u.ci = %s
                LIMIT 1
            """, (identificador,))

        user = cursor.fetchone()

        if not user:
            return jsonify({"success": False, "message": "Credenciales incorrectas."}), 401

        if user["estado"] != "activo":
            return jsonify({
                "success": False,
                "message": "Tu cuenta está inactiva. Contacta al administrador."
            }), 403

        if user["bloqueado"]:
            return jsonify({
                "success": False,
                "message": "Cuenta bloqueada. Usa '¿Olvidaste tu contraseña?' para recuperarla."
            }), 403

        es_valida, necesita_migrar = _verificar_password(password, user["password"])

        if not es_valida:
            intentos = user["intentos_fallidos"] + 1
            if intentos >= MAX_INTENTOS:
                cursor.execute("""
                    UPDATE usuarios
                    SET intentos_fallidos = %s, bloqueado = TRUE, fecha_bloqueo = NOW()
                    WHERE id_usuario = %s
                """, (intentos, user["id_usuario"]))
                _registrar_auditoria(cursor, user["id_usuario"], "BLOQUEADO", ip)
                conn.commit()
                return jsonify({
                    "success": False,
                    "message": "Cuenta bloqueada por demasiados intentos fallidos."
                }), 403
            else:
                cursor.execute("""
                    UPDATE usuarios SET intentos_fallidos = %s WHERE id_usuario = %s
                """, (intentos, user["id_usuario"]))
                _registrar_auditoria(cursor, user["id_usuario"], "INTENTO_FALLIDO", ip)
                conn.commit()
                restantes = MAX_INTENTOS - intentos
                return jsonify({
                    "success": False,
                    "message": f"Credenciales incorrectas. "
                               f"Te {'queda' if restantes == 1 else 'quedan'} "
                               f"{restantes} intento{'s' if restantes > 1 else ''}."
                }), 401

        # Login correcto
        if necesita_migrar:
            nuevo_hash = bcrypt.hashpw(
                password.encode('utf-8'), bcrypt.gensalt()
            ).decode('utf-8')
            cursor.execute("""
                UPDATE usuarios
                SET password = %s, intentos_fallidos = 0, ultimo_acceso = NOW()
                WHERE id_usuario = %s
            """, (nuevo_hash, user["id_usuario"]))
        else:
            cursor.execute("""
                UPDATE usuarios
                SET intentos_fallidos = 0, ultimo_acceso = NOW()
                WHERE id_usuario = %s
            """, (user["id_usuario"],))

        _registrar_auditoria(cursor, user["id_usuario"], "LOGIN_OK", ip)
        conn.commit()

        # Generar JWT usando la clave centralizada
        payload = {
            "sub":   str(user["id_usuario"]),  # PyJWT 2.x exige string
            "email": user["email"],
            "rol":   user["rol"],
            "iat":   datetime.datetime.utcnow(),
            "exp":   datetime.datetime.utcnow() + datetime.timedelta(minutes=JWT_EXPIRES_MIN)
        }
        token = jwt.encode(payload, JWT_SECRET_KEY, algorithm="HS256")

        return jsonify({
            "success": True,
            "token":   token,
            "user": {
                "id_usuario":         user["id_usuario"],
                "email":              user["email"],
                "rol":                user["rol"],
                "perfil_completo":    bool(user["perfil_completo"]),
                "cuenta_autogenerada": bool(user.get("cuenta_autogenerada"))
            }
        }), 200

    except Exception as e:
        print(f"[AUTH ERROR] {e}")
        return jsonify({"success": False, "message": "Error interno del servidor."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()