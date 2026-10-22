import mysql.connector

# ── JWT ── clave única para todo el proyecto
JWT_SECRET_KEY  = "hospital_clinica_secret_2024"
JWT_EXPIRES_MIN = 60

def get_connection():
    try:
        conn = mysql.connector.connect(
            host="localhost",
            user="root",
            password="",
            database="hospital_clinica10"
        )
        return conn
    except Exception as e:
        print("Error de conexión:", e)
        return None
