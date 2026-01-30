# seed_users.py
# Inserta usuarios base en la tabla `users` si no existen (por correo).
# Deja password_hash = 'PENDING_HASH' para que luego migrate_passwords.py lo reemplace por bcrypt.


import os
import pymysql

DB_PASSWORD = os.getenv("DB_PASSWORD") or os.getenv("DB_PASS") or ""
print("[env] DB_PASSWORD_set=", bool(DB_PASSWORD))

USERS = [
    {"nombre": "Astudillo Marin Manuela Soledad", "email": "msastudillom@ext.achs.cl", "rol": "EJECUTIVO"},
    {"nombre": "Castro Cáceres Marcia Nicole", "email": "mncastroc@ext.achs.cl", "rol": "EJECUTIVO"},
    {"nombre": "Chacón Avilés Alejandra Daniela", "email": "adchacona@ext.achs.cl", "rol": "EJECUTIVO"},
    {"nombre": "Garcia Velasco Ataly Tatiana", "email": "atgarciav@ext.achs.cl", "rol": "EJECUTIVO"},
    {"nombre": "Góngora Zuleta Elsa Susana", "email": "esgongoraz@ext.achs.cl", "rol": "EJECUTIVO"},
    {"nombre": "Hald Tello Katia Liza", "email": "klhaldt@ext.achs.cl", "rol": "EJECUTIVO"},
    {"nombre": "Llancapichun Soto Johana Angelica", "email": "jallancapich@ext.achs.cl", "rol": "EJECUTIVO"},
    {"nombre": "Méndez Pérez Nanci Zobeida", "email": "nzmendezp@ext.achs.cl", "rol": "EJECUTIVO"},
    {"nombre": "Monsalve Corvacho Manuel Alejandro", "email": "mamonsalvec@achs.cl", "rol": "EJECUTIVO"},
    {"nombre": "Olivares González Maximiliano Alfonso", "email": "malolivaresg@ext.achs.cl", "rol": "EJECUTIVO"},
    {"nombre": "Orellana Mallea Ema Alejandra", "email": "eorellanam@ext.achs.cl", "rol": "EJECUTIVO"},
    {"nombre": "Penailillo Cartagena Alejandro Patricio", "email": "appenailillc@ext.achs.cl", "rol": "EJECUTIVO"},
    {"nombre": "Rodriguez Fernandez Daniela Paz", "email": "dprodriguezf@ext.achs.cl", "rol": "EJECUTIVO"},
    {"nombre": "Rodríguez Zenteno José Manuel", "email": "jmrodriguezz@ext.achs.cl", "rol": "EJECUTIVO"},
    {"nombre": "Salgado Tobar Melissa Aracelli", "email": "masalgadot@ext.achs.cl", "rol": "EJECUTIVO"},
    {"nombre": "Velasquez Perez María Loreto", "email": "mlvelasquezp@ext.achs.cl", "rol": "EJECUTIVO"},

    {"nombre": "Berra Fernandez Renzo Gabriel", "email": "rgberraf@achs.cl", "rol": "JEFATURA"},
    {"nombre": "Garcia Cabello Luz Patricia", "email": "lpgarciac@ext.achs.cl", "rol": "SUPERVISOR"},
    {"nombre": "Diaz Amell Barbara Victoria", "email": "bvdiaza@ext.achs.cl", "rol": "SUPERVISOR"},
    {"nombre": "Santander Hernández Luis Alberto", "email": "lsantander@ext.achs.cl", "rol": "JEFATURA"},
]

ROLE_ID = {
    "EJECUTIVO": 1,
    "SUPERVISOR": 2,
    "JEFATURA": 3,
}

def main():

    DB_HOST = os.getenv("DB_HOST", "kpi-dashboard_kpi-db")
    DB_PORT = int(os.getenv("DB_PORT", "3306"))
    DB_USER = os.getenv("DB_USER", "kpi_user")
    DB_NAME = os.getenv("DB_NAME", "kpi_dashboard")

    if not DB_PASSWORD:
        raise SystemExit("Falta DB_PASSWORD/DB_PASS (password de la DB). Define DB_PASSWORD o DB_PASS en variables de entorno.")

    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )

    inserted = 0
    updated = 0

    try:
        with conn.cursor() as cur:
            # Insert idempotente por correo (correo es UNIQUE).
            # rut es UNIQUE y NOT NULL, así que generamos TEMP#### único por cada usuario.
            sql = """
            INSERT INTO users (nombre, rut, correo, password_hash, is_active, role_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                nombre = VALUES(nombre),
                role_id = VALUES(role_id),
                is_active = VALUES(is_active)
            """
            for i, u in enumerate(USERS, start=1):
                rut_temp = f"TEMP{i:04d}"   # ej: TEMP0001 (<= 20 chars, UNIQUE)
                role_id = ROLE_ID.get(u["rol"].upper())
                if not role_id:
                    raise ValueError(f"Rol inválido en USERS: {u['rol']}")

                cur.execute(sql, (
                    u["nombre"],
                    rut_temp,
                    u["email"],
                    "PENDING_HASH",
                    1,
                    role_id
                ))

                # rowcount: 1 insert, 2 update (depende del engine/config)
                if cur.rowcount == 1:
                    inserted += 1
                else:
                    updated += 1

        conn.commit()
        print(f"OK seed_users.py -> inserted={inserted} updated={updated}")
        print("Siguiente: ejecuta migrate_passwords.py para reemplazar PENDING_HASH por bcrypt.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    main()
