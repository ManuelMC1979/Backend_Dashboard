from fastapi import APIRouter, Query
from typing import Optional, List, Dict, Any
from datetime import date

router = APIRouter()

@router.post("/auth/login")
def login(payload: Dict[str, Any]):
    # MOCK: después lo conectamos a BD/JWT
    email = payload.get("email")
    password = payload.get("password")
    if email == "admin@demo.cl" and password == "1234":
        return {
            "token": "dev-token",
            "user": {"nombre": "Admin Demo", "email": email, "rol": "supervisor"}
        }
    return {"detail": "Credenciales inválidas"}

@router.get("/kpis")
def get_kpis(
    meses: List[str] = Query(...),
    ejecutivo: Optional[str] = None
):
    # MOCK: estructura basada en tu reporte INT-001
    data = []
    for mes in meses:
        data.append({
            "name": ejecutivo or "EJECUTIVO DEMO",
            "mes": mes,
            "tmo": 55.2,
            "transfEPA": 12.3,
            "tipificaciones": 88.1,
            "satEp": 92.0,
            "resEp": 86.0,
            "satSnl": 90.0,
            "resSnl": 84.0
        })
    return {"data": data}

@router.get("/kpis/historial")
def get_historial():
    # MOCK: estructura basada en INT-003
    return {
        "resEP": [80, 82, 85],
        "satEP": [90, 91, 92],
        "tmo": [50, 55, 54],
        "epa": [10, 11, 12],
        "satSNL": [88, 89, 90]
    }

@router.post("/auditoria")
def auditoria(payload: Dict[str, Any]):
    return {"id": 1, "status": "registered"}

@router.get("/recomendaciones")
def get_recomendaciones(ejecutivo: Optional[str] = None, mes: Optional[str] = None):
    return {
        "recomendaciones": [
            {"id": 1, "fecha": str(date.today()), "ejecutivo": ejecutivo or "EJECUTIVO DEMO", "mes": mes or "ENERO",
             "recomendacion": "Revisar TMO y tipificaciones", "estado": "Pendiente"}
        ]
    }

@router.post("/recomendaciones")
def post_recomendacion(payload: Dict[str, Any]):
    return {"id": 2, "status": "created"}

@router.patch("/recomendaciones/{rec_id}")
def patch_recomendacion(rec_id: int, payload: Dict[str, Any]):
    return {"id": rec_id, "estado": payload.get("estado", "Pendiente")}