import smtplib
from email.mime.text import MIMEText

GMAIL_USER = "barriosjuan9865@gmail.com"
GMAIL_PASS = "cjiisrfhehcuhsga"

msg = MIMEText("Código de prueba: 123456")
msg["Subject"] = "Prueba Hospital"
msg["From"]    = GMAIL_USER
msg["To"]      = "barriosjuan9865@gmail.com"  # enviá a vos mismo primero

with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
    server.login(GMAIL_USER, GMAIL_PASS)
    server.sendmail(GMAIL_USER, GMAIL_USER, msg.as_string())
    print("Enviado OK")