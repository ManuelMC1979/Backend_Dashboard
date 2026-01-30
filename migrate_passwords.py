import os
import pymysql
import bcrypt

# ---- Pega aquí tu lista (copiada desde auth.js) ----
USERS = [
    {"nombre": "Astudillo Marin Manuela Soledad", "email": "msastudillom@ext.achs.cl", "rol": "Ejecutivo", "password": "Achs01"},
    {"nombre": "Castro Cáceres Marcia Nicole", "email": "mncastroc@ext.achs.cl", "rol": "Ejecutivo", "password": "Achs02"},
    {"nombre": "Chacón Avilés Alejandra Daniela", "email": "adchacona@ext.achs.cl", "rol": "Ejecutivo", "password": "Achs03"},
    {"nombre": "Garcia Velasco Ataly Tatiana", "email": "atgarciav@ext.achs.cl", "rol": "Ejecutivo", "password": "Achs04"},
    {"nombre": "Góngora Zuleta Elsa Susana", "email": "esgongoraz@ext.achs.cl", "rol": "Ejecutivo", "password": "Achs05"},
    {"nombre": "Hald Tello Katia Liza", "email": "klhaldt@ext.achs.cl", "rol": "Ejecutivo", "password": "Achs06"},
    {"nombre": "Llancapichun Soto Johana Angelica", "email": "jallancapich@ext.achs.cl", "rol": "Ejecutivo", "password": "Achs06"},
    {"nombre": "Méndez Pérez Nanci Zobeida", "email": "nzmendezp@ext.achs.cl", "rol": "Ejecutivo", "password": "Achs07"},
    {"nombre": "Monsalve Corvacho Manuel Alejandro", "email": "mamonsalvec@achs.cl", "rol": "Ejecutivo", "password": "Achs08"},
    {"nombre": "Olivares González Maximiliano Alfonso", "email": "malolivaresg@ext.achs.cl", "rol": "Ejecutivo", "password": "Achs09"},
    {"nombre": "Orellana Mallea Ema Alejandra", "email": "eorellanam@ext.achs.cl", "rol": "Ejecutivo", "password": "Achs10"},
    {"nombre": "Penailillo Cartagena Alejandro Patricio", "email": "appenailillc@ext.achs.cl", "rol": "Ejecutivo", "password": "Achs11"},
    {"nombre": "Rodriguez Fernandez Daniela Paz", "email": "dprodriguezf@ext.achs.cl", "rol": "Ejecutivo", "password": "Achs12"},
    {"nombre": "Rodríguez Zenteno José Manuel", "email": "jmrodriguezz@ext.achs.cl", "rol": "Ejecutivo", "password": "Achs13"},
    {"nombre": "Salgado Tobar Melissa Aracelli", "email": "masalgadot@ext.achs.cl", "rol": "Ejecutivo", "password": "Achs014"},
    {"nombre": "Velasquez Perez María Loreto", "email": "mlvelasquezp@ext.achs.cl", "rol": "Ejecutivo", "password": "Achs015"},
    {"nombre": "Berra Fernandez Renzo Gabriel", "email": "rgberraf@achs.cl", "rol": "Jefatura", "password": "AchsRenzo"},
    {"nombre": "Garcia Cabello Luz Patricia", "email": "lpgarciac@ext.achs.cl", "rol": "Supervisor", "password": "AchsLuz"},
    {"nombre": "Diaz Amell Barbara Victoria", "email": "bvdiaza@ext.achs.cl", "rol": "Supervisor", "password": "AchsBarbara"},
    {"nombre": "Santander Hernández Luis Alberto", "email": "lsantander@ext.achs.cl", "rol": "Jefatura", "password": "AchsLuis"},
]

def hash_password(pw: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(pw.encode("utf-8"), salt).decode("utf-8")

def main():
    # Ideal: variables de entorno del contenedor (EasyPanel)
    DB_HOST = os.getenv("DB_HOST", "kpi-dashboard_kpi-db")
    DB_PORT = int(os.getenv("DB_PORT", "3306"))
    DB_USER = os.getenv("DB_USER", "kpi_user")
    DB_PASS = os.getenv("DB_PASS", "")
    DB_NAME = os.getenv("DB_NAME", "kpi_dashboard")

    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )

    updated = 0
    missing = []

    try:
        with conn.cursor() as cur:
            for u in USERS:
                email = u["email"].strip().lower()
                pw_hash = hash_password(u["password"])

                # Solo actualiza si existe el usuario
                cur.execute("SELECT id FROM users WHERE lower(correo)=%s LIMIT 1", (email,))
                row = cur.fetchone()
                if not row:
                    missing.append(email)
                    continue

                cur.execute(
                    "UPDATE users SET password_hash=%s, updated_at=NOW() WHERE id=%s",
                    (pw_hash, row["id"])
                )
                updated += 1

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"OK. Updated={updated}")
    if missing:
        print("WARNING. No existen en DB estos correos:")
        for m in missing:
            print(" -", m)

if __name__ == "__main__":
    main()