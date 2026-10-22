from flask import Blueprint, request, jsonify
from config import get_connection
from datetime import date, datetime, timedelta
import random
import string
import re
import bcrypt

fichas = Blueprint('fichas', __name__)


def _generar_codigo_ficha(fecha_str):
    """
    Genera un código único de ficha con formato HC-YYYYMMDD-XXXXXX.
    XXXXXX = 6 caracteres alfanuméricos en mayúsculas (A-Z, 0-9).
    Excluye caracteres ambiguos: O, 0, I, 1, L.
    """
    chars = [c for c in (string.ascii_uppercase + string.digits)
             if c not in ('O', '0', 'I', '1', 'L')]
    sufijo = ''.join(random.choices(chars, k=6))
    # fecha_str esperado: 'YYYY-MM-DD'
    fecha_compact = fecha_str.replace('-', '') if fecha_str else datetime.today().strftime('%Y%m%d')
    return f"HC-{fecha_compact}-{sufijo}"


# ══════════════════════════════════════════════════════════════
# GET /api/especialidades_disponibles
# Retorna todas las especialidades que tienen cupos futuros
# ══════════════════════════════════════════════════════════════
@fichas.route('/especialidades_disponibles', methods=['GET'])
def especialidades_disponibles():
    conn   = None
    cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT DISTINCT
                e.id_especialidad,
                e.nombre,
                e.descripcion
            FROM especialidades e
            JOIN cupos c ON c.id_especialidad = e.id_especialidad
            WHERE c.fecha >= CURDATE()
              AND (c.cantidad_maxima - c.cantidad_reservada) > 0
            ORDER BY e.nombre
        """)
        especialidades = cursor.fetchall()

        return jsonify({"success": True, "especialidades": especialidades}), 200

    except Exception as e:
        print(f"[ESP ERROR] {e}")
        return jsonify({"success": False, "message": "Error al obtener especialidades."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# GET /api/cupos_disponibles/<id_especialidad>
# Retorna cupos futuros con libres > 0 para una especialidad
# ══════════════════════════════════════════════════════════════
@fichas.route('/cupos_disponibles/<int:id_especialidad>', methods=['GET'])
def cupos_disponibles(id_especialidad):
    conn   = None
    cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                c.id_cupo,
                c.id_especialidad,
                c.fecha,
                c.cantidad_maxima,
                c.cantidad_reservada,
                (c.cantidad_maxima - c.cantidad_reservada) AS cupos_libres
            FROM cupos c
            WHERE c.id_especialidad = %s
              AND c.fecha >= CURDATE()
            ORDER BY c.fecha ASC
            LIMIT 14
        """, (id_especialidad,))

        cupos = cursor.fetchall()

        # Convertir date a string para JSON
        for c in cupos:
            if isinstance(c.get('fecha'), date):
                c['fecha'] = c['fecha'].isoformat()

        return jsonify({"success": True, "cupos": cupos}), 200

    except Exception as e:
        print(f"[CUPOS ERROR] {e}")
        return jsonify({"success": False, "message": "Error al obtener cupos."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# GET /api/medico_especialidad/<id_especialidad>
# Retorna el médico activo asignado a esa especialidad
# ══════════════════════════════════════════════════════════════
@fichas.route('/medico_especialidad/<int:id_especialidad>', methods=['GET'])
def medico_especialidad(id_especialidad):
    conn   = None
    cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        cursor.execute("""
            SELECT
                m.id_medico,
                m.nombre,
                m.apellido_paterno,
                m.apellido_materno,
                m.email
            FROM medicos m
            JOIN medico_especialidad me ON me.id_medico = m.id_medico
            WHERE me.id_especialidad = %s
              AND m.estado = 'activo'
            LIMIT 1
        """, (id_especialidad,))

        medico = cursor.fetchone()

        return jsonify({"success": True, "medico": medico}), 200

    except Exception as e:
        print(f"[MEDICO ESP ERROR] {e}")
        return jsonify({"success": False, "message": "Error al obtener médico."}), 500
    finally:
        if cursor: cursor.close()
        if conn:   conn.close()


# ══════════════════════════════════════════════════════════════
# POST /api/reservar_ficha_sin_cuenta
# Reserva una ficha para un paciente sin usuario registrado.
# Si el CI ya existe en pacientes, reutiliza ese registro.
# ══════════════════════════════════════════════════════════════
@fichas.route('/reservar_ficha_sin_cuenta', methods=['POST'])
def reservar_ficha_sin_cuenta():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"success": False, "message": "Solicitud inválida."}), 400

    # Campos requeridos
    ci               = (data.get('ci') or '').strip()
    nombre           = (data.get('nombre') or '').strip().title()
    apellido_paterno = (data.get('apellido_paterno') or '').strip().title()
    apellido_materno = (data.get('apellido_materno') or '').strip().title()
    telefono         = (data.get('telefono') or '').strip()
    id_especialidad  = data.get('id_especialidad')
    id_cupo          = data.get('id_cupo')
    fecha            = data.get('fecha')

    if not all([ci, nombre, apellido_paterno, apellido_materno,
                telefono, id_especialidad, id_cupo, fecha]):
        return jsonify({"success": False, "message": "Completa todos los campos."}), 400

    conn   = None
    cursor = None
    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)

        # 1. Verificar que el cupo exista y tenga espacio (con lock)
        cursor.execute("""
            SELECT id_cupo, cantidad_maxima, cantidad_reservada
            FROM cupos
            WHERE id_cupo = %s AND fecha = %s AND id_especialidad = %s
            FOR UPDATE
        """, (id_cupo, fecha, id_especialidad))

        cupo = cursor.fetchone()

        if not cupo:
            return jsonify({"success": False, "message": "El cupo seleccionado no existe."}), 404

        libres = cupo['cantidad_maxima'] - cupo['cantidad_reservada']
        if libres <= 0:
            return jsonify({"success": False,
                            "message": "Lo sentimos, el cupo se agotó. Elige otra fecha."}), 409

        # 2. Buscar o crear paciente por CI
        cursor.execute("""
            SELECT id_paciente, nombre, apellido_paterno
            FROM pacientes WHERE ci = %s
        """, (ci,))
        paciente = cursor.fetchone()

        credenciales_nuevas = None  # se llena solo si se crea cuenta nueva

        if not paciente:
            # Crear nuevo paciente sin cuenta
            # fecha_nacimiento y direccion son NOT NULL en BD,
            # usamos valores por defecto para paciente sin cuenta completa
            cursor.execute("""
                INSERT INTO pacientes
                    (ci, nombre, apellido_paterno, apellido_materno,
                     telefono, fecha_nacimiento, direccion)
                VALUES (%s, %s, %s, %s, %s, '1900-01-01', 'No registrada')
            """, (ci, nombre, apellido_paterno, apellido_materno, telefono))
            id_paciente = cursor.lastrowid

            # 2b. Crear cuenta autogenerada: usuario = CI, contraseña = celular (solo dígitos)
            cursor.execute("SELECT id_usuario FROM usuarios WHERE ci = %s LIMIT 1", (ci,))
            if not cursor.fetchone():
                telefono_limpio = re.sub(r'\D', '', telefono)  # solo dígitos
                if telefono_limpio:
                    cursor.execute(
                        "SELECT id_rol FROM roles WHERE nombre = 'paciente' LIMIT 1"
                    )
                    rol_paciente = cursor.fetchone()
                    if rol_paciente:
                        password_hash = bcrypt.hashpw(
                            telefono_limpio.encode('utf-8'), bcrypt.gensalt()
                        ).decode('utf-8')
                        cursor.execute("""
                            INSERT INTO usuarios
                                (ci, password, id_rol, id_paciente, estado,
                                 perfil_completo, cuenta_autogenerada)
                            VALUES (%s, %s, %s, %s, 'activo', FALSE, TRUE)
                        """, (ci, password_hash, rol_paciente["id_rol"], id_paciente))
                        credenciales_nuevas = {
                            "usuario":     ci,
                            "contrasena":  telefono_limpio
                        }
        else:
            id_paciente = paciente['id_paciente']

        # 3. Obtener médico desde la agenda aprobada para esa fecha/especialidad
        #    Si no hay agenda aprobada, buscar cualquier médico activo como fallback
        cursor.execute("""
            SELECT ag.id_medico
            FROM agenda_medico ag
            WHERE ag.id_especialidad = %s
              AND ag.fecha = %s
              AND ag.estado = 'aprobada'
            ORDER BY ag.hora_inicio ASC
            LIMIT 1
        """, (id_especialidad, fecha))
        med = cursor.fetchone()
        if not med:
            # Fallback: primer médico activo de la especialidad
            cursor.execute("""
                SELECT m.id_medico
                FROM medicos m
                JOIN medico_especialidad me ON me.id_medico = m.id_medico
                WHERE me.id_especialidad = %s AND m.estado = 'activo'
                LIMIT 1
            """, (id_especialidad,))
            med = cursor.fetchone()
        id_medico = med['id_medico'] if med else None

        # Validar máximo 1 ficha pendiente por día para este paciente
        cursor.execute("""
            SELECT COUNT(*) AS total FROM fichas f
            JOIN estados_ficha ef ON ef.id_estado = f.id_estado
            WHERE f.id_paciente = %s AND f.fecha = %s
              AND LOWER(ef.nombre) = 'pendiente'
        """, (id_paciente, fecha))
        if cursor.fetchone()["total"] > 0:
            return jsonify({"success": False,
                            "message": "Ya tienes una ficha pendiente para esa fecha."}), 400

        # 4. Obtener estado "pendiente" (o el primero disponible)
        cursor.execute("""
            SELECT id_estado FROM estados_ficha
            WHERE nombre = 'pendiente'
            LIMIT 1
        """)
        estado = cursor.fetchone()
        if not estado:
            # Si no existe, tomar el primer estado
            cursor.execute("SELECT id_estado FROM estados_ficha LIMIT 1")
            estado = cursor.fetchone()
        if not estado:
            return jsonify({"success": False,
                            "message": "No hay estados de ficha configurados."}), 500
        id_estado = estado['id_estado']

        # 5. Calcular número de turno
        numero_turno = cupo['cantidad_reservada'] + 1

        # 5b. Calcular hora estimada de atención desde agenda aprobada
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
                # MySQL TIME puede llegar como timedelta
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

        # 6. Generar código único de ficha (con reintento si colisiona)
        codigo_ficha = None
        for _ in range(5):
            candidato = _generar_codigo_ficha(fecha)
            cursor.execute("SELECT id_ficha FROM fichas WHERE codigo_ficha = %s", (candidato,))
            if not cursor.fetchone():
                codigo_ficha = candidato
                break
        if not codigo_ficha:
            # Fallback extremo: usar timestamp + id_paciente
            codigo_ficha = f"HC-{datetime.now().strftime('%Y%m%d%H%M%S')}-{id_paciente}"

        # 7. Insertar ficha (con fecha límite de confirmación: 24h antes de la cita)
        cursor.execute("""
            INSERT INTO fichas
                (id_paciente, id_especialidad, id_medico, fecha, numero_turno,
                 id_estado, codigo_ficha, fecha_limite_confirmacion)
            VALUES (%s, %s, %s, %s, %s, %s, %s,
                    DATE_SUB(CONCAT(%s, ' 00:00:00'), INTERVAL 24 HOUR))
        """, (id_paciente, id_especialidad, id_medico, fecha, numero_turno,
              id_estado, codigo_ficha, fecha))

        # 7b. Incrementar cupos reservados (tabla cupos)
        cursor.execute("""
            UPDATE cupos
            SET cantidad_reservada = cantidad_reservada + 1
            WHERE id_cupo = %s
        """, (id_cupo,))

        # 7c. Incrementar cupos_ocupados en agenda_medico (BUG corregido:
        #     antes solo se actualizaba 'cupos' y Mi Agenda nunca lo reflejaba)
        cursor.execute("""
            UPDATE agenda_medico
            SET cupos_ocupados = cupos_ocupados + 1
            WHERE id_especialidad = %s AND fecha = %s AND estado = 'aprobada'
        """, (id_especialidad, fecha))

        conn.commit()

        respuesta = {
            "success":           True,
            "message":           "Ficha reservada exitosamente.",
            "numero_turno":      numero_turno,
            "nombre":            f"{nombre} {apellido_paterno} {apellido_materno}",
            "fecha":             fecha,
            "id_ficha":          cursor.lastrowid,
            "codigo_ficha":      codigo_ficha,
            "hora_estimada":     hora_estimada_str,
            "tiempo_promedio":   tiempo_promedio_min
        }
        if credenciales_nuevas:
            respuesta["credenciales_nuevas"] = credenciales_nuevas

        return jsonify(respuesta), 201

    except Exception as e:
        if conn: conn.rollback()
        import traceback
        traceback.print_exc()
        print(f"[RESERVA ERROR] {e}")
        return jsonify({"success": False,
                        "message": str(e)}), 500