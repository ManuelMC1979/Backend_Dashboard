# main.py
from __future__ import annotations

from fastapi import FastAPI, File, UploadFile, Form, Header, HTTPException, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Dict, List, Any
import pandas as pd
import tempfile
import os
import httpx

# Variables de entorno
DB_PASSWORD = os.getenv("DB_PASSWORD") or os.getenv("DB_PASS") or ""

print("[env] DB_PASSWORD_set=", bool(DB_PASSWORD))
from datetime import datetime

# Router de API (tu /api/kpis, etc.)
from api_dashboard import router as api_router
from admin_users import router as admin_users_router


app = FastAPI()

# CORS para producción y desarrollo local
ALLOWED_ORIGINS = [
    "https://gtrmanuelmonsalve.cl",
    "https://www.gtrmanuelmonsalve.cl",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.include_router(api_router, prefix="/api")
app.include_router(admin_users_router, prefix="/api/admin")


# --- TOKEN AUTH HELPERS (Token opaco - validación contra API principal) ---

# URL del API principal para validar tokens
MAIN_API_URL = os.getenv("MAIN_API_URL", "https://api.gtrmanuelmonsalve.cl")


async def validate_token_with_main_api(token: str) -> Dict[str, Any]:
    """
    Valida un token opaco consultando al API principal.
    NO decodifica JWT localmente - el token es opaco.
    
    Request: GET {MAIN_API_URL}/api/auth/me
    Header: Authorization: Bearer <token>
    
    Returns: dict con datos del usuario si es válido
    Raises: HTTPException 401 si el token es inválido
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{MAIN_API_URL}/api/auth/me",
                headers={"Authorization": f"Bearer {token}"}
            )
        
        if response.status_code == 200:
            return response.json()
        
        # Token inválido o expirado
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado"
        )
    
    except httpx.RequestError as e:
        # Error de conexión al API principal
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"No se pudo validar el token: {str(e)}"
        )


async def require_admin_token(token: str) -> Dict[str, Any]:
    """
    Valida que el token sea de un usuario admin.
    
    Criterios de admin (cualquiera):
    - user.rol == "admin"
    - user.role_id == 99 o 1
    - user.is_admin == true
    
    Returns: dict con datos del usuario admin
    Raises: HTTPException 401/403
    """
    user = await validate_token_with_main_api(token)
    
    # Verificar si es admin por cualquiera de los criterios
    rol = user.get("rol", "")
    role_id = user.get("role_id")
    is_admin_flag = user.get("is_admin", False)
    
    is_admin = (
        rol == "admin" or
        role_id in (99, 1) or
        is_admin_flag is True
    )
    
    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado - Solo administradores"
        )
    
    return user


def extract_bearer_token(authorization: str | None) -> str:
    """
    Extrae el token del header Authorization: Bearer <token>
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Header Authorization requerido"
        )
    
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Formato inválido. Use: Bearer <token>"
        )
    
    return authorization.split(" ", 1)[1]


# --- FIN AUTH HELPERS ---


def normalizar_valor(valor) -> Optional[float]:
    """
    Normaliza cualquier formato de porcentaje a decimal (0-1).
    Ejemplos:
    - "95,50 %" -> 0.9550
    - "0,9550" -> 0.9550
    - 95.5 -> 0.9550
    - 0.9550 -> 0.9550
    - 1 -> 1.0
    """
    if pd.isna(valor) or valor == "":
        return None

    try:
        # Si es string, limpiar
        if isinstance(valor, str):
            # Remover espacios, %, y reemplazar coma por punto
            valor_limpio = valor.replace(" ", "").replace("%", "").replace(",", ".")
            if valor_limpio == "":
                return None
            valor_num = float(valor_limpio)
        else:
            valor_num = float(valor)

        # Si el valor es mayor a 10, asumimos que está en escala 0-100
        if valor_num > 10:
            return round(valor_num / 100, 4)
        # Si está entre 0 y 1, ya está normalizado
        if 0 <= valor_num <= 1:
            return round(valor_num, 4)
        # Si está entre 1 y 10, podría ser ambiguo pero asumimos 0-100
        if 1 < valor_num <= 10:
            return round(valor_num / 100, 4)

        return None

    except (ValueError, TypeError):
        return None


def buscar_columna_valor(df: pd.DataFrame, kpi_nombre: str) -> Optional[str]:
    """
    Busca la columna correcta para extraer valores.
    Prioridad:
    1. Columna "Total" (case insensitive)
    2. Columna con header que contenga el tipo de KPI (%SATISFACCION, %RESOLUCION, etc.)
    3. Segunda columna como fallback
    """
    columnas = df.columns.tolist()

    # Primera fila (que contiene los nombres reales de las métricas)
    primera_fila = df.iloc[0] if len(df) > 0 else None

    # Opción 1: Buscar columna "Total"
    for col in columnas:
        if isinstance(col, str) and col.lower().strip() == "total":
            return col

    # Opción 2: Buscar por tipo de KPI en la primera fila
    kpi_patterns = {
        "TMO": ["%tmo", "tmo"],
        "TransfEPA": ["%transf", "transf epa", "transfepa", "transf."],
        "Tipificaciones": ["%tipif", "tipif", "tipificaciones"],
        "SatEP": ["%satisf", "satisf"],
        "ResEP": ["%resol", "resol"],
        "SatSNL": ["%satisf", "satisf"],
        "ResSNL": ["%resol", "resol"],
    }

    if kpi_nombre in kpi_patterns and primera_fila is not None:
        patterns = kpi_patterns[kpi_nombre]
        for col in columnas:
            try:
                valor_primera_fila = str(primera_fila[col]).lower()
            except Exception:
                continue
            for pattern in patterns:
                if pattern in valor_primera_fila:
                    return col

    # Opción 3: Segunda columna como fallback
    if len(columnas) >= 2:
        return columnas[1]

    return None


def detectar_tipo_kpi(archivo_bytes: bytes) -> Dict[str, str]:
    """
    Detecta qué tipo de KPI contiene el archivo.
    Retorna: {'tipo': 'Satisfacción EP', 'servicio': 'EP', 'metrica': 'SATISFACCION'}
    """
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(archivo_bytes)
            tmp_path = tmp.name

        df = pd.read_excel(tmp_path)
        df_raw = pd.read_excel(tmp_path, header=None)
        os.unlink(tmp_path)

        # Buscar en headers (primera fila de datos)
        metrica = None
        if len(df) > 0:
            primera_fila = df.iloc[0]
            primera_fila_str = " ".join([str(v) for v in primera_fila.values]).upper()

            if "SATISF" in primera_fila_str:
                metrica = "SATISFACCION"
            elif "RESOL" in primera_fila_str:
                metrica = "RESOLUCION"
            elif "TMO" in primera_fila_str:
                metrica = "TMO"
            elif "TRANSF" in primera_fila_str:
                metrica = "TRANSF EPA"
            elif "TIPIF" in primera_fila_str:
                metrica = "TIPIFICACIONES"

        # Buscar servicio en "Filtros aplicados"
        servicio = None
        for _, row in df_raw.iterrows():
            for col_val in row:
                if col_val and isinstance(col_val, str) and "SERVICIO es" in col_val:
                    if "SERVICIO es EP" in col_val:
                        servicio = "EP"
                    elif "SERVICIO es SNL" in col_val:
                        servicio = "SNL"
                    break

        # Construir nombre completo
        if metrica and servicio:
            if metrica == "SATISFACCION":
                tipo_completo = f"Satisfacción {servicio}"
            elif metrica == "RESOLUCION":
                tipo_completo = f"Resolución {servicio}"
            elif metrica == "TRANSF EPA":
                tipo_completo = f"Transferencias {servicio}"
            else:
                tipo_completo = metrica
        elif metrica:
            tipo_completo = metrica
        else:
            tipo_completo = "Desconocido"

        return {
            "tipo": tipo_completo,
            "servicio": servicio or "N/A",
            "metrica": metrica or "N/A",
        }

    except Exception:
        return {"tipo": "Error al detectar", "servicio": "N/A", "metrica": "N/A"}


def procesar_archivo_kpi(archivo_bytes: bytes, kpi_nombre: str) -> Dict[str, Optional[float]]:
    """
    Procesa un archivo KPI y extrae los valores por ejecutivo.
    Retorna dict: ejecutivo -> valor (porcentaje 0-100) o None
    """
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(archivo_bytes)
            tmp_path = tmp.name

        df = pd.read_excel(tmp_path)
        os.unlink(tmp_path)

        if df.empty:
            return {}

        # La primera columna tiene el nombre del ejecutivo
        columna_ejecutivo = df.columns[0]

        # Buscar columna de valor de forma inteligente
        columna_valor = buscar_columna_valor(df, kpi_nombre)

        if not columna_valor:
            print(f"No se encontró columna de valor para {kpi_nombre}")
            return {}

        # Saltar la primera fila (que tiene el nombre de la columna repetido)
        df = df.iloc[1:]

        # Crear diccionario ejecutivo -> valor
        resultado: Dict[str, Optional[float]] = {}
        for _, row in df.iterrows():
            ejecutivo = row.get(columna_ejecutivo, None)
            valor = row.get(columna_valor, None)

            # Filtrar filas inválidas
            if pd.isna(ejecutivo) or ejecutivo == "":
                continue
            if isinstance(ejecutivo, str) and ("Filtros aplicados" in ejecutivo or ejecutivo.strip() == "Total"):
                continue

            # Normalizar valor (siempre devuelve decimal 0-1)
            valor_normalizado = normalizar_valor(valor)

            # Convertir a porcentaje (multiplicar por 100)
            if valor_normalizado is not None:
                resultado[str(ejecutivo)] = round(valor_normalizado * 100, 2)
            else:
                resultado[str(ejecutivo)] = None

        return resultado

    except Exception as e:
        print(f"Error procesando {kpi_nombre}: {e}")
        return {}


def unificar_datos_kpi(archivos_data: Dict[str, bytes], kpis_omitidos: List[str]) -> List[dict]:
    """
    Unifica los datos de todos los archivos KPI.
    Retorna lista de registros normalizados.
    """
    datos_por_kpi: Dict[str, Dict[str, Optional[float]]] = {}

    for kpi_nombre, archivo_bytes in archivos_data.items():
        if kpi_nombre not in kpis_omitidos:
            datos_por_kpi[kpi_nombre] = procesar_archivo_kpi(archivo_bytes, kpi_nombre)

    todos_ejecutivos = set()
    for datos in datos_por_kpi.values():
        todos_ejecutivos.update(datos.keys())

    registros: List[dict] = []
    for ejecutivo in sorted(todos_ejecutivos):
        registro = {"ejecutivo": ejecutivo}
        for kpi_nombre in ["TMO", "TransfEPA", "Tipificaciones", "SatEP", "ResEP", "SatSNL", "ResSNL"]:
            key = kpi_nombre.lower()
            if kpi_nombre in kpis_omitidos:
                registro[key] = None
            else:
                registro[key] = datos_por_kpi.get(kpi_nombre, {}).get(ejecutivo, None)
        registros.append(registro)

    return registros


async def enviar_a_n8n(registros: list, fecha_registro: str, digitador: Optional[Dict[str, Any]] = None):
    """
    Envía los registros al webhook de n8n para procesamiento.
    Incluye información del digitador (admin que realizó la carga) como 'ingresado_por'.
    """
    try:
        fecha_obj = datetime.strptime(fecha_registro, "%Y-%m-%d")
        anio = fecha_obj.year
        meses_esp = [
            "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
            "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"
        ]
        mes = meses_esp[fecha_obj.month - 1]

        # Normalizar digitador para el payload
        if digitador:
            ingresado_por = {
                "email": digitador.get("email") or digitador.get("correo", "unknown"),
                "nombre": digitador.get("nombre_mostrar") or digitador.get("nombre", "Desconocido"),
                "rut": digitador.get("rut"),
                "rol": digitador.get("rol", "admin"),
            }
        else:
            ingresado_por = {"email": "sistema", "nombre": "Sistema", "rol": "system"}

        payload = {
            "registros": registros,
            "fecha_registro": fecha_registro,
            "anio": anio,
            "mes": mes,
            "ingresado_por": ingresado_por,  # Campo estándar para n8n
            "digitador": ingresado_por,  # Alias para compatibilidad
        }

        n8n_webhook_url = "https://kpi-dashboard-n8n.f7jaui.easypanel.host/webhook/kpi-upload"

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(n8n_webhook_url, json=payload)

        if response.status_code == 200:
            return {"success": True, "data": response.json()}
        return {"success": False, "error": f"Error en n8n: {response.status_code}"}

    except Exception as e:
        print(f"Error llamando a n8n: {e}")
        return {"success": False, "error": str(e)}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/detectar-kpi")
async def detectar_kpi_endpoint(archivo: UploadFile = File(...)):
    """Endpoint para detectar tipo de KPI de un archivo"""
    try:
        archivo_bytes = await archivo.read()
        info = detectar_tipo_kpi(archivo_bytes)
        return JSONResponse(content={"status": "success", "info": info})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "detail": str(e)})


@app.get("/", response_class=HTMLResponse)
async def upload_form(t: Optional[str] = None):
    """Formulario HTML para subir archivos KPI con pre-lectura.
    
    Requiere token en query param: /?t=TOKEN
    El token se valida contra el API principal.
    """
    # Verificar que existe token
    if not t:
        return HTMLResponse(content="""
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Acceso Restringido - ACHS</title>
<style>
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background-color: #0a1929;
  color: #ffffff;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
}
.error-card {
  background-color: #1e293b;
  border-radius: 8px;
  padding: 48px;
  text-align: center;
  border-left: 4px solid #ef4444;
}
.error-card h1 { color: #ef4444; margin-bottom: 16px; }
.error-card p { color: #94a3b8; margin-bottom: 24px; }
.error-card a { color: #22c55e; text-decoration: underline; }
</style>
</head>
<body>
<div class="error-card">
  <h1>⛔ Acceso Restringido</h1>
  <p>Falta el token de autenticación.</p>
  <a href="https://www.gtrmanuelmonsalve.cl">Volver al Dashboard</a>
</div>
</body>
</html>
        """, status_code=401)
    
    # Validar token con API principal
    try:
        admin_user = await require_admin_token(t)
    except HTTPException as e:
        error_msg = e.detail if hasattr(e, 'detail') else "Token inválido"
        return HTMLResponse(content=f"""
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Acceso Denegado - ACHS</title>
<style>
body {{
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background-color: #0a1929;
  color: #ffffff;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
}}
.error-card {{
  background-color: #1e293b;
  border-radius: 8px;
  padding: 48px;
  text-align: center;
  border-left: 4px solid #ef4444;
}}
.error-card h1 {{ color: #ef4444; margin-bottom: 16px; }}
.error-card p {{ color: #94a3b8; margin-bottom: 24px; }}
.error-card a {{ color: #22c55e; text-decoration: underline; }}
</style>
</head>
<body>
<div class="error-card">
  <h1>⛔ Acceso Denegado</h1>
  <p>{error_msg}</p>
  <a href="https://www.gtrmanuelmonsalve.cl">Volver al Dashboard</a>
</div>
</body>
</html>
        """, status_code=e.status_code)
    
    # Token válido y es admin - mostrar formulario
    return """
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Carga de Archivos KPI - ACHS</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background-color: #0a1929;
  color: #ffffff;
  min-height: 100vh;
  padding: 40px 20px;
}
.container { max-width: 800px; margin: 0 auto; }
.header {
  background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%);
  padding: 32px;
  border-radius: 8px;
  margin-bottom: 32px;
}
.header h1 { font-size: 28px; font-weight: 600; margin-bottom: 8px; }
.header p { color: #dcfce7; font-size: 14px; }
.form-card {
  background-color: #1e293b;
  border-radius: 8px;
  padding: 32px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.3);
}
.form-group { margin-bottom: 24px; }
.form-group label {
  display: block;
  color: #94a3b8;
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-weight: 500;
  margin-bottom: 8px;
}
.checkbox-wrapper { display: flex; align-items: center; gap: 8px; margin-top: 8px; }
.checkbox-wrapper input[type="checkbox"] { width: 18px; height: 18px; cursor: pointer; }
.checkbox-wrapper label {
  color: #64748b;
  font-size: 13px;
  text-transform: none;
  letter-spacing: normal;
  margin: 0;
  cursor: pointer;
}
.file-input-wrapper {
  position: relative;
  background-color: #0f172a;
  border: 2px dashed #334155;
  border-radius: 6px;
  padding: 16px;
  cursor: pointer;
  transition: all 0.3s;
}
.file-input-wrapper:hover { border-color: #22c55e; background-color: #1e293b; }
.file-input-wrapper.has-file { border-color: #22c55e; background-color: #064e3b; }
.file-input-wrapper.disabled { opacity: 0.4; cursor: not-allowed; pointer-events: none; }
.file-input-wrapper input[type="file"] {
  position: absolute; width: 100%; height: 100%;
  top: 0; left: 0; opacity: 0; cursor: pointer;
}
.file-label { color: #64748b; font-size: 14px; pointer-events: none; }
.file-input-wrapper.has-file .file-label { color: #22c55e; font-weight: 500; }
.file-detected-info {
  margin-top: 8px;
  padding: 8px 12px;
  background-color: #172554;
  border-left: 3px solid #3b82f6;
  border-radius: 4px;
  display: none;
}
.file-detected-info.show { display: block; }
.file-detected-info p { color: #93c5fd; font-size: 12px; margin: 0; }
.file-detected-info strong { color: #60a5fa; }
.date-input {
  width: 100%;
  background-color: #0f172a;
  border: 1px solid #334155;
  border-radius: 6px;
  padding: 12px 16px;
  color: #ffffff;
  font-size: 14px;
}
.date-input:focus { outline: none; border-color: #22c55e; }
.submit-btn {
  width: 100%;
  background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%);
  color: #ffffff;
  border: none;
  padding: 16px;
  border-radius: 6px;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
  transition: transform 0.2s;
}
.submit-btn:hover { transform: translateY(-2px); }
.submit-btn:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }
.status {
  margin-top: 20px;
  padding: 16px;
  border-radius: 6px;
  display: none;
}
.status.success { background-color: #064e3b; border-left: 3px solid #22c55e; color: #22c55e; }
.status.error {{ background-color: #7f1d1d; border-left: 3px solid #ef4444; color: #fca5a5; }}
</style>
</head>
<body>
  <!-- Contenido principal (ya validado server-side como admin) -->
  <div id="mainContent" class="container">
    <div class="header">
      <h1>Carga de Archivos KPI</h1>
      <p>Panel de Control Operacional ACHS</p>
    </div>

    <div class="form-card">
      <form id="uploadForm" enctype="multipart/form-data">
        <div class="form-group">
          <label>Seleccione fecha del registro</label>
          <input type="date" name="fecha_registro" class="date-input" required>
        </div>

        <!-- TMO -->
        <div class="form-group">
          <label>TMO (Tiempo Medio de Operación)</label>
          <div class="checkbox-wrapper">
            <input type="checkbox" id="omitir_tmo" name="omitir_tmo" onchange="toggleFileInput('tmo')">
            <label for="omitir_tmo">Omitir (sin datos)</label>
          </div>
          <div class="file-input-wrapper" data-input="tmo" id="wrapper_tmo">
            <input type="file" name="tmo" accept=".xlsx,.xls,.csv" onchange="handleFileChange(this, 'tmo')">
            <div class="file-label">Seleccionar archivo...</div>
          </div>
          <div class="file-detected-info" id="info_tmo">
            <p>Detectado: <strong id="detected_tmo"></strong></p>
          </div>
        </div>

        <!-- Transf EPA -->
        <div class="form-group">
          <label>Transf EPA (Transferencias EPA)</label>
          <div class="checkbox-wrapper">
            <input type="checkbox" id="omitir_transf_epa" name="omitir_transf_epa" onchange="toggleFileInput('transf_epa')">
            <label for="omitir_transf_epa">Omitir (sin datos)</label>
          </div>
          <div class="file-input-wrapper" data-input="transf_epa" id="wrapper_transf_epa">
            <input type="file" name="transf_epa" accept=".xlsx,.xls,.csv" onchange="handleFileChange(this, 'transf_epa')">
            <div class="file-label">Seleccionar archivo...</div>
          </div>
          <div class="file-detected-info" id="info_transf_epa">
            <p>Detectado: <strong id="detected_transf_epa"></strong></p>
          </div>
        </div>

        <!-- Tipificaciones -->
        <div class="form-group">
          <label>Tipificaciones</label>
          <div class="checkbox-wrapper">
            <input type="checkbox" id="omitir_tipificaciones" name="omitir_tipificaciones" onchange="toggleFileInput('tipificaciones')">
            <label for="omitir_tipificaciones">Omitir (sin datos)</label>
          </div>
          <div class="file-input-wrapper" data-input="tipificaciones" id="wrapper_tipificaciones">
            <input type="file" name="tipificaciones" accept=".xlsx,.xls,.csv" onchange="handleFileChange(this, 'tipificaciones')">
            <div class="file-label">Seleccionar archivo...</div>
          </div>
          <div class="file-detected-info" id="info_tipificaciones">
            <p>Detectado: <strong id="detected_tipificaciones"></strong></p>
          </div>
        </div>

        <!-- Sat EP -->
        <div class="form-group">
          <label>Sat EP (Satisfacción EP)</label>
          <div class="checkbox-wrapper">
            <input type="checkbox" id="omitir_sat_ep" name="omitir_sat_ep" onchange="toggleFileInput('sat_ep')">
            <label for="omitir_sat_ep">Omitir (sin datos)</label>
          </div>
          <div class="file-input-wrapper" data-input="sat_ep" id="wrapper_sat_ep">
            <input type="file" name="sat_ep" accept=".xlsx,.xls,.csv" onchange="handleFileChange(this, 'sat_ep')">
            <div class="file-label">Seleccionar archivo...</div>
          </div>
          <div class="file-detected-info" id="info_sat_ep">
            <p>Detectado: <strong id="detected_sat_ep"></strong></p>
          </div>
        </div>

        <!-- Res EP -->
        <div class="form-group">
          <label>Res EP (Resolución EP)</label>
          <div class="checkbox-wrapper">
            <input type="checkbox" id="omitir_res_ep" name="omitir_res_ep" onchange="toggleFileInput('res_ep')">
            <label for="omitir_res_ep">Omitir (sin datos)</label>
          </div>
          <div class="file-input-wrapper" data-input="res_ep" id="wrapper_res_ep">
            <input type="file" name="res_ep" accept=".xlsx,.xls,.csv" onchange="handleFileChange(this, 'res_ep')">
            <div class="file-label">Seleccionar archivo...</div>
          </div>
          <div class="file-detected-info" id="info_res_ep">
            <p>Detectado: <strong id="detected_res_ep"></strong></p>
          </div>
        </div>

        <!-- Sat SNL -->
        <div class="form-group">
          <label>Sat SNL (Satisfacción SNL)</label>
          <div class="checkbox-wrapper">
            <input type="checkbox" id="omitir_sat_snl" name="omitir_sat_snl" onchange="toggleFileInput('sat_snl')">
            <label for="omitir_sat_snl">Omitir (sin datos)</label>
          </div>
          <div class="file-input-wrapper" data-input="sat_snl" id="wrapper_sat_snl">
            <input type="file" name="sat_snl" accept=".xlsx,.xls,.csv" onchange="handleFileChange(this, 'sat_snl')">
            <div class="file-label">Seleccionar archivo...</div>
          </div>
          <div class="file-detected-info" id="info_sat_snl">
            <p>Detectado: <strong id="detected_sat_snl"></strong></p>
          </div>
        </div>

        <!-- Res SNL -->
        <div class="form-group">
          <label>Res SNL (Resolución SNL)</label>
          <div class="checkbox-wrapper">
            <input type="checkbox" id="omitir_res_snl" name="omitir_res_snl" onchange="toggleFileInput('res_snl')">
            <label for="omitir_res_snl">Omitir (sin datos)</label>
          </div>
          <div class="file-input-wrapper" data-input="res_snl" id="wrapper_res_snl">
            <input type="file" name="res_snl" accept=".xlsx,.xls,.csv" onchange="handleFileChange(this, 'res_snl')">
            <div class="file-label">Seleccionar archivo...</div>
          </div>
          <div class="file-detected-info" id="info_res_snl">
            <p>Detectado: <strong id="detected_res_snl"></strong></p>
          </div>
        </div>

        <button type="submit" class="submit-btn">Procesar Archivos</button>
      </form>

      <div id="status" class="status"></div>
    </div>
  </div>

<script>
  // --- AUTH: Manejo de token opaco ---
  let authToken = null;
  
  function initAuth() {{
    // 1. Leer token desde query param ?t=TOKEN
    const urlParams = new URLSearchParams(window.location.search);
    const tokenFromUrl = urlParams.get('t');
    
    if (tokenFromUrl) {
      // Guardar en localStorage
      localStorage.setItem('kpi_token', tokenFromUrl);
      authToken = tokenFromUrl;
      // Limpiar URL para no mostrar el token
      window.history.replaceState({}, document.title, window.location.pathname);
    } else {
      // Obtener de localStorage si existe
      authToken = localStorage.getItem('kpi_token');
    }
    
    // Si llegamos aquí, el backend ya validó el token (server-side)
    // Solo mostramos el formulario
    document.getElementById('mainContent').style.display = 'block';
  }
  
  function getAuthHeaders() {
    return authToken ? { 'Authorization': 'Bearer ' + authToken } : {};
  }
  
  function handleAuthError(response) {
    if (response.status === 401 || response.status === 403) {
      localStorage.removeItem('kpi_token');
      alert('Sesión expirada o sin permisos. Será redirigido al dashboard.');
      window.location.href = 'https://www.gtrmanuelmonsalve.cl';
      return true;
    }
    return false;
  }
  
  // Inicializar auth al cargar
  document.addEventListener('DOMContentLoaded', initAuth);
  
  // --- FIN AUTH ---

  const filesCache = {};

  function toggleFileInput(name) {
    const checkbox = document.getElementById('omitir_' + name);
    const wrapper = document.getElementById('wrapper_' + name);
    const fileInput = wrapper.querySelector('input[type="file"]');
    const infoDiv = document.getElementById('info_' + name);

    if (checkbox.checked) {
      wrapper.classList.add('disabled');
      fileInput.removeAttribute('required');
      wrapper.querySelector('.file-label').textContent = 'Omitido';
      wrapper.classList.remove('has-file');
      infoDiv.classList.remove('show');
    } else {
      wrapper.classList.remove('disabled');
      wrapper.querySelector('.file-label').textContent = 'Seleccionar archivo...';
    }
  }

  async function handleFileChange(input, kpiName) {
    const wrapper = input.closest('.file-input-wrapper');
    const label = wrapper.querySelector('.file-label');
    const infoDiv = document.getElementById('info_' + kpiName);
    const detectedSpan = document.getElementById('detected_' + kpiName);

    if (input.files.length > 0) {
      const file = input.files[0];
      label.textContent = file.name;
      wrapper.classList.add('has-file');

      filesCache[kpiName] = file;

      const formData = new FormData();
      formData.append('archivo', file);

      try {
        const response = await fetch('/detectar-kpi', {
          method: 'POST',
          body: formData
        });

        const result = await response.json();
        if (result.status === 'success') {
          detectedSpan.textContent = result.info.tipo;
          infoDiv.classList.add('show');
        }
      } catch (error) {
        console.error('Error detectando KPI:', error);
      }
    } else {
      label.textContent = 'Seleccionar archivo...';
      wrapper.classList.remove('has-file');
      infoDiv.classList.remove('show');
      delete filesCache[kpiName];
    }
  }

  document.getElementById('uploadForm').addEventListener('submit', async (e) => {
    e.preventDefault();

    const formData = new FormData(e.target);
    const submitBtn = e.target.querySelector('.submit-btn');
    const status = document.getElementById('status');

    submitBtn.disabled = true;
    submitBtn.textContent = 'Procesando...';
    status.style.display = 'none';

    try {
      const response = await fetch('/upload', {
        method: 'POST',
        headers: getAuthHeaders(),
        body: formData
      });

      if (handleAuthError(response)) return;

      const result = await response.json();

      if (response.ok && result.preview_url) {
        // Redirigir a preview con token en query param
        window.location.href = result.preview_url + '?t=' + encodeURIComponent(authToken);
      } else {
        throw new Error(result.detail || 'Error al procesar archivos');
      }
    } catch (error) {
      status.className = 'status error';
      status.textContent = '✗ ' + error.message;
      status.style.display = 'block';
      submitBtn.disabled = false;
      submitBtn.textContent = 'Procesar Archivos';
    }
  });
</script>
</body>
</html>
""".strip()


preview_data: Dict[str, dict] = {}


@app.post("/upload")
async def upload_files(
    fecha_registro: str = Form(...),
    tmo: Optional[UploadFile] = File(None),
    transf_epa: Optional[UploadFile] = File(None),
    tipificaciones: Optional[UploadFile] = File(None),
    sat_ep: Optional[UploadFile] = File(None),
    res_ep: Optional[UploadFile] = File(None),
    sat_snl: Optional[UploadFile] = File(None),
    res_snl: Optional[UploadFile] = File(None),
    omitir_tmo: Optional[str] = Form(None),
    omitir_transf_epa: Optional[str] = Form(None),
    omitir_tipificaciones: Optional[str] = Form(None),
    omitir_sat_ep: Optional[str] = Form(None),
    omitir_res_ep: Optional[str] = Form(None),
    omitir_sat_snl: Optional[str] = Form(None),
    omitir_res_snl: Optional[str] = Form(None),
    authorization: str = Header(None),
):
    """Endpoint para recibir los 7 archivos KPI y procesarlos (SOLO ADMIN)"""
    # Validar token opaco via API principal
    token = extract_bearer_token(authorization)
    admin_user = await require_admin_token(token)
    
    try:
        kpis_omitidos: List[str] = []
        if omitir_tmo == "on":
            kpis_omitidos.append("TMO")
        if omitir_transf_epa == "on":
            kpis_omitidos.append("TransfEPA")
        if omitir_tipificaciones == "on":
            kpis_omitidos.append("Tipificaciones")
        if omitir_sat_ep == "on":
            kpis_omitidos.append("SatEP")
        if omitir_res_ep == "on":
            kpis_omitidos.append("ResEP")
        if omitir_sat_snl == "on":
            kpis_omitidos.append("SatSNL")
        if omitir_res_snl == "on":
            kpis_omitidos.append("ResSNL")

        archivos_data: Dict[str, bytes] = {}
        if tmo and "TMO" not in kpis_omitidos:
            archivos_data["TMO"] = await tmo.read()
        if transf_epa and "TransfEPA" not in kpis_omitidos:
            archivos_data["TransfEPA"] = await transf_epa.read()
        if tipificaciones and "Tipificaciones" not in kpis_omitidos:
            archivos_data["Tipificaciones"] = await tipificaciones.read()
        if sat_ep and "SatEP" not in kpis_omitidos:
            archivos_data["SatEP"] = await sat_ep.read()
        if res_ep and "ResEP" not in kpis_omitidos:
            archivos_data["ResEP"] = await res_ep.read()
        if sat_snl and "SatSNL" not in kpis_omitidos:
            archivos_data["SatSNL"] = await sat_snl.read()
        if res_snl and "ResSNL" not in kpis_omitidos:
            archivos_data["ResSNL"] = await res_snl.read()

        registros = unificar_datos_kpi(archivos_data, kpis_omitidos)

        session_id = datetime.now().strftime("%Y%m%d%H%M%S")
        preview_data[session_id] = {
            "registros": registros,
            "fecha_registro": fecha_registro,
            "kpis_omitidos": kpis_omitidos,
            "digitador": admin_user,  # Guardar info del admin que subió (email, nombre, etc.)
        }

        return JSONResponse(content={"status": "success", "preview_url": f"/preview/{session_id}"})

    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "detail": str(e)})


@app.get("/preview/{session_id}", response_class=HTMLResponse)
async def preview_data_view(
    session_id: str,
    t: Optional[str] = None,
):
    """Vista previa de datos antes de insertar en BD (SOLO ADMIN).
    
    Requiere token en query param: /preview/{id}?t=TOKEN
    """
    # Validar token
    if not t:
        return HTMLResponse(content="""
        <html><body style="background:#0a1929;color:#fff;font-family:sans-serif;text-align:center;padding:100px;">
        <h1 style="color:#ef4444;">⛔ Acceso Denegado</h1>
        <p>Token de autenticación requerido.</p>
        <a href="https://www.gtrmanuelmonsalve.cl" style="color:#22c55e;">Volver al Dashboard</a>
        </body></html>
        """, status_code=401)
    
    try:
        await require_admin_token(t)
    except HTTPException as e:
        return HTMLResponse(content=f"""
        <html><body style="background:#0a1929;color:#fff;font-family:sans-serif;text-align:center;padding:100px;">
        <h1 style="color:#ef4444;">⛔ Acceso Denegado</h1>
        <p>{e.detail}</p>
        <a href="https://www.gtrmanuelmonsalve.cl" style="color:#22c55e;">Volver al Dashboard</a>
        </body></html>
        """, status_code=e.status_code)
    
    if session_id not in preview_data:
        return HTMLResponse(content="""
        <html><body style="background:#0a1929;color:#fff;font-family:sans-serif;text-align:center;padding:100px;">
        <h1 style="color:#ef4444;">⛔ Sesión Expirada</h1>
        <p>La sesión no existe o ha expirado. Vuelva a cargar los archivos.</p>
        <a href="/" style="color:#22c55e;">Volver al formulario</a>
        </body></html>
        """, status_code=404)

    data = preview_data[session_id]
    registros = data["registros"]
    fecha_registro = data["fecha_registro"]

    filas_html = ""
    for reg in registros:
        filas_html += f"""
        <tr>
            <td>{reg['ejecutivo']}</td>
            <td>{reg.get('tmo') if reg.get('tmo') is not None else '-'}</td>
            <td>{reg.get('transfepa') if reg.get('transfepa') is not None else '-'}</td>
            <td>{reg.get('tipificaciones') if reg.get('tipificaciones') is not None else '-'}</td>
            <td>{reg.get('satep') if reg.get('satep') is not None else '-'}</td>
            <td>{reg.get('resep') if reg.get('resep') is not None else '-'}</td>
            <td>{reg.get('satsnl') if reg.get('satsnl') is not None else '-'}</td>
            <td>{reg.get('ressnl') if reg.get('ressnl') is not None else '-'}</td>
        </tr>
        """

    return f"""
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Vista Previa KPI - ACHS</title>
  <style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      background-color: #0a1929;
      color: #ffffff;
      min-height: 100vh;
      padding: 40px 20px;
    }}
    .container {{ max-width: 1400px; margin: 0 auto; }}
    .header {{
      background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%);
      padding: 32px;
      border-radius: 8px;
      margin-bottom: 32px;
    }}
    .header h1 {{ font-size: 28px; font-weight: 600; margin-bottom: 8px; }}
    .header p {{ color: #dcfce7; font-size: 14px; }}
    .info-card {{
      background-color: #1e293b;
      border-radius: 8px;
      padding: 20px 32px;
      margin-bottom: 24px;
      border-left: 4px solid #22c55e;
    }}
    .info-card p {{ color: #94a3b8; font-size: 14px; margin-bottom: 8px; }}
    .info-card strong {{ color: #ffffff; }}
    .table-card {{
      background-color: #1e293b;
      border-radius: 8px;
      padding: 24px;
      margin-bottom: 24px;
      overflow-x: auto;
    }}
    table {{ width: 100%; border-collapse: collapse; }}
    th {{
      background-color: #0f172a;
      color: #64748b;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      font-weight: 600;
      padding: 12px;
      text-align: left;
      border-bottom: 2px solid #334155;
    }}
    td {{
      padding: 12px;
      color: #ffffff;
      font-size: 14px;
      border-bottom: 1px solid #334155;
    }}
    tr:hover {{ background-color: #0f172a; }}
    .actions {{ display: flex; gap: 16px; justify-content: center; }}
    .btn {{
      padding: 14px 32px;
      border-radius: 6px;
      font-size: 16px;
      font-weight: 600;
      cursor: pointer;
      border: none;
      transition: transform 0.2s;
    }}
    .btn:hover {{ transform: translateY(-2px); }}
    .btn-confirm {{
      background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%);
      color: #ffffff;
    }}
    .btn-back {{ background-color: #475569; color: #ffffff; }}
    .status {{
      margin-top: 20px;
      padding: 16px;
      border-radius: 6px;
      display: none;
      text-align: center;
    }}
    .status.success {{ background-color: #064e3b; border-left: 3px solid #22c55e; color: #22c55e; }}
    .status.error {{ background-color: #7f1d1d; border-left: 3px solid #ef4444; color: #fca5a5; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>Vista Previa de Datos KPI</h1>
      <p>Revise los datos antes de confirmar la inserción</p>
    </div>

    <div class="info-card">
      <p><strong>Fecha de registro:</strong> {fecha_registro}</p>
      <p><strong>Total ejecutivos:</strong> {len(registros)}</p>
    </div>

    <div class="table-card">
      <table>
        <thead>
          <tr>
            <th>Ejecutivo</th>
            <th>TMO</th>
            <th>Transf EPA</th>
            <th>Tipificaciones</th>
            <th>Sat EP</th>
            <th>Res EP</th>
            <th>Sat SNL</th>
            <th>Res SNL</th>
          </tr>
        </thead>
        <tbody>
          {filas_html}
        </tbody>
      </table>
    </div>

    <div class="actions">
      <button class="btn btn-back" onclick="window.history.back()">Volver y Modificar</button>
      <button class="btn btn-confirm" onclick="confirmarInsercion()">Confirmar e Insertar</button>
    </div>

    <div id="status" class="status"></div>
  </div>

<script>
  // Obtener token del localStorage (guardado en la página principal)
  function getAuthToken() {{
    return localStorage.getItem('kpi_token');
  }}

  // Obtener headers con autorización
  function getAuthHeaders() {{
    const token = getAuthToken();
    const headers = {{}};
    if (token) {{
      headers['Authorization'] = `Bearer ${{token}}`;
    }}
    return headers;
  }}

  async function confirmarInsercion() {{
    const status = document.getElementById('status');
    const btnConfirm = document.querySelector('.btn-confirm');

    // Verificar que hay token
    const token = getAuthToken();
    if (!token) {{
      status.className = 'status error';
      status.textContent = '✗ No hay sesión activa. Por favor, inicie sesión nuevamente.';
      status.style.display = 'block';
      return;
    }}

    btnConfirm.disabled = true;
    btnConfirm.textContent = 'Insertando...';

    try {{
      const response = await fetch('/confirm/{session_id}', {{
        method: 'POST',
        headers: getAuthHeaders()
      }});

      const result = await response.json();

      if (response.status === 401 || response.status === 403) {{
        status.className = 'status error';
        status.textContent = '✗ Sesión expirada o sin permisos. Inicie sesión nuevamente.';
        status.style.display = 'block';
        btnConfirm.disabled = false;
        btnConfirm.textContent = 'Confirmar e Insertar';
        return;
      }}

      if (response.ok) {{
        status.className = 'status success';
        status.textContent = '✓ Datos procesados correctamente';
        status.style.display = 'block';

        setTimeout(() => {{
          // Redirigir al formulario principal (el token ya está en localStorage)
          window.location.href = '/';
        }}, 2000);
      }} else {{
        throw new Error(result.detail || 'Error al procesar datos');
      }}
    }} catch (error) {{
      status.className = 'status error';
      status.textContent = '✗ ' + error.message;
      status.style.display = 'block';
      btnConfirm.disabled = false;
      btnConfirm.textContent = 'Confirmar e Insertar';
    }}
  }}
</script>
</body>
</html>
""".strip()


@app.post("/confirm/{session_id}")
async def confirm_insertion(
    session_id: str,
    authorization: str = Header(None),
):
    """Confirmar e insertar datos vía n8n (SOLO ADMIN)"""
    # Validar token opaco via API principal
    token = extract_bearer_token(authorization)
    admin_user = await require_admin_token(token)
    
    if session_id not in preview_data:
        return JSONResponse(status_code=404, content={"status": "error", "detail": "Sesión no encontrada"})

    data = preview_data[session_id]
    # Usar el digitador guardado en la sesión (o el usuario actual si no existe)
    digitador = data.get("digitador") or admin_user

    try:
        result = await enviar_a_n8n(data["registros"], data["fecha_registro"], digitador=digitador)

        if result["success"]:
            del preview_data[session_id]
            return JSONResponse(
                content={
                    "status": "success",
                    "message": "Datos procesados correctamente",
                    "n8n_response": result.get("data", {}),
                }
            )

        return JSONResponse(status_code=500, content={"status": "error", "detail": result.get("error", "Error en n8n")})

    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "detail": str(e)})
