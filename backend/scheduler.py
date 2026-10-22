"""
scheduler.py
══════════════════════════════════════════════════════════════
Configura las tareas automáticas (jobs) que el sistema necesita
ejecutar periódicamente, sin que un usuario tenga que dispararlas
manualmente.

Jobs registrados:
  1. liberar-no-confirmadas  → cada 1 hora
     Cancela fichas pendientes cuyo plazo de 24h para confirmar
     asistencia ya venció, y libera el cupo.

  2. vencer-agendas          → 1 vez al día (madrugada)
     Mueve agendas aprobadas con fecha pasada (+24h de gracia)
     a 'vencida' y calcula sus estadísticas en agenda_historial_stats.

  3. notificar-preasignadas  → 1 vez al día (madrugada)
     Revisa fichas pre-asignadas sin agenda publicada y notifica
     al médico (y al admin desde la 3ra notificación).

Los jobs llaman a los endpoints internos vía HTTP usando requests,
reutilizando exactamente la misma lógica que ya está probada y
protegida con el header X-Job-Key — así no se duplica código de
negocio entre el scheduler y las rutas Flask.
══════════════════════════════════════════════════════════════
"""

import os
import requests
from apscheduler.schedulers.background import BackgroundScheduler

# Debe coincidir con JOB_INTERNAL_KEY usado en los endpoints
# (routes/medico_routes.py). En producción, definir esta variable
# de entorno con un valor secreto real.
JOB_INTERNAL_KEY = os.environ.get("JOB_INTERNAL_KEY", "hospital-job-2026")

# Base URL del propio servidor Flask (mismo proceso/host)
BASE_URL = os.environ.get("INTERNAL_API_URL", "http://127.0.0.1:5000/api")

HEADERS = {"X-Job-Key": JOB_INTERNAL_KEY}


def _llamar_job(nombre_endpoint, nombre_log):
    """Hace POST al endpoint del job y registra el resultado en consola."""
    url = f"{BASE_URL}/medico/job/{nombre_endpoint}"
    try:
        resp = requests.post(url, headers=HEADERS, timeout=30)
        if resp.status_code == 200:
            print(f"[SCHEDULER] ✅ {nombre_log} OK → {resp.json()}")
        else:
            print(f"[SCHEDULER] ⚠️ {nombre_log} respondió {resp.status_code}: {resp.text}")
    except Exception as e:
        print(f"[SCHEDULER] ❌ Error ejecutando {nombre_log}: {e}")


def job_liberar_no_confirmadas():
    _llamar_job("liberar-no-confirmadas", "Liberar fichas no confirmadas")


def job_vencer_agendas():
    _llamar_job("vencer-agendas", "Vencer agendas")


def job_notificar_preasignadas():
    _llamar_job("notificar-preasignadas", "Notificar fichas pre-asignadas")


def iniciar_scheduler():
    """
    Crea y arranca el BackgroundScheduler con los 3 jobs.
    Debe llamarse una sola vez, al iniciar la app (ver app.py).
    """
    scheduler = BackgroundScheduler(timezone="America/La_Paz")

    # Cada hora, en el minuto 0
    scheduler.add_job(
        job_liberar_no_confirmadas,
        trigger="cron",
        minute=0,
        id="liberar_no_confirmadas",
        replace_existing=True
    )

    # 1 vez al día a las 00:30 (después de medianoche, ya es "ayer" oficialmente)
    scheduler.add_job(
        job_vencer_agendas,
        trigger="cron",
        hour=0, minute=30,
        id="vencer_agendas",
        replace_existing=True
    )

    # 1 vez al día a las 7:00 AM (horario hábil, para que el médico la vea pronto)
    scheduler.add_job(
        job_notificar_preasignadas,
        trigger="cron",
        hour=7, minute=0,
        id="notificar_preasignadas",
        replace_existing=True
    )

    scheduler.start()
    print("[SCHEDULER] 🕐 Scheduler iniciado con 3 jobs automáticos:")
    print("  - liberar_no_confirmadas   → cada hora (min 0)")
    print("  - vencer_agendas           → diario 00:30")
    print("  - notificar_preasignadas   → diario 07:00")
    return scheduler