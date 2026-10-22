from flask import Blueprint, request, jsonify
from config import get_connection
from datetime import date, datetime, timedelta
from config import get_connection, JWT_SECRET_KEY as SECRET_KEY
import jwt
import os
import random
import re
import string

paciente_bp = Blueprint('paciente', __name__)

# ── Helpers de validación ────────────────────────────────────
_REGEX_CI       = re.compile(r'^\d{6,9}$')
_REGEX_TELEFONO = re.compile(r'^[67]\d{7}$')
_REGEX_NOMBRE   = re.compile(r'^[A-Za-záéíóúÁÉÍÓÚüÜñÑ\s]{2,}$')

_PALABRAS_OBSCENAS = [
    "puta","puto","mierda","cojudo","idiota","imbecil","imbécil",
    "pendejo","culero","cabrón","cabron","hdp","concha","carajo",
    "joder","marica","maricón","maricon","weon","huevon","huevón",
    "coño","cono","chinga","chingada","perra","perro","bastardo",
    "mamona","mamón","mamon","zorra","zorro","estupido","estúpido",
]

def _normalizar(texto):
    import unicodedata
    return unicodedata.normalize('NFD', texto.lower()).encode('ascii', 'ignore').decode('ascii')

def _contiene_obscenidad(texto):
    t = _normalizar(texto)
    return any(_normalizar(p) in t for p in _PALABRAS_OBSCENAS)

def _validar_nombre(valor, campo="Nombre"):
    """Retorna None si OK, string con mensaje de error si falla."""
    if not _REGEX_NOMBRE.match(valor):
        return f"{campo} solo debe contener letras (mínimo 2 caracteres)."
    if _contiene_obscenidad(valor):
        return f"{campo} contiene palabras no permitidas."
    return None


def _generar_codigo_ficha(fecha_str):
    """
    Genera un código único: HC-YYYYMMDD-XXXXXX
    XXXXXX = 6 chars alfanuméricos mayúsculas sin ambiguos (O,0,I,1,L).
    """
    chars = [c for c in (string.ascii_uppercase + string.digits)
             if c not in ('O', '0', 'I', '1', 'L')]
    sufijo = ''.join(random.choices(chars, k=6))
    fecha_compact = fecha_str.replace('-', '') if fecha_str else datetime.today().strftime('%Y%m%d')
    return f"HC-{fecha_compact}-{sufijo}"



# ── Helper: obtener id_usuario del token ───────────────────
def get_id_usuario():
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    try:
        token   = auth.split(" ")[1]
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload.get("sub")
    except Exception:
        return None


def fecha_str(d):
    return d.isoformat() if isinstance(d, (date, datetime)) else d


# ══════════════════════════════════════════════════════════════
# GET /api/paciente/perfil
# ══════════════════════════════════════════════════════════════
@paciente_bp.route('/paciente/perfil', methods=['GET'])
def perfil():
    id_usuario = get_id_usuario()
    if not id_usuario:
        return jsonify({"success": False, "message": "No autorizado."}), 401

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT p.id_paciente, p.ci, p.nombre, p.apellido_paterno,
                   p.apellido_materno, p.telefono, p.fecha_nacimiento, p.direccion,
                   u.cuenta_autogenerada
            FROM   usuarios u
            JOIN   pacientes p ON p.id_paciente = u.id_paciente
            WHERE  u.id_usuario = %s
        """, (id_usuario,))
        paciente = cursor.fetchone()

        if not paciente:
            return jsonify({"success": False, "message": "Perfil no encontrado."}), 404

        if paciente.get("fecha_nacimiento"):
            paciente["fecha_nacimiento"] = fecha_str(paciente["fecha_nacimiento"])
        paciente["cuenta_autogenerada"] = bool(paciente.get("cuenta_autogenerada"))

        return jsonify({"success": True, "paciente": paciente}), 200

    except Exception as e:
        print(f"[PERFIL ERROR] {e}")
        return jsonify({"success": False, "message": "Error interno."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# PUT /api/paciente/perfil
# Actualiza datos del paciente. CI siempre bloqueado.
# Teléfono bloqueado solo para cuentas autogeneradas
# (es su contraseña de login).
# ══════════════════════════════════════════════════════════════
@paciente_bp.route('/paciente/perfil', methods=['PUT'])
def actualizar_perfil():
    id_usuario = get_id_usuario()
    if not id_usuario:
        return jsonify({"success": False, "message": "No autorizado."}), 401

    data = request.get_json(silent=True) or {}

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT u.id_paciente, u.cuenta_autogenerada
            FROM usuarios u WHERE u.id_usuario = %s
        """, (id_usuario,))
        u = cursor.fetchone()
        if not u:
            return jsonify({"success": False, "message": "Perfil no encontrado."}), 404

        es_autogenerada = bool(u.get("cuenta_autogenerada"))
        id_paciente = u["id_paciente"]

        # CI nunca es editable desde este endpoint, se ignora si llega
        nombre            = (data.get("nombre") or "").strip().title()
        apellido_paterno  = (data.get("apellido_paterno") or "").strip().title()
        apellido_materno  = (data.get("apellido_materno") or "").strip().title()
        direccion         = (data.get("direccion") or "").strip()
        fecha_nacimiento  = data.get("fecha_nacimiento") or None
        telefono          = (data.get("telefono") or "").strip()

        if not nombre or not apellido_paterno or not apellido_materno:
            return jsonify({"success": False, "message": "Nombre y apellidos son requeridos."}), 400

        # Validar formato de nombres
        for val, campo in [(nombre, "Nombre"), (apellido_paterno, "Apellido paterno"), (apellido_materno, "Apellido materno")]:
            err = _validar_nombre(val, campo)
            if err:
                return jsonify({"success": False, "message": err}), 400

        # Teléfono bloqueado para cuentas autogeneradas (es su contraseña)
        if es_autogenerada:
            cursor.execute("""
                UPDATE pacientes
                SET nombre = %s, apellido_paterno = %s, apellido_materno = %s,
                    direccion = %s, fecha_nacimiento = COALESCE(%s, fecha_nacimiento)
                WHERE id_paciente = %s
            """, (nombre, apellido_paterno, apellido_materno,
                  direccion, fecha_nacimiento, id_paciente))
        else:
            if not telefono:
                return jsonify({"success": False, "message": "El teléfono es requerido."}), 400
            if not _REGEX_TELEFONO.match(telefono):
                return jsonify({"success": False, "message": "El teléfono debe tener exactamente 8 dígitos y comenzar en 6 o 7."}), 400
            cursor.execute("""
                UPDATE pacientes
                SET nombre = %s, apellido_paterno = %s, apellido_materno = %s,
                    telefono = %s, direccion = %s,
                    fecha_nacimiento = COALESCE(%s, fecha_nacimiento)
                WHERE id_paciente = %s
            """, (nombre, apellido_paterno, apellido_materno,
                  telefono, direccion, fecha_nacimiento, id_paciente))

        cursor.execute("""
            UPDATE usuarios SET perfil_completo = TRUE WHERE id_usuario = %s
        """, (id_usuario,))

        conn.commit()
        return jsonify({"success": True, "message": "Perfil actualizado correctamente."}), 200

    except Exception as e:
        if conn: conn.rollback()
        print(f"[ACTUALIZAR PERFIL ERROR] {e}")
        return jsonify({"success": False, "message": "Error interno."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# GET /api/paciente/stats
# ══════════════════════════════════════════════════════════════
@paciente_bp.route('/paciente/stats', methods=['GET'])
def stats():
    id_usuario = get_id_usuario()
    if not id_usuario:
        return jsonify({"success": False, "message": "No autorizado."}), 401

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        # Obtener id_paciente
        cursor.execute("SELECT id_paciente FROM usuarios WHERE id_usuario = %s", (id_usuario,))
        u = cursor.fetchone()
        if not u:
            return jsonify({"success": False}), 404
        id_paciente = u["id_paciente"]

        # Fichas activas (pendientes)
        cursor.execute("""
            SELECT COUNT(*) AS total FROM fichas f
            JOIN estados_ficha ef ON ef.id_estado = f.id_estado
            WHERE f.id_paciente = %s AND LOWER(ef.nombre) = 'pendiente'
              AND f.es_familiar = FALSE
        """, (id_paciente,))
        fichas_activas = cursor.fetchone()["total"]

        # Fichas atendidas
        cursor.execute("""
            SELECT COUNT(*) AS total FROM fichas f
            JOIN estados_ficha ef ON ef.id_estado = f.id_estado
            WHERE f.id_paciente = %s AND LOWER(ef.nombre) = 'atendido'
              AND f.es_familiar = FALSE
        """, (id_paciente,))
        fichas_atendidas = cursor.fetchone()["total"]

        # Familiares registrados
        cursor.execute("""
            SELECT COUNT(*) AS total FROM paciente_familiar
            WHERE id_paciente_titular = %s
        """, (id_paciente,))
        total_familiares = cursor.fetchone()["total"]

        return jsonify({
            "success":          True,
            "fichas_activas":   fichas_activas,
            "fichas_atendidas": fichas_atendidas,
            "total_familiares": total_familiares
        }), 200

    except Exception as e:
        print(f"[STATS ERROR] {e}")
        return jsonify({"success": False}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# GET /api/paciente/mis_fichas
# Parámetros opcionales: ?estado=pendiente&limite=10
# ══════════════════════════════════════════════════════════════
@paciente_bp.route('/paciente/mis_fichas', methods=['GET'])
def mis_fichas():
    id_usuario = get_id_usuario()
    if not id_usuario:
        return jsonify({"success": False, "message": "No autorizado."}), 401

    estado = request.args.get("estado")
    limite = int(request.args.get("limite", 50))

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT id_paciente FROM usuarios WHERE id_usuario = %s", (id_usuario,))
        u = cursor.fetchone()
        if not u:
            return jsonify({"success": False}), 404
        id_paciente = u["id_paciente"]

        filtro_estado = "AND LOWER(ef.nombre) = %s" if estado else ""
        params = [id_paciente]
        if estado: params.append(estado)
        params.append(limite)

        cursor.execute(f"""
            SELECT
                f.id_ficha, f.codigo_ficha, f.fecha, f.numero_turno, f.cambios_fecha,
                f.confirmada, f.fecha_limite_confirmacion,
                ef.nombre AS estado,
                e.nombre  AS especialidad,
                e.id_especialidad,
                CONCAT('Dr. ', m.nombre, ' ', m.apellido_paterno) AS medico
            FROM fichas f
            JOIN estados_ficha ef   ON ef.id_estado   = f.id_estado
            JOIN especialidades e   ON e.id_especialidad = f.id_especialidad
            LEFT JOIN medicos m     ON m.id_medico = f.id_medico
            WHERE f.id_paciente = %s
              AND (f.es_familiar = FALSE OR f.es_familiar IS NULL)
              {filtro_estado}
            ORDER BY f.fecha DESC
            LIMIT %s
        """, params)

        fichas = cursor.fetchall()
        for f in fichas:
            f["fecha"] = fecha_str(f.get("fecha"))
            f["fecha_registro"] = fecha_str(f.get("fecha_registro"))
            f["confirmada"] = bool(f.get("confirmada"))
            f["fecha_limite_confirmacion"] = fecha_str(f.get("fecha_limite_confirmacion"))

        return jsonify({"success": True, "fichas": fichas}), 200

    except Exception as e:
        print(f"[MIS FICHAS ERROR] {e}")
        return jsonify({"success": False}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# PUT /api/paciente/cancelar_ficha/<id_ficha>
# Solo cancela si: pendiente + más de 24h de anticipación
# ══════════════════════════════════════════════════════════════
@paciente_bp.route('/paciente/cancelar_ficha/<int:id_ficha>', methods=['PUT'])
def cancelar_ficha(id_ficha):
    id_usuario = get_id_usuario()
    if not id_usuario:
        return jsonify({"success": False, "message": "No autorizado."}), 401

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT id_paciente FROM usuarios WHERE id_usuario = %s", (id_usuario,))
        u = cursor.fetchone()
        if not u:
            return jsonify({"success": False}), 404

        # Verificar que la ficha pertenezca al paciente y sea cancelable
        cursor.execute("""
            SELECT f.id_ficha, f.fecha, f.id_especialidad, f.id_cupo,
                   ef.nombre AS estado
            FROM fichas f
            JOIN estados_ficha ef ON ef.id_estado = f.id_estado
            WHERE f.id_ficha = %s AND f.id_paciente = %s
        """, (id_ficha, u["id_paciente"]))

        ficha = cursor.fetchone()
        if not ficha:
            return jsonify({"success": False, "message": "Ficha no encontrada."}), 404

        if ficha["estado"].lower() != "pendiente":
            return jsonify({"success": False,
                            "message": "Solo puedes cancelar fichas pendientes."}), 400

        # Verificar 24h de anticipación
        fecha_ficha = ficha["fecha"]
        if isinstance(fecha_ficha, str):
            fecha_ficha = datetime.strptime(fecha_ficha, "%Y-%m-%d")
        horas_diff = (fecha_ficha - datetime.now()).total_seconds() / 3600

        if horas_diff <= 24:
            return jsonify({"success": False,
                            "message": "Solo puedes cancelar con más de 24 horas de anticipación."}), 400

        # Obtener id_estado cancelado
        cursor.execute("""
            SELECT id_estado FROM estados_ficha WHERE LOWER(nombre) = 'cancelada' LIMIT 1
        """)
        est = cursor.fetchone()
        if not est:
            return jsonify({"success": False, "message": "Estado 'cancelada' no configurado."}), 500

        # Cancelar ficha
        cursor.execute("""
            UPDATE fichas SET id_estado = %s WHERE id_ficha = %s
        """, (est["id_estado"], id_ficha))

        # Liberar cupo (tabla cupos + agenda_medico)
        cursor.execute("""
            UPDATE cupos
            SET cantidad_reservada = GREATEST(cantidad_reservada - 1, 0)
            WHERE id_especialidad = %s AND fecha = %s
        """, (ficha["id_especialidad"], ficha["fecha"]))
        cursor.execute("""
            UPDATE agenda_medico
            SET cupos_ocupados = GREATEST(cupos_ocupados - 1, 0)
            WHERE id_especialidad = %s AND fecha = %s AND estado = 'aprobada'
        """, (ficha["id_especialidad"], ficha["fecha"]))

        conn.commit()
        return jsonify({"success": True, "message": "Ficha cancelada exitosamente."}), 200

    except Exception as e:
        if conn: conn.rollback()
        print(f"[CANCELAR ERROR] {e}")
        return jsonify({"success": False, "message": "Error interno."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# PUT /api/paciente/cambiar_fecha/<id_ficha>
# Reglas: 48h anticipación, máx 1 cambio, no duplicar mismo día
# ══════════════════════════════════════════════════════════════
@paciente_bp.route('/paciente/cambiar_fecha/<int:id_ficha>', methods=['PUT'])
def cambiar_fecha(id_ficha):
    id_usuario = get_id_usuario()
    if not id_usuario:
        return jsonify({"success": False, "message": "No autorizado."}), 401

    data         = request.get_json(silent=True) or {}
    id_cupo_nuevo = data.get("id_cupo_nuevo")
    fecha_nueva  = data.get("fecha_nueva")

    if not id_cupo_nuevo or not fecha_nueva:
        return jsonify({"success": False, "message": "Datos incompletos."}), 400

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT id_paciente FROM usuarios WHERE id_usuario = %s", (id_usuario,))
        u = cursor.fetchone()
        if not u:
            return jsonify({"success": False}), 404
        id_paciente = u["id_paciente"]

        # Obtener ficha actual
        cursor.execute("""
            SELECT f.id_ficha, f.fecha, f.id_especialidad, f.cambios_fecha,
                   ef.nombre AS estado
            FROM fichas f
            JOIN estados_ficha ef ON ef.id_estado = f.id_estado
            WHERE f.id_ficha = %s AND f.id_paciente = %s
        """, (id_ficha, id_paciente))
        ficha = cursor.fetchone()

        if not ficha:
            return jsonify({"success": False, "message": "Ficha no encontrada."}), 404

        if ficha["estado"].lower() != "pendiente":
            return jsonify({"success": False,
                            "message": "Solo puedes cambiar fichas pendientes."}), 400

        if (ficha["cambios_fecha"] or 0) >= 1:
            return jsonify({"success": False,
                            "message": "Ya realizaste el cambio de fecha permitido para esta ficha."}), 400

        # Verificar 48h
        fecha_actual = ficha["fecha"]
        if isinstance(fecha_actual, str):
            fecha_actual = datetime.strptime(fecha_actual, "%Y-%m-%d")
        if (fecha_actual - datetime.now()).total_seconds() / 3600 <= 48:
            return jsonify({"success": False,
                            "message": "Solo puedes cambiar la fecha con 48 horas de anticipación."}), 400

        # No duplicar ficha ese día
        cursor.execute("""
            SELECT COUNT(*) AS total FROM fichas f
            JOIN estados_ficha ef ON ef.id_estado = f.id_estado
            WHERE f.id_paciente = %s AND f.fecha = %s
              AND LOWER(ef.nombre) = 'pendiente' AND f.id_ficha != %s
        """, (id_paciente, fecha_nueva, id_ficha))
        if cursor.fetchone()["total"] > 0:
            return jsonify({"success": False,
                            "message": "Ya tienes una ficha pendiente para esa fecha."}), 400

        # Verificar cupo nuevo
        cursor.execute("""
            SELECT id_cupo, cantidad_maxima, cantidad_reservada, id_especialidad
            FROM cupos WHERE id_cupo = %s AND fecha = %s FOR UPDATE
        """, (id_cupo_nuevo, fecha_nueva))
        cupo = cursor.fetchone()

        if not cupo:
            return jsonify({"success": False, "message": "Cupo no disponible."}), 404
        if cupo["cantidad_maxima"] - cupo["cantidad_reservada"] <= 0:
            return jsonify({"success": False,
                            "message": "El cupo seleccionado se agotó."}), 409

        nuevo_turno = cupo["cantidad_reservada"] + 1

        # Liberar cupo anterior (tabla cupos + agenda_medico)
        cursor.execute("""
            UPDATE cupos
            SET cantidad_reservada = GREATEST(cantidad_reservada - 1, 0)
            WHERE id_especialidad = %s AND fecha = %s
        """, (ficha["id_especialidad"], ficha["fecha"]))
        cursor.execute("""
            UPDATE agenda_medico
            SET cupos_ocupados = GREATEST(cupos_ocupados - 1, 0)
            WHERE id_especialidad = %s AND fecha = %s AND estado = 'aprobada'
        """, (ficha["id_especialidad"], ficha["fecha"]))

        # Actualizar ficha (recalcula también la fecha límite de confirmación)
        cursor.execute("""
            UPDATE fichas
            SET fecha = %s, numero_turno = %s, cambios_fecha = cambios_fecha + 1,
                confirmada = FALSE, fecha_confirmacion = NULL,
                fecha_limite_confirmacion = DATE_SUB(CONCAT(%s, ' 00:00:00'), INTERVAL 24 HOUR)
            WHERE id_ficha = %s
        """, (fecha_nueva, nuevo_turno, fecha_nueva, id_ficha))

        # Reservar cupo nuevo (tabla cupos + agenda_medico)
        cursor.execute("""
            UPDATE cupos SET cantidad_reservada = cantidad_reservada + 1
            WHERE id_cupo = %s
        """, (id_cupo_nuevo,))
        cursor.execute("""
            UPDATE agenda_medico
            SET cupos_ocupados = cupos_ocupados + 1
            WHERE id_especialidad = %s AND fecha = %s AND estado = 'aprobada'
        """, (cupo["id_especialidad"], fecha_nueva))

        conn.commit()
        return jsonify({
            "success":      True,
            "message":      "Fecha cambiada exitosamente.",
            "numero_turno": nuevo_turno,
            "fecha_nueva":  fecha_nueva
        }), 200

    except Exception as e:
        if conn: conn.rollback()
        print(f"[CAMBIAR FECHA ERROR] {e}")
        return jsonify({"success": False, "message": "Error interno."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# POST /api/paciente/reservar_ficha
# Para sí mismo o para un familiar
# ══════════════════════════════════════════════════════════════
@paciente_bp.route('/paciente/reservar_ficha', methods=['POST'])
def reservar_ficha():
    id_usuario = get_id_usuario()
    if not id_usuario:
        return jsonify({"success": False, "message": "No autorizado."}), 401

    data            = request.get_json(silent=True) or {}
    id_especialidad = data.get("id_especialidad")
    id_cupo         = data.get("id_cupo")
    fecha           = data.get("fecha")
    para_quien      = data.get("para_quien", "personal")
    familiar_data   = data.get("familiar")

    # Cuentas autogeneradas (creadas al reservar sin registro previo)
    # no pueden reservar fichas para familiares: el sistema nunca
    # verificó la identidad de quien usa la cuenta.
    if para_quien == "familiar":
        conn_chk = cursor_chk = None
        try:
            conn_chk   = get_connection()
            cursor_chk = conn_chk.cursor(dictionary=True)
            cursor_chk.execute(
                "SELECT cuenta_autogenerada FROM usuarios WHERE id_usuario = %s",
                (id_usuario,)
            )
            u_chk = cursor_chk.fetchone()
            if u_chk and u_chk.get("cuenta_autogenerada"):
                return jsonify({
                    "success": False,
                    "message": "Tu cuenta fue creada automáticamente y solo puede "
                               "reservar fichas para ti mismo. Regístrate con tu "
                               "correo para habilitar la reserva de familiares."
                }), 403
        finally:
            if cursor_chk: cursor_chk.close()
            if conn_chk:   conn_chk.close()

    if not all([id_especialidad, id_cupo, fecha]):
        return jsonify({"success": False, "message": "Datos incompletos."}), 400

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT u.id_paciente, p.ci, p.nombre, p.apellido_paterno
            FROM usuarios u JOIN pacientes p ON p.id_paciente = u.id_paciente
            WHERE u.id_usuario = %s
        """, (id_usuario,))
        u = cursor.fetchone()
        if not u:
            return jsonify({"success": False, "message": "Paciente no encontrado."}), 404

        id_paciente_titular = u["id_paciente"]

        # Verificar cupo (con lock)
        cursor.execute("""
            SELECT id_cupo, cantidad_maxima, cantidad_reservada
            FROM cupos WHERE id_cupo = %s AND fecha = %s FOR UPDATE
        """, (id_cupo, fecha))
        cupo = cursor.fetchone()

        if not cupo:
            return jsonify({"success": False, "message": "Cupo no disponible."}), 404
        if cupo["cantidad_maxima"] - cupo["cantidad_reservada"] <= 0:
            return jsonify({"success": False, "message": "Cupos agotados para esa fecha."}), 409

        # Determinar id_paciente de la ficha
        if para_quien == "personal":
            id_paciente_ficha = id_paciente_titular
            es_familiar       = False

            # No duplicar mismo día
            cursor.execute("""
                SELECT COUNT(*) AS total FROM fichas f
                JOIN estados_ficha ef ON ef.id_estado = f.id_estado
                WHERE f.id_paciente = %s AND f.fecha = %s
                  AND LOWER(ef.nombre) = 'pendiente'
            """, (id_paciente_ficha, fecha))
            if cursor.fetchone()["total"] > 0:
                return jsonify({"success": False,
                                "message": "Ya tienes una ficha pendiente para esa fecha."}), 400

        else:
            # Familiar
            if not familiar_data:
                return jsonify({"success": False, "message": "Datos del familiar requeridos."}), 400

            ci_fam = (familiar_data.get("ci") or "").strip()

            if familiar_data.get("es_nuevo"):
                # Validar campos del familiar antes de insertar
                ci_fam   = (familiar_data.get("ci") or "").strip()
                nom_fam  = (familiar_data.get("nombre") or "").strip()
                ap1_fam  = (familiar_data.get("apellido_paterno") or "").strip()
                ap2_fam  = (familiar_data.get("apellido_materno") or "").strip()
                tel_fam  = (familiar_data.get("telefono") or "").strip()

                if not _REGEX_CI.match(ci_fam):
                    return jsonify({"success": False, "message": "CI del familiar inválido (6 a 9 dígitos)."}), 400
                if not _REGEX_TELEFONO.match(tel_fam):
                    return jsonify({"success": False, "message": "Teléfono del familiar inválido (8 dígitos, empieza en 6 o 7)."}), 400
                for val, campo in [(nom_fam, "Nombre del familiar"), (ap1_fam, "Apellido paterno del familiar"), (ap2_fam, "Apellido materno del familiar")]:
                    err = _validar_nombre(val, campo)
                    if err:
                        return jsonify({"success": False, "message": err}), 400

                # Crear paciente familiar
                cursor.execute("""
                    INSERT INTO pacientes
                        (ci, nombre, apellido_paterno, apellido_materno,
                         telefono, fecha_nacimiento, direccion)
                    VALUES (%s, %s, %s, %s, %s, %s, 'No registrada')
                    ON DUPLICATE KEY UPDATE
                        nombre = VALUES(nombre), telefono = VALUES(telefono)
                """, (
                    ci_fam,
                    familiar_data.get("nombre", "").strip().title(),
                    familiar_data.get("apellido_paterno", "").strip().title(),
                    familiar_data.get("apellido_materno", "").strip().title(),
                    familiar_data.get("telefono", "").strip(),
                    familiar_data.get("fecha_nacimiento", "1990-01-01")
                ))
                id_paciente_ficha = cursor.lastrowid

                # Vincular como familiar si no existe
                cursor.execute("""
                    INSERT IGNORE INTO paciente_familiar
                        (id_paciente_titular, id_paciente_familiar, parentesco)
                    VALUES (%s, %s, %s)
                """, (id_paciente_titular, id_paciente_ficha, familiar_data.get("parentesco", "Familiar")))
            else:
                id_paciente_ficha = familiar_data.get("id_paciente")

            es_familiar = True

            # Misma validación de 1 ficha pendiente por día, también para familiares
            cursor.execute("""
                SELECT COUNT(*) AS total FROM fichas f
                JOIN estados_ficha ef ON ef.id_estado = f.id_estado
                WHERE f.id_paciente = %s AND f.fecha = %s
                  AND LOWER(ef.nombre) = 'pendiente'
            """, (id_paciente_ficha, fecha))
            if cursor.fetchone()["total"] > 0:
                return jsonify({"success": False,
                                "message": "Este familiar ya tiene una ficha pendiente para esa fecha."}), 400

        # Médico de la especialidad
        cursor.execute("""
            SELECT id_medico FROM agenda_medico
            WHERE id_especialidad = %s AND fecha = %s AND estado = 'aprobada'
            LIMIT 1
        """, (id_especialidad, fecha))

        med = cursor.fetchone()
        id_medico = med["id_medico"] if med else None

        # Estado pendiente
        cursor.execute("SELECT id_estado FROM estados_ficha WHERE LOWER(nombre) = 'pendiente' LIMIT 1")
        est = cursor.fetchone()
        if not est:
            cursor.execute("SELECT id_estado FROM estados_ficha LIMIT 1")
            est = cursor.fetchone()
        if not est:
            return jsonify({"success": False, "message": "Estados de ficha no configurados."}), 500

        numero_turno = cupo["cantidad_reservada"] + 1

        # Calcular hora estimada desde agenda aprobada
        hora_estimada_str = None
        tiempo_promedio_min = None
        try:
            cursor.execute("""
                SELECT hora_inicio, hora_fin, cupos_solicitados
                FROM agenda_medico
                WHERE id_especialidad = %s
                  AND fecha = %s
                  AND estado = 'aprobada'
                ORDER BY hora_inicio ASC
                LIMIT 1
            """, (id_especialidad, fecha))
            agenda = cursor.fetchone()
            if agenda and agenda['hora_inicio'] is not None:
                h_ini = agenda['hora_inicio']
                h_fin = agenda['hora_fin']
                if isinstance(h_ini, timedelta):
                    h_ini_dt = datetime(2000, 1, 1) + h_ini
                else:
                    h_ini_dt = datetime.strptime(str(h_ini)[:5], "%H:%M")
                if isinstance(h_fin, timedelta):
                    h_fin_dt = datetime(2000, 1, 1) + h_fin
                else:
                    h_fin_dt = datetime.strptime(str(h_fin)[:5], "%H:%M")
                minutos_totales = int((h_fin_dt - h_ini_dt).seconds / 60)
                cupos_agenda = max(agenda['cupos_solicitados'] or 1, 1)
                tiempo_promedio_min = round(minutos_totales / cupos_agenda)
                minutos_offset = tiempo_promedio_min * (numero_turno - 1)
                hora_estimada_dt = h_ini_dt + timedelta(minutes=minutos_offset)
                hora_estimada_str = hora_estimada_dt.strftime("%H:%M")
        except Exception as e_hora:
            print(f"[HORA ESTIMADA WARN] {e_hora}")

        # Generar código único de ficha (con reintento ante colisión)
        codigo_ficha = None
        for _ in range(5):
            candidato = _generar_codigo_ficha(fecha)
            cursor.execute("SELECT id_ficha FROM fichas WHERE codigo_ficha = %s", (candidato,))
            if not cursor.fetchone():
                codigo_ficha = candidato
                break
        if not codigo_ficha:
            codigo_ficha = f"HC-{datetime.now().strftime('%Y%m%d%H%M%S')}-{id_paciente_ficha}"

        # Insertar ficha (con fecha límite de confirmación: 24h antes de la cita)
        cursor.execute("""
            INSERT INTO fichas
                (id_paciente, id_especialidad, id_medico, fecha,
                 numero_turno, id_estado, es_familiar, id_titular, codigo_ficha,
                 fecha_limite_confirmacion)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                    DATE_SUB(CONCAT(%s, ' 00:00:00'), INTERVAL 24 HOUR))
        """, (id_paciente_ficha, id_especialidad, id_medico, fecha,
              numero_turno, est["id_estado"], es_familiar,
              id_paciente_titular if es_familiar else None,
              codigo_ficha, fecha))

        # Incrementar cupos (tabla cupos)
        cursor.execute("""
            UPDATE cupos SET cantidad_reservada = cantidad_reservada + 1
            WHERE id_cupo = %s
        """, (id_cupo,))

        # Incrementar cupos_ocupados en agenda_medico (BUG corregido:
        # antes solo se actualizaba 'cupos' y Mi Agenda nunca lo reflejaba)
        cursor.execute("""
            UPDATE agenda_medico
            SET cupos_ocupados = cupos_ocupados + 1
            WHERE id_especialidad = %s AND fecha = %s AND estado = 'aprobada'
        """, (id_especialidad, fecha))

        conn.commit()
        return jsonify({
            "success":         True,
            "message":         "Ficha reservada exitosamente.",
            "numero_turno":    numero_turno,
            "codigo_ficha":    codigo_ficha,
            "hora_estimada":   hora_estimada_str,
            "tiempo_promedio": tiempo_promedio_min
        }), 201

    except Exception as e:
        if conn: conn.rollback()
        print(f"[RESERVA CON CUENTA ERROR] {e}")
        return jsonify({"success": False, "message": "Error interno al reservar."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# GET /api/paciente/fichas_familiares
# ══════════════════════════════════════════════════════════════
@paciente_bp.route('/paciente/fichas_familiares', methods=['GET'])
def fichas_familiares():
    id_usuario = get_id_usuario()
    if not id_usuario:
        return jsonify({"success": False, "message": "No autorizado."}), 401

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT id_paciente FROM usuarios WHERE id_usuario = %s", (id_usuario,))
        u = cursor.fetchone()
        if not u:
            return jsonify({"success": False}), 404

        cursor.execute("""
            SELECT
                f.id_ficha, f.fecha, f.numero_turno,
                ef.nombre AS estado,
                e.nombre  AS especialidad,
                CONCAT(p.nombre, ' ', p.apellido_paterno) AS paciente_nombre,
                pf.parentesco
            FROM fichas f
            JOIN estados_ficha ef ON ef.id_estado   = f.id_estado
            JOIN especialidades e ON e.id_especialidad = f.id_especialidad
            JOIN pacientes p      ON p.id_paciente  = f.id_paciente
            LEFT JOIN paciente_familiar pf
                ON pf.id_paciente_familiar = f.id_paciente
               AND pf.id_paciente_titular  = %s
            WHERE f.id_titular = %s AND f.es_familiar = TRUE
            ORDER BY f.fecha DESC
        """, (u["id_paciente"], u["id_paciente"]))

        fichas = cursor.fetchall()
        for f in fichas:
            f["fecha"] = fecha_str(f.get("fecha"))

        return jsonify({"success": True, "fichas": fichas}), 200

    except Exception as e:
        print(f"[FICHAS FAM ERROR] {e}")
        return jsonify({"success": False}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# GET /api/buscar_paciente_ci?ci=xxx
# Busca un paciente por CI (para familiar)
# ══════════════════════════════════════════════════════════════
@paciente_bp.route('/buscar_paciente_ci', methods=['GET'])
def buscar_paciente_ci():
    ci = (request.args.get("ci") or "").strip()
    if not ci:
        return jsonify({"success": False, "message": "CI requerido."}), 400
    if not _REGEX_CI.match(ci):
        return jsonify({"success": False, "message": "CI inválido (6 a 9 dígitos numéricos)."}), 400

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT id_paciente, ci, nombre, apellido_paterno, apellido_materno, telefono
            FROM pacientes WHERE ci = %s
        """, (ci,))
        paciente = cursor.fetchone()

        return jsonify({"success": bool(paciente), "paciente": paciente}), 200

    except Exception as e:
        print(f"[BUSCAR CI ERROR] {e}")
        return jsonify({"success": False}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# POST /api/registro_paciente
# Registro de nuevo paciente con cuenta
# ══════════════════════════════════════════════════════════════
@paciente_bp.route('/registro_paciente', methods=['POST'])
def registro_paciente():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "message": "Solicitud inválida."}), 400

    nombre           = (data.get('nombre') or '').strip().title()
    ap_paterno       = (data.get('apellido_paterno') or '').strip().title()
    ap_materno       = (data.get('apellido_materno') or '').strip().title()
    ci               = (data.get('ci') or '').strip()
    telefono         = (data.get('telefono') or '').strip()
    fecha_nacimiento = (data.get('fecha_nacimiento') or '').strip()
    sexo             = (data.get('sexo') or '').strip().upper()
    direccion        = (data.get('direccion') or 'No registrada').strip()
    email            = (data.get('email') or '').strip().lower()
    password         = (data.get('password') or '').strip()

    # Validaciones básicas — campos presentes
    if not all([nombre, ap_paterno, ap_materno, ci, telefono, fecha_nacimiento, sexo, email, password]):
        return jsonify({"success": False, "message": "Completa todos los campos obligatorios."}), 400

    if sexo not in ('M', 'F'):
        return jsonify({"success": False, "message": "Sexo inválido."}), 400

    # CI: 6 a 9 dígitos
    if not _REGEX_CI.match(ci):
        return jsonify({"success": False, "message": "El CI debe tener entre 6 y 9 dígitos numéricos."}), 400

    # Teléfono: 8 dígitos, empieza en 6 o 7
    if not _REGEX_TELEFONO.match(telefono):
        return jsonify({"success": False, "message": "El teléfono debe tener exactamente 8 dígitos y comenzar en 6 o 7."}), 400

    # Nombres: solo letras, sin obscenidades
    for val, campo in [(nombre, "Nombre"), (ap_paterno, "Apellido paterno"), (ap_materno, "Apellido materno")]:
        err = _validar_nombre(val, campo)
        if err:
            return jsonify({"success": False, "message": err}), 400

    # Validar mayor de 18 años
    try:
        from datetime import date
        nac  = datetime.strptime(fecha_nacimiento, "%Y-%m-%d").date()
        hoy  = date.today()
        edad = hoy.year - nac.year - ((hoy.month, hoy.day) < (nac.month, nac.day))
        if edad < 18:
            return jsonify({"success": False,
                            "message": "Debes ser mayor de 18 años para crear una cuenta."}), 400
    except ValueError:
        return jsonify({"success": False, "message": "Fecha de nacimiento inválida."}), 400

    import bcrypt as _bcrypt
    password_hash = _bcrypt.hashpw(password.encode('utf-8'), _bcrypt.gensalt()).decode('utf-8')

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        # Verificar email duplicado
        cursor.execute("SELECT id_usuario FROM usuarios WHERE email = %s", (email,))
        if cursor.fetchone():
            return jsonify({"success": False, "message": "El correo ya está registrado."}), 409

        # Verificar CI duplicado
        cursor.execute("SELECT id_paciente FROM pacientes WHERE ci = %s", (ci,))
        if cursor.fetchone():
            return jsonify({"success": False, "message": "El CI ya está registrado."}), 409

        # Obtener id_rol paciente
        cursor.execute("SELECT id_rol FROM roles WHERE LOWER(nombre) = 'paciente' LIMIT 1")
        rol = cursor.fetchone()
        if not rol:
            return jsonify({"success": False, "message": "Rol paciente no configurado."}), 500

        # Insertar paciente
        cursor.execute("""
            INSERT INTO pacientes
                (ci, nombre, apellido_paterno, apellido_materno,
                 telefono, fecha_nacimiento, sexo, direccion)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (ci, nombre, ap_paterno, ap_materno, telefono, fecha_nacimiento, sexo, direccion))
        id_paciente = cursor.lastrowid

        # Insertar usuario
        cursor.execute("""
            INSERT INTO usuarios (email, password, id_rol, id_paciente, estado, perfil_completo)
            VALUES (%s, %s, %s, %s, 'activo', TRUE)
        """, (email, password_hash, rol["id_rol"], id_paciente))
        id_usuario = cursor.lastrowid

        conn.commit()

        # Generar token JWT
        payload = {
            "sub":   id_usuario,
            "email": email,
            "rol":   "paciente",
            "iat":   datetime.utcnow(),
            "exp":   datetime.utcnow() + timedelta(minutes=60)
        }
        token = jwt.encode(payload, SECRET_KEY, algorithm="HS256")

        return jsonify({
            "success": True,
            "message": "Cuenta creada exitosamente.",
            "token":   token,
            "user":    {"id": id_usuario, "email": email, "rol": "paciente"}
        }), 201

    except Exception as e:
        if conn: conn.rollback()
        print(f"[REGISTRO ERROR] {e}")
        return jsonify({"success": False, "message": "Error interno del servidor."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# PUT /api/paciente/confirmar_ficha/<id_ficha>
# El paciente confirma su asistencia a una ficha pendiente.
# Disponible hasta 24h antes de la fecha de la cita.
# ══════════════════════════════════════════════════════════════
@paciente_bp.route('/paciente/confirmar_ficha/<int:id_ficha>', methods=['PUT'])
def confirmar_ficha(id_ficha):
    id_usuario = get_id_usuario()
    if not id_usuario:
        return jsonify({"success": False, "message": "No autorizado."}), 401

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT id_paciente FROM usuarios WHERE id_usuario = %s", (id_usuario,))
        u = cursor.fetchone()
        if not u or not u["id_paciente"]:
            return jsonify({"success": False, "message": "Perfil de paciente no encontrado."}), 404

        cursor.execute("""
            SELECT f.id_ficha, f.confirmada, f.fecha_limite_confirmacion,
                   ef.nombre AS estado
            FROM fichas f
            JOIN estados_ficha ef ON ef.id_estado = f.id_estado
            WHERE f.id_ficha = %s AND f.id_paciente = %s LIMIT 1
        """, (id_ficha, u["id_paciente"]))
        ficha = cursor.fetchone()

        if not ficha:
            return jsonify({"success": False, "message": "Ficha no encontrada."}), 404
        if ficha["estado"] != "pendiente":
            return jsonify({"success": False,
                            "message": "Solo puedes confirmar fichas en estado pendiente."}), 400
        if ficha["confirmada"]:
            return jsonify({"success": False, "message": "Esta ficha ya estaba confirmada."}), 400
        if ficha["fecha_limite_confirmacion"] and datetime.now() > ficha["fecha_limite_confirmacion"]:
            return jsonify({"success": False,
                            "message": "El plazo para confirmar esta ficha ya venció."}), 400

        cursor.execute("""
            UPDATE fichas
            SET confirmada = TRUE, fecha_confirmacion = NOW()
            WHERE id_ficha = %s
        """, (id_ficha,))
        conn.commit()

        return jsonify({"success": True, "message": "Asistencia confirmada correctamente."}), 200

    except Exception as e:
        if conn: conn.rollback()
        print(f"[CONFIRMAR FICHA ERROR] {e}")
        return jsonify({"success": False, "message": "Error interno."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# PUT /api/paciente/agregar_correo
# Permite a una cuenta autogenerada (CI + celular) agregar un
# correo y contraseña. El paciente decide si eso reemplaza su
# login (cuenta pasa a "completa") o solo se guarda como dato.
# ══════════════════════════════════════════════════════════════
@paciente_bp.route('/paciente/agregar_correo', methods=['PUT'])
def agregar_correo():
    id_usuario = get_id_usuario()
    if not id_usuario:
        return jsonify({"success": False, "message": "No autorizado."}), 401

    data = request.get_json(silent=True) or {}
    email             = (data.get("email") or "").strip().lower()
    password          = (data.get("password") or "").strip()
    reemplazar_login  = bool(data.get("reemplazar_login", False))

    if not email or "@" not in email:
        return jsonify({"success": False, "message": "Ingresa un correo válido."}), 400

    # La contraseña solo es obligatoria si decide reemplazar su login
    if reemplazar_login and len(password) < 4:
        return jsonify({"success": False,
                        "message": "La contraseña debe tener al menos 4 caracteres."}), 400

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT id_usuario, cuenta_autogenerada FROM usuarios WHERE id_usuario = %s
        """, (id_usuario,))
        u = cursor.fetchone()
        if not u:
            return jsonify({"success": False, "message": "Usuario no encontrado."}), 404
        if not u.get("cuenta_autogenerada"):
            return jsonify({"success": False,
                            "message": "Esta acción es solo para cuentas autogeneradas."}), 400

        # Verificar que el correo no esté usado por otra cuenta
        cursor.execute("SELECT id_usuario FROM usuarios WHERE email = %s AND id_usuario != %s",
                       (email, id_usuario))
        if cursor.fetchone():
            return jsonify({"success": False, "message": "Ese correo ya está en uso."}), 409

        if reemplazar_login:
            import bcrypt as _bcrypt
            password_hash = _bcrypt.hashpw(password.encode('utf-8'), _bcrypt.gensalt()).decode('utf-8')
            # Email + password pasan a ser el login. CI/celular dejan de servir
            # (la columna 'ci' se conserva solo como referencia interna del paciente,
            #  pero el login universal ya no la usará porque cuenta_autogenerada = FALSE)
            cursor.execute("""
                UPDATE usuarios
                SET email = %s, password = %s, cuenta_autogenerada = FALSE,
                    ci = NULL, perfil_completo = TRUE
                WHERE id_usuario = %s
            """, (email, password_hash, id_usuario))
            mensaje = "¡Listo! Ahora puedes iniciar sesión con tu correo y contraseña."
        else:
            # Solo guarda el correo como dato informativo, sin tocar el login
            cursor.execute("""
                UPDATE usuarios SET email = %s WHERE id_usuario = %s
            """, (email, id_usuario))
            mensaje = "Correo guardado. Sigues accediendo con tu CI y celular."

        conn.commit()
        return jsonify({
            "success":            True,
            "message":            mensaje,
            "credenciales_nuevas": {"usuario": email, "contrasena": password} if reemplazar_login else None
        }), 200

    except Exception as e:
        if conn: conn.rollback()
        print(f"[AGREGAR CORREO ERROR] {e}")
        return jsonify({"success": False, "message": "Error interno."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()

# ══════════════════════════════════════════════════════════════
# GET /api/paciente/detalle_consulta/<id_ficha>
# Devuelve los datos completos de una consulta al paciente:
# info de la cita, diagnóstico, tratamiento, observaciones
# y receta con sus items (si existe).
# Solo se puede consultar si la ficha pertenece al paciente.
# ══════════════════════════════════════════════════════════════
@paciente_bp.route('/paciente/detalle_consulta/<int:id_ficha>', methods=['GET'])
def detalle_consulta(id_ficha):
    id_usuario = get_id_usuario()
    if not id_usuario:
        return jsonify({"success": False, "message": "No autorizado."}), 401

    conn = cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        # Obtener id_paciente del token
        cursor.execute("SELECT id_paciente FROM usuarios WHERE id_usuario = %s", (id_usuario,))
        u = cursor.fetchone()
        if not u or not u["id_paciente"]:
            return jsonify({"success": False, "message": "Perfil no encontrado."}), 404
        id_paciente = u["id_paciente"]

        # Datos de la ficha (verificar que pertenece al paciente)
        cursor.execute("""
            SELECT f.id_ficha, f.codigo_ficha, f.fecha, f.numero_turno,
                   ef.nombre AS estado,
                   e.nombre  AS especialidad,
                   CONCAT('Dr. ', m.nombre, ' ', m.apellido_paterno) AS medico
            FROM fichas f
            JOIN estados_ficha ef   ON ef.id_estado     = f.id_estado
            JOIN especialidades e   ON e.id_especialidad = f.id_especialidad
            LEFT JOIN medicos m     ON m.id_medico       = f.id_medico
            WHERE f.id_ficha = %s AND f.id_paciente = %s
            LIMIT 1
        """, (id_ficha, id_paciente))
        ficha = cursor.fetchone()

        if not ficha:
            return jsonify({"success": False, "message": "Ficha no encontrada."}), 404

        if ficha["estado"] not in ("completada", "atendido"):
            return jsonify({"success": False,
                            "message": "Esta ficha aún no tiene consulta registrada."}), 400

        if ficha.get("fecha"):
            ficha["fecha"] = fecha_str(ficha["fecha"])

        # Datos de la consulta vinculada a esa ficha
        cursor.execute("""
            SELECT c.id_consulta, c.motivo_consulta, c.sintomas,
                   c.diagnostico, c.tratamiento, c.observaciones,
                   c.fecha_consulta
            FROM consultas c
            WHERE c.id_ficha = %s AND c.id_paciente = %s
            ORDER BY c.fecha_consulta DESC
            LIMIT 1
        """, (id_ficha, id_paciente))
        consulta = cursor.fetchone()

        if not consulta:
            return jsonify({"success": False,
                            "message": "No se encontró consulta para esta ficha."}), 404

        if consulta.get("fecha_consulta"):
            consulta["fecha_consulta"] = consulta["fecha_consulta"].isoformat()

        # Receta e items (si existe)
        cursor.execute("""
            SELECT r.id_receta, r.indicaciones
            FROM recetas r
            WHERE r.id_consulta = %s
            LIMIT 1
        """, (consulta["id_consulta"],))
        receta = cursor.fetchone()

        items_receta = []
        if receta:
            cursor.execute("""
                SELECT medicamento, dosis, frecuencia, duracion, indicacion
                FROM receta_items
                WHERE id_receta = %s
                ORDER BY id_item ASC
            """, (receta["id_receta"],))
            items_receta = cursor.fetchall()

        return jsonify({
            "success":      True,
            "ficha":        ficha,
            "consulta":     consulta,
            "receta":       receta,
            "items_receta": items_receta
        }), 200

    except Exception as e:
        print(f"[DETALLE CONSULTA ERROR] {e}")
        return jsonify({"success": False, "message": "Error interno."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()