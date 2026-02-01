import os
DB_PASSWORD = os.getenv("DB_PASSWORD") or os.getenv("DB_PASS") or ""
print("[env] DB_PASSWORD_set=", bool(DB_PASSWORD))
from fastapi import APIRouter, Query, HTTPException, Header
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
import bcrypt

# Global token store: token -> {user_id, expires_at}
TOKENS: Dict[str, Dict[str, Any]] = {}

ROLE_MAP = {
    1: "ejecutivo",
    2: "supervisor",
    3: "jefatura",
    99: "admin"
}


def verify_password(plain: str, password_hash: str) -> bool:
    if not plain or not password_hash:
        return False
    if len(plain.encode("utf-8")) > 72:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False

@router.post("/auth/login")
def login(payload: Dict[str, Any]):
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password")
    if not email or not password:
        print(f"[auth] login fail reason=not_found/email")
        raise HTTPException(status_code=401, detail="Credenciales inválidas")

    conn = get_db_conn()
    cur = None
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT id, nombre, nombre_mostrar, correo, password_hash, is_active, role_id FROM users WHERE correo = %s",
            (email,)
        )
        user = cur.fetchone()
        if not user or not user.get("password_hash"):
            print(f"[auth] login fail reason=not_found/email")
            raise HTTPException(status_code=401, detail="Credenciales inválidas")

        if not user["password_hash"].startswith("$2b$"):
            print(f"[auth] login fail reason=bad_password")
            raise HTTPException(status_code=401, detail="Credenciales inválidas")

        if not verify_password(password, user["password_hash"]):
            print(f"[auth] login fail reason=bad_password")
            raise HTTPException(status_code=401, detail="Credenciales inválidas")

        if not user["is_active"]:
            print(f"[auth] login fail reason=inactive user_id={user['id']}")
            raise HTTPException(status_code=403, detail="Usuario inactivo")

        role_str = ROLE_MAP.get(int(user["role_id"]), "ejecutivo")
        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(hours=12)
        TOKENS[token] = {"user_id": user["id"], "expires_at": expires_at}

        # nombre_mostrar tiene prioridad sobre nombre para el frontend
        nombre_display = user.get("nombre_mostrar") or user["nombre"]

        print(f"[auth] login ok user_id={user['id']}")
        return {
            "token": token,
            "usuario": {
                "id": user["id"],
                "nombre": nombre_display,
                "nombre_mostrar": user.get("nombre_mostrar"),
                "correo": user["correo"],
                "rol": role_str,
            },
        }
    except Exception as e:
        print(f"[auth] login fail reason=exception error={e}")
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


# --- ENDPOINT PÚBLICO: Nombres de usuarios (cualquier rol autenticado) ---

@router.get("/usuarios/nombres")
def get_usuarios_nombres():
    """
    Devuelve nombre y nombre_mostrar de todos los usuarios activos.
    Accesible para cualquier rol autenticado.
    NO incluye datos sensibles (id, correo, password, role_id).
    """
    conn = get_db_conn()
    cur = None
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT nombre, nombre_mostrar 
            FROM users 
            WHERE is_active = 1
            ORDER BY nombre
        """)
        usuarios = cur.fetchall()
        
        result = []
        for u in usuarios:
            result.append({
                "nombre": u["nombre"],
                "nombre_mostrar": u.get("nombre_mostrar"),
            })
        
        print(f"[api/usuarios/nombres] list ok count={len(result)}")
        return result
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
    """
    ============================================================
    ANÁLISIS DE FILTRADO - GET /api/kpis
    ============================================================
    ESTADO ACTUAL (sin modificar lógica):
    
    a) FILTROS APLICADOS:
       - meses: OBLIGATORIO (query param). Filtra por mes IN (...)
       - ejecutivo: OPCIONAL (query param). Si se envía, filtra por ejecutivo = %s
    
    b) ROL DEL USUARIO AUTENTICADO:
       - NO SE USA. Este endpoint NO valida token ni rol.
       - Cualquier request (autenticado o no) puede consultar TODOS los KPIs.
       - NO hay restricción por rol (admin, supervisor, ejecutivo).
    
    c) PARÁMETRO EJECUTIVO:
       - El frontend PUEDE enviar ?ejecutivo=NOMBRE para filtrar.
       - Si NO se envía, retorna TODOS los ejecutivos de los meses solicitados.
       - El backend NO fuerza filtro por usuario autenticado.
    
    d) IDENTIFICADOR DE USUARIO:
       - NO SE EXTRAE del token. No hay header Authorization requerido.
    
    CONCLUSIÓN:
       - HOY: Endpoint PÚBLICO, sin restricción por rol.
       - FALTA: Validar token, extraer rol, y si rol=ejecutivo filtrar
         automáticamente por su propio nombre (ignorando param ejecutivo).
    ============================================================
    """
    # --- DEBUG LOG: Análisis de filtrado actual ---
    print(f"[DEBUG /api/kpis] === ANÁLISIS DE FILTRADO ===")
    print(f"[DEBUG /api/kpis] Endpoint NO requiere autenticación (sin header Authorization)")
    print(f"[DEBUG /api/kpis] Parámetros recibidos: meses={meses}, ejecutivo={ejecutivo}")
    print(f"[DEBUG /api/kpis] Filtro por rol: NO APLICADO (endpoint público)")
    print(f"[DEBUG /api/kpis] Si ejecutivo=None -> retorna TODOS los ejecutivos")
    print(f"[DEBUG /api/kpis] === FIN ANÁLISIS ===")
    # --- FIN DEBUG LOG ---
    
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
        print(f"[DEBUG /api/kpis] Filtro ejecutivo APLICADO: {ejecutivo}")
    else:
        print(f"[DEBUG /api/kpis] Filtro ejecutivo NO APLICADO: retornando TODOS")

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
    """
    ============================================================
    ANÁLISIS DE FILTRADO - GET /api/kpis/historial
    ============================================================
    ESTADO ACTUAL (sin modificar lógica):
    
    a) FILTROS APLICADOS:
       - NINGUNO. Retorna datos HARDCODEADOS de demo.
       - No consulta la BD.
    
    b) ROL DEL USUARIO AUTENTICADO:
       - NO SE USA. Endpoint sin autenticación.
       - Cualquier request puede acceder.
    
    c) PARÁMETRO EJECUTIVO:
       - NO ACEPTA parámetros.
       - Siempre retorna los mismos datos fijos.
    
    d) IDENTIFICADOR DE USUARIO:
       - NO SE EXTRAE. Sin validación de token.
    
    CONCLUSIÓN:
       - HOY: Endpoint DEMO/PÚBLICO con datos estáticos.
       - FALTA: Implementar query real a BD, validar token,
         y filtrar por ejecutivo si rol=ejecutivo.
    ============================================================
    """
    # --- DEBUG LOG: Análisis de filtrado actual ---
    print(f"[DEBUG /api/kpis/historial] === ANÁLISIS DE FILTRADO ===")
    print(f"[DEBUG /api/kpis/historial] Endpoint NO requiere autenticación")
    print(f"[DEBUG /api/kpis/historial] Retorna datos HARDCODEADOS (demo)")
    print(f"[DEBUG /api/kpis/historial] NO consulta BD, NO filtra por rol ni usuario")
    print(f"[DEBUG /api/kpis/historial] === FIN ANÁLISIS ===")
    # --- FIN DEBUG LOG ---
    
    # DEMO hoy (presentación)
    return {
        "resEP": [80, 82, 85],
        "satEP": [90, 91, 92],
        "tmo": [50, 55, 54],
        "epa": [10, 11, 12],
        "satSNL": [88, 89, 90],
    }


@router.get("/meses-disponibles")
def get_meses_disponibles(authorization: str = Header(None)):
    """
    Devuelve los meses con datos disponibles en la BD.
    Ordenados cronológicamente (año, mes).
    
    Requiere: Authorization: Bearer <token>
    
    Respuesta:
    {
      "meses": [
        { "mes": "OCTUBRE", "anio": 2025 },
        { "mes": "NOVIEMBRE", "anio": 2025 },
        ...
      ]
    }
    
    v1.1 - Trigger redeploy
    """
    # --- Validar token ---
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Token requerido")
    
    token = authorization.split(" ", 1)[1]
    session = TOKENS.get(token)
    if not session:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")
    
    from datetime import datetime as dt
    if dt.utcnow() > session["expires_at"]:
        del TOKENS[token]
        raise HTTPException(status_code=401, detail="Token expirado")
    # --- Fin validación token ---
    
    MES_ORDER = [
        'ENERO', 'FEBRERO', 'MARZO', 'ABRIL', 'MAYO', 'JUNIO',
        'JULIO', 'AGOSTO', 'SEPTIEMBRE', 'OCTUBRE', 'NOVIEMBRE', 'DICIEMBRE'
    ]
    
    conn = get_db_conn()
    cur = None
    try:
        cur = conn.cursor(dictionary=True)
        
        # Query para obtener meses y años distintos
        # Intenta primero con columnas separadas (mes, anio)
        cur.execute("""
            SELECT DISTINCT UPPER(mes) as mes, anio 
            FROM kpi_monthly
            WHERE mes IS NOT NULL AND mes != '' AND anio IS NOT NULL
        """)
        rows = cur.fetchall() or []
        
        # Si no hay resultados con columna anio, intentar parsear del campo mes
        if not rows:
            cur.execute("""
                SELECT DISTINCT mes
                FROM kpi_monthly
                WHERE mes IS NOT NULL AND mes != ''
            """)
            rows_raw = cur.fetchall() or []
            
            # Parsear formato "ENERO 2025"
            for row in rows_raw:
                mes_raw = (row.get("mes") or "").strip().upper()
                if not mes_raw:
                    continue
                parts = mes_raw.split()
                if len(parts) >= 2:
                    mes_nombre = parts[0]
                    try:
                        anio = int(parts[1])
                    except ValueError:
                        anio = 2025
                else:
                    mes_nombre = parts[0]
                    anio = 2025
                rows.append({"mes": mes_nombre, "anio": anio})
        
        # Ordenar cronológicamente
        def sort_key(x):
            mes = (x.get("mes") or "").upper()
            anio = x.get("anio") or 2025
            try:
                mes_idx = MES_ORDER.index(mes)
            except ValueError:
                mes_idx = 0
            return (anio, mes_idx)
        
        meses_sorted = sorted(rows, key=sort_key)
        
        # Formato limpio para frontend
        result = [{"mes": m["mes"], "anio": m["anio"]} for m in meses_sorted]
        
        print(f"[DEBUG /api/meses-disponibles] user_id={session['user_id']} meses={len(result)}")
        return {"meses": result}
        
    except Error as e:
        print(f"[ERROR /api/meses-disponibles] {e}")
        raise HTTPException(status_code=500, detail=f"Error consultando meses: {e}")
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