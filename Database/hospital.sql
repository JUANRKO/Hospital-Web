import mysql.connector

def get_connection():
    try:
        conn = mysql.connector.connect(
            host="localhost",
            user="root",
            password="",
            database="hospital_clinica10"
        )
        print("✅ Conexión exitosa")
        return conn
    except Exception as e:
        print("❌ Error de conexión:", e)