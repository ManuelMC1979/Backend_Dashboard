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


@router.post("/auth/login")
def login(payload: Dict[str, Any]):
    # DEMO hoy (no tocar)
    email = payload.get("email")
    password = payload.get("password")
    if email == "admin@demo.cl" and password == "1234":
        return {
            "token": "dev-token",
            "user": {"nombre": "Admin Demo", "email": email, "rol": "supervisor"},
        }
    return {"detail": "Credenciales inválidas"}


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