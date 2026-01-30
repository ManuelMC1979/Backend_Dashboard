from fastapi import APIRouter, Query, HTTPException
from typing import Optional, List, Dict, Any
from datetime import date
from decimal import Decimal

import mysql.connector
from mysql.connector import Error

from config import DB_CONFIG  # <- sin circular import

router = APIRouter()


def _to_float(v):
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    try:
        return float(v)
    except Exception:
        return None


def get_db_conn():
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except Error as e:
        raise HTTPException(status_code=500, detail=f"Error conexión BD: {e}")



# --- AUTH LOGIN ENDPOINT REAL ---
import secrets
from datetime import datetime, timedelta
from security_context import crypt_context

# Global token store: token -> {user_id, expires_at}
TOKENS: Dict[str, Dict[str, Any]] = {}

ROLE_MAP = {1: "ejecutivo", 2: "supervisor", 3: "jefatura"}

@router.post("/auth/login")
def login(payload: Dict[str, Any]):
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password")
    if not email or not password:
        print(f"[auth] login fail: {email}")
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    conn = get_db_conn()
    cur = None
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id, nombre, correo, password_hash, is_active, role_id FROM users WHERE correo = %s",
            (email,)
        )
        user = cur.fetchone()
        if not user or not user.get("password_hash"):
            print(f"[auth] login fail: {email}")
            raise HTTPException(status_code=401, detail="Credenciales inválidas")

        if not user["password_hash"].startswith("$2b$"):
            print(f"[auth] login fail: {email} (hash no bcrypt)")
            raise HTTPException(status_code=401, detail="Credenciales inválidas")

        if not crypt_context.verify(password, user["password_hash"]):
            print(f"[auth] login fail: {email}")
            raise HTTPException(status_code=401, detail="Credenciales inválidas")

        if not user["is_active"]:
            print(f"[auth] login fail: {email} (inactivo)")
            raise HTTPException(status_code=403, detail="Usuario inactivo")

        role_str = ROLE_MAP.get(user["role_id"], "ejecutivo")
        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(hours=12)
        TOKENS[token] = {"user_id": user["id"], "expires_at": expires_at}

        print(f"[auth] login ok: {email}")
        return {
            "token": token,
            "usuario": {
                "id": user["id"],
                "nombre": user["nombre"],
                "correo": user["correo"],
                "rol": role_str,
            },
        }
    except Exception as e:
        print(f"[auth] login fail: {email} (error: {e})")
        raise HTTPException(status_code=401, detail="Credenciales inválidas")
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


@router.get("/kpis")
def get_kpis(meses: List[str] = Query(...), ejecutivo: Optional[str] = None):
    if not meses:
        return {"data": []}

    placeholders = ",".join(["%s"] * len(meses))

    sql = f"""
        SELECT
            ejecutivo,
            mes,
            tmo,
            transfEPA,
            tipificaciones,
            satEp,
            resEp,
            satSnl,
            resSnl
        FROM kpi_monthly
        WHERE mes IN ({placeholders})
    """

    params: List[Any] = list(meses)

    if ejecutivo:
        sql += " AND ejecutivo = %s"
        params.append(ejecutivo)

    sql += " ORDER BY mes, ejecutivo"

    conn = get_db_conn()
    cur = None
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params)
        rows = cur.fetchall() or []

        # LOG TEMPORAL: verificar que NULL viene como None desde MySQL
        if rows:
            print(f"[DEBUG /api/kpis] Primera fila cruda del cursor: {rows[0]}")

        data = []
        for r in rows:
            data.append(
                {
                    "name": (r.get("ejecutivo") or "").strip(),
                    "mes": (r.get("mes") or "").strip(),
                    "tmo": _to_float(r.get("tmo")),
                    "transfEPA": _to_float(r.get("transfEPA")),
                    "tipificaciones": _to_float(r.get("tipificaciones")),
                    "satEp": _to_float(r.get("satEp")),
                    "resEp": _to_float(r.get("resEp")),
                    "satSnl": _to_float(r.get("satSnl")),
                    "resSnl": _to_float(r.get("resSnl")),
                }
            )

        return {"data": data}

    except Error as e:
        raise HTTPException(status_code=500, detail=f"Error query KPIs: {e}")
    finally:
        try:
            if cur:
                cur.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


@router.get("/kpis/historial")
def get_historial():
    # DEMO hoy (presentación)
    return {
        "resEP": [80, 82, 85],
        "satEP": [90, 91, 92],
        "tmo": [50, 55, 54],
        "epa": [10, 11, 12],
        "satSNL": [88, 89, 90],
    }


@router.post("/auditoria")
def auditoria(payload: Dict[str, Any]):
    return {"id": 1, "status": "registered"}


@router.get("/recomendaciones")
def get_recomendaciones(ejecutivo: Optional[str] = None, mes: Optional[str] = None):
    return {
        "recomendaciones": [
            {
                "id": 1,
                "fecha": str(date.today()),
                "ejecutivo": ejecutivo or "EJECUTIVO DEMO",
                "mes": mes or "ENERO",
                "recomendacion": "Revisar TMO y tipificaciones",
                "estado": "Pendiente",
            }
        ]
    }


@router.post("/recomendaciones")
def post_recomendacion(payload: Dict[str, Any]):
    return {"id": 2, "status": "created"}


@router.patch("/recomendaciones/{rec_id}")
def patch_recomendacion(rec_id: int, payload: Dict[str, Any]):
    return {"id": rec_id, "estado": payload.get("estado", "Pendiente")}