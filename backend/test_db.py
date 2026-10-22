print("INICIANDO PRUEBA...")

from config import get_connection

conn = get_connection()

if conn:
    print("TODO BIEN 🔥")
else:
    print("FALLÓ ❌")