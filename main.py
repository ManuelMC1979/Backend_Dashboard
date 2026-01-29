from fastapi import FastAPI, File, UploadFile, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional, Dict, Tuple
import pandas as pd
import tempfile
import os
from datetime import datetime
import re
from api_dashboard import router as api_router

app = FastAPI()

# CORS para producción y desarrollo local

ALLOWED_ORIGINS = [
“https://gtrmanuelmonsalve.cl”,
“https://www.gtrmanuelmonsalve.cl”,
“http://localhost:8080”,
“http://127.0.0.1:8080”,
]

app.add_middleware(
CORSMiddleware,
allow_origins=ALLOWED_ORIGINS,
allow_credentials=True,
allow_methods=[”*”],
allow_headers=[”*”],
expose_headers=[”*”],
)

app.include_router(api_router, prefix=”/api”)

def normalizar_valor(valor) -> Optional[float]:
“””
Normaliza cualquier formato de porcentaje a decimal (0-1).
Ejemplos:
- “95,50 %” -> 0.9550
- “0,9550” -> 0.9550
- 95.5 -> 0.9550
- 0.9550 -> 0.9550
- 1 -> 1.0
“””
if pd.isna(valor) or valor == ‘’:
return None

```
try:
    # Si es string, limpiar
    if isinstance(valor, str):
        # Remover espacios, %, y reemplazar coma por punto
        valor_limpio = valor.replace(' ', '').replace('%', '').replace(',', '.')
        valor_num = float(valor_limpio)
    else:
        valor_num = float(valor)
    
    # Si el valor es mayor a 10, asumimos que está en escala 0-100
    if valor_num > 10:
        return round(valor_num / 100, 4)
    # Si está entre 0 y 1, ya está normalizado
    elif 0 <= valor_num <= 1:
        return round(valor_num, 4)
    # Si está entre 1 y 10, podría ser ambiguo pero asumimos 0-100
    elif 1 < valor_num <= 10:
        return round(valor_num / 100, 4)
    else:
        return None
        
except (ValueError, TypeError):
    return None
```

def buscar_columna_valor(df: pd.DataFrame, kpi_nombre: str) -> Optional[str]:
“””
Busca la columna correcta para extraer valores.
Prioridad:
1. Columna “Total” (case insensitive)
2. Columna con header que contenga el tipo de KPI (%SATISFACCION, %RESOLUCION, etc.)
3. Segunda columna como fallback
“””
columnas = df.columns.tolist()

```
# Primera fila (que contiene los nombres reales de las métricas)
primera_fila = df.iloc[0] if len(df) > 0 else None

# Opción 1: Buscar columna "Total"
for col in columnas:
    if isinstance(col, str) and col.lower().strip() == 'total':
        return col

# Opción 2: Buscar por tipo de KPI en la primera fila
kpi_patterns = {
    'TMO': ['%tmo', 'tmo'],
    'TransfEPA': ['%transf', 'transf epa'],
    'Tipificaciones': ['%tipif', 'tipif'],
    'SatEP': ['%satisf'],
    'ResEP': ['%resol'],
    'SatSNL': ['%satisf'],
    'ResSNL': ['%resol']
}

if kpi_nombre in kpi_patterns and primera_fila is not None:
    patterns = kpi_patterns[kpi_nombre]
    for col in columnas:
        valor_primera_fila = str(primera_fila[col]).lower()
        for pattern in patterns:
            if pattern in valor_primera_fila:
                return col

# Opción 3: Segunda columna como fallback
if len(columnas) >= 2:
    return columnas[1]

return None
```

def detectar_tipo_kpi(archivo_bytes: bytes) -> Dict[str, str]:
“””
Detecta qué tipo de KPI contiene el archivo.
Retorna: {‘tipo’: ‘Satisfacción EP’, ‘servicio’: ‘EP’, ‘metrica’: ‘SATISFACCION’}
“””
try:
with tempfile.NamedTemporaryFile(delete=False, suffix=’.xlsx’) as tmp:
tmp.write(archivo_bytes)
tmp_path = tmp.name

```
    df = pd.read_excel(tmp_path)
    df_raw = pd.read_excel(tmp_path, header=None)
    os.unlink(tmp_path)
    
    # Buscar en headers (primera fila de datos)
    metrica = None
    if len(df) > 0:
        primera_fila = df.iloc[0]
        primera_fila_str = ' '.join([str(v) for v in primera_fila.values]).upper()
        
        if 'SATISF' in primera_fila_str:
            metrica = 'SATISFACCION'
        elif 'RESOL' in primera_fila_str:
            metrica = 'RESOLUCION'
        elif 'TMO' in primera_fila_str:
            metrica = 'TMO'
        elif 'TRANSF' in primera_fila_str:
            metrica = 'TRANSF EPA'
        elif 'TIPIF' in primera_fila_str:
            metrica = 'TIPIFICACIONES'
    
    # Buscar servicio en "Filtros aplicados"
    servicio = None
    for idx, row in df_raw.iterrows():
        for col_val in row:
            if col_val and isinstance(col_val, str) and 'SERVICIO es' in col_val:
                if 'SERVICIO es EP' in col_val:
                    servicio = 'EP'
                elif 'SERVICIO es SNL' in col_val:
                    servicio = 'SNL'
                break
    
    # Construir nombre completo
    if metrica and servicio:
        if metrica == 'SATISFACCION':
            tipo_completo = f"Satisfacción {servicio}"
        elif metrica == 'RESOLUCION':
            tipo_completo = f"Resolución {servicio}"
        elif metrica == 'TRANSF EPA':
            tipo_completo = f"Transferencias {servicio}"
        else:
            tipo_completo = metrica
    elif metrica:
        tipo_completo = metrica
    else:
        tipo_completo = "Desconocido"
    
    return {
        'tipo': tipo_completo,
        'servicio': servicio or 'N/A',
        'metrica': metrica or 'N/A'
    }
    
except Exception as e:
    return {'tipo': 'Error al detectar', 'servicio': 'N/A', 'metrica': 'N/A'}
```

def procesar_archivo_kpi(archivo_bytes: bytes, kpi_nombre: str) -> Dict[str, float]:
“””
Procesa un archivo KPI y extrae los valores por ejecutivo.
“””
try:
with tempfile.NamedTemporaryFile(delete=False, suffix=’.xlsx’) as tmp:
tmp.write(archivo_bytes)
tmp_path = tmp.name

```
    df = pd.read_excel(tmp_path)
    os.unlink(tmp_path)
    
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
    resultado = {}
    for _, row in df.iterrows():
        ejecutivo = row[columna_ejecutivo]
        valor = row[columna_valor]
        
        # Filtrar filas inválidas
        if pd.isna(ejecutivo) or ejecutivo == '':
            continue
        if isinstance(ejecutivo, str) and ('Filtros aplicados' in ejecutivo or ejecutivo == 'Total'):
            continue
        
        # Normalizar valor (siempre devuelve decimal 0-1)
        valor_normalizado = normalizar_valor(valor)
        
        # Convertir a porcentaje (multiplicar por 100)
        if valor_normalizado is not None:
            resultado[ejecutivo] = round(valor_normalizado * 100, 2)
        else:
            resultado[ejecutivo] = None
            
    return resultado
except Exception as e:
    print(f"Error procesando {kpi_nombre}: {e}")
    return {}
```

def unificar_datos_kpi(archivos_data: Dict[str, bytes], kpis_omitidos: list) -> list:
“””
Unifica los datos de todos los archivos KPI.
“””
datos_por_kpi = {}
for kpi_nombre, archivo_bytes in archivos_data.items():
if kpi_nombre not in kpis_omitidos:
datos_por_kpi[kpi_nombre] = procesar_archivo_kpi(archivo_bytes, kpi_nombre)

```
todos_ejecutivos = set()
for datos in datos_por_kpi.values():
    todos_ejecutivos.update(datos.keys())

registros = []
for ejecutivo in sorted(todos_ejecutivos):
    registro = {'ejecutivo': ejecutivo}
    for kpi_nombre in ['TMO', 'TransfEPA', 'Tipificaciones', 'SatEP', 'ResEP', 'SatSNL', 'ResSNL']:
        if kpi_nombre in kpis_omitidos:
            registro[kpi_nombre.lower()] = None
        else:
            registro[kpi_nombre.lower()] = datos_por_kpi.get(kpi_nombre, {}).get(ejecutivo, None)
    registros.append(registro)

return registros
```

async def enviar_a_n8n(registros: list, fecha_registro: str):
“””
Envía los registros al webhook de n8n para procesamiento.
“””
try:
import httpx

```
    fecha_obj = datetime.strptime(fecha_registro, '%Y-%m-%d')
    anio = fecha_obj.year
    meses_esp = ['ENERO', 'FEBRERO', 'MARZO', 'ABRIL', 'MAYO', 'JUNIO', 
                 'JULIO', 'AGOSTO', 'SEPTIEMBRE', 'OCTUBRE', 'NOVIEMBRE', 'DICIEMBRE']
    mes = meses_esp[fecha_obj.month - 1]
    
    payload = {
        "registros": registros,
        "fecha_registro": fecha_registro,
        "anio": anio,
        "mes": mes
    }
    
    n8n_webhook_url = "https://kpi-dashboard-n8n.f7jaui.easypanel.host/webhook/kpi-upload"
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(n8n_webhook_url, json=payload)
        
    if response.status_code == 200:
        result = response.json()
        return {"success": True, "data": result}
    else:
        return {"success": False, "error": f"Error en n8n: {response.status_code}"}
        
except Exception as e:
    print(f"Error llamando a n8n: {e}")
    return {"success": False, "error": str(e)}
```

@app.get(”/health”)
def health():
return {“status”: “ok”}

@app.post(”/detectar-kpi”)
async def detectar_kpi_endpoint(archivo: UploadFile = File(…)):
“”“Endpoint para detectar tipo de KPI de un archivo”””
try:
archivo_bytes = await archivo.read()
info = detectar_tipo_kpi(archivo_bytes)
return JSONResponse(content={“status”: “success”, “info”: info})
except Exception as e:
return JSONResponse(
status_code=500,
content={“status”: “error”, “detail”: str(e)}
)

@app.get(”/”, response_class=HTMLResponse)
def upload_form():
“”“Formulario HTML para subir archivos KPI con pre-lectura”””
return “””
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Carga de Archivos KPI - ACHS</title>
<style>
* {
margin: 0;
padding: 0;
box-sizing: border-box;
}

```
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background-color: #0a1929;
            color: #ffffff;
            min-height: 100vh;
            padding: 40px 20px;
        }
        
        .container {
            max-width: 800px;
            margin: 0 auto;
        }
        
        .header {
            background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%);
            padding: 32px;
            border-radius: 8px;
            margin-bottom: 32px;
        }
        
        .header h1 {
            font-size: 28px;
            font-weight: 600;
            margin-bottom: 8px;
        }
        
        .header p {
            color: #dcfce7;
            font-size: 14px;
        }
        
        .form-card {
            background-color: #1e293b;
            border-radius: 8px;
            padding: 32px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        }
        
        .form-group {
            margin-bottom: 24px;
        }
        
        .form-group label {
            display: block;
            color: #94a3b8;
            font-size: 12px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            font-weight: 500;
            margin-bottom: 8px;
        }
        
        .checkbox-wrapper {
            display: flex;
            align-items: center;
            gap: 8px;
            margin-top: 8px;
        }
        
        .checkbox-wrapper input[type="checkbox"] {
            width: 18px;
            height: 18px;
            cursor: pointer;
        }
        
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
        
        .file-input-wrapper:hover {
            border-color: #22c55e;
            background-color: #1e293b;
        }
        
        .file-input-wrapper.has-file {
            border-color: #22c55e;
            background-color: #064e3b;
        }
        
        .file-input-wrapper.disabled {
            opacity: 0.4;
            cursor: not-allowed;
            pointer-events: none;
        }
        
        .file-input-wrapper input[type="file"] {
            position: absolute;
            width: 100%;
            height: 100%;
            top: 0;
            left: 0;
            opacity: 0;
            cursor: pointer;
        }
        
        .file-label {
            color: #64748b;
            font-size: 14px;
            pointer-events: none;
        }
        
        .file-input-wrapper.has-file .file-label {
            color: #22c55e;
            font-weight: 500;
        }
        
        .file-detected-info {
            margin-top: 8px;
            padding: 8px 12px;
            background-color: #172554;
            border-left: 3px solid #3b82f6;
            border-radius: 4px;
            display: none;
        }
        
        .file-detected-info.show {
            display: block;
        }
        
        .file-detected-info p {
            color: #93c5fd;
            font-size: 12px;
            margin: 0;
        }
        
        .file-detected-info strong {
            color: #60a5fa;
        }
        
        .date-input {
            width: 100%;
            background-color: #0f172a;
            border: 1px solid #334155;
            border-radius: 6px;
            padding: 12px 16px;
            color: #ffffff;
            font-size: 14px;
        }
        
        .date-input:focus {
            outline: none;
            border-color: #22c55e;
        }
        
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
        
        .submit-btn:hover {
            transform: translateY(-2px);
        }
        
        .submit-btn:disabled {
            opacity: 0.5;
            cursor: not-allowed;
            transform: none;
        }
        
        .status {
            margin-top: 20px;
            padding: 16px;
            border-radius: 6px;
            display: none;
        }
        
        .status.success {
            background-color: #064e3b;
            border-left: 3px solid #22c55e;
            color: #22c55e;
        }
        
        .status.error {
            background-color: #7f1d1d;
            border-left: 3px solid #ef4444;
            color: #fca5a5;
        }
    </style>
</head>
<body>
    <div class="container">
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
        // Almacenar archivos cargados para poder volver sin perderlos
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
                
                // Guardar archivo en cache
                filesCache[kpiName] = file;
                
                // Detectar tipo de KPI
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
                    body: formData
                });
                
                const result = await response.json();
                
                if (response.ok && result.preview_url) {
                    window.location.href = result.preview_url;
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
"""
```

preview_data = {}

@app.post(”/upload”)
async def upload_files(
fecha_registro: str = Form(…),
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
omitir_res_snl: Optional[str] = Form(None)
):
“”“Endpoint para recibir los 7 archivos KPI y procesarlos”””

```
try:
    kpis_omitidos = []
    if omitir_tmo == 'on': kpis_omitidos.append('TMO')
    if omitir_transf_epa == 'on': kpis_omitidos.append('TransfEPA')
    if omitir_tipificaciones == 'on': kpis_omitidos.append('Tipificaciones')
    if omitir_sat_ep == 'on': kpis_omitidos.append('SatEP')
    if omitir_res_ep == 'on': kpis_omitidos.append('ResEP')
    if omitir_sat_snl == 'on': kpis_omitidos.append('SatSNL')
    if omitir_res_snl == 'on': kpis_omitidos.append('ResSNL')
    
    archivos_data = {}
    if tmo and 'TMO' not in kpis_omitidos:
        archivos_data['TMO'] = await tmo.read()
    if transf_epa and 'TransfEPA' not in kpis_omitidos:
        archivos_data['TransfEPA'] = await transf_epa.read()
    if tipificaciones and 'Tipificaciones' not in kpis_omitidos:
        archivos_data['Tipificaciones'] = await tipificaciones.read()
    if sat_ep and 'SatEP' not in kpis_omitidos:
        archivos_data['SatEP'] = await sat_ep.read()
    if res_ep and 'ResEP' not in kpis_omitidos:
        archivos_data['ResEP'] = await res_ep.read()
    if sat_snl and 'SatSNL' not in kpis_omitidos:
        archivos_data['SatSNL'] = await sat_snl.read()
    if res_snl and 'ResSNL' not in kpis_omitidos:
        archivos_data['ResSNL'] = await res_snl.read()
    
    registros = unificar_datos_kpi(archivos_data, kpis_omitidos)
    
    session_id = datetime.now().strftime('%Y%m%d%H%M%S')
    preview_data[session_id] = {
        'registros': registros,
        'fecha_registro': fecha_registro,
        'kpis_omitidos': kpis_omitidos
    }
    
    return JSONResponse(content={
        "status": "success",
        "preview_url": f"/preview/{session_id}"
    })
    
except Exception as e:
    return JSONResponse(
        status_code=500,
        content={"status": "error", "detail": str(e)}
    )
```

@app.get(”/preview/{session_id}”, response_class=HTMLResponse)
async def preview_data_view(session_id: str):
“”“Vista previa de datos antes de insertar en BD”””

```
if session_id not in preview_data:
    return "<h1>Sesión expirada</h1>"

data = preview_data[session_id]
registros = data['registros']
fecha_registro = data['fecha_registro']

filas_html = ""
for reg in registros:
    filas_html += f"""
    <tr>
        <td>{reg['ejecutivo']}</td>
        <td>{reg['tmo'] if reg['tmo'] is not None else '-'}</td>
        <td>{reg['transfepa'] if reg['transfepa'] is not None else '-'}</td>
        <td>{reg['tipificaciones'] if reg['tipificaciones'] is not None else '-'}</td>
        <td>{reg['satep'] if reg['satep'] is not None else '-'}</td>
        <td>{reg['resep'] if reg['resep'] is not None else '-'}</td>
        <td>{reg['satsnl'] if reg['satsnl'] is not None else '-'}</td>
        <td>{reg['ressnl'] if reg['ressnl'] is not None else '-'}</td>
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
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background-color: #0a1929;
            color: #ffffff;
            min-height: 100vh;
            padding: 40px 20px;
        }}
        
        .container {{
            max-width: 1400px;
            margin: 0 auto;
        }}
        
        .header {{
            background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%);
            padding: 32px;
            border-radius: 8px;
            margin-bottom: 32px;
        }}
        
        .header h1 {{
            font-size: 28px;
            font-weight: 600;
            margin-bottom: 8px;
        }}
        
        .header p {{
            color: #dcfce7;
            font-size: 14px;
        }}
        
        .info-card {{
            background-color: #1e293b;
            border-radius: 8px;
            padding: 20px 32px;
            margin-bottom: 24px;
            border-left: 4px solid #22c55e;
        }}
        
        .info-card p {{
            color: #94a3b8;
            font-size: 14px;
            margin-bottom: 8px;
        }}
        
        .info-card strong {{
            color: #ffffff;
        }}
        
        .table-card {{
            background-color: #1e293b;
            border-radius: 8px;
            padding: 24px;
            margin-bottom: 24px;
            overflow-x: auto;
        }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
        }}
        
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
        
        tr:hover {{
            background-color: #0f172a;
        }}
        
        .actions {{
            display: flex;
            gap: 16px;
            justify-content: center;
        }}
        
        .btn {{
            padding: 14px 32px;
            border-radius: 6px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            border: none;
            transition: transform 0.2s;
        }}
        
        .btn:hover {{
            transform: translateY(-2px);
        }}
        
        .btn-confirm {{
            background: linear-gradient(135deg, #22c55e 0%, #16a34a 100%);
            color: #ffffff;
        }}
        
        .btn-back {{
            background-color: #475569;
            color: #ffffff;
        }}
        
        .status {{
            margin-top: 20px;
            padding: 16px;
            border-radius: 6px;
            display: none;
            text-align: center;
        }}
        
        .status.success {{
            background-color: #064e3b;
            border-left: 3px solid #22c55e;
            color: #22c55e;
        }}
        
        .status.error {{
            background-color: #7f1d1d;
            border-left: 3px solid #ef4444;
            color: #fca5a5;
        }}
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
        async function confirmarInsercion() {{
            const status = document.getElementById('status');
            const btnConfirm = document.querySelector('.btn-confirm');
            
            btnConfirm.disabled = true;
            btnConfirm.textContent = 'Insertando...';
            
            try {{
                const response = await fetch('/confirm/{session_id}', {{
                    method: 'POST'
                }});
                
                const result = await response.json();
                
                if (response.ok) {{
                    status.className = 'status success';
                    status.textContent = '✓ Datos procesados correctamente';
                    status.style.display = 'block';
                    
                    setTimeout(() => {{
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
"""
```

@app.post(”/confirm/{session_id}”)
async def confirm_insertion(session_id: str):
“”“Confirmar e insertar datos vía n8n”””

```
if session_id not in preview_data:
    return JSONResponse(
        status_code=404,
        content={"status": "error", "detail": "Sesión no encontrada"}
    )

data = preview_data[session_id]

try:
    result = await enviar_a_n8n(data['registros'], data['fecha_registro'])
    
    if result["success"]:
        del preview_data[session_id]
        
        return JSONResponse(content={
            "status": "success",
            "message": "Datos procesados correctamente",
            "n8n_response": result.get("data", {})
        })
    else:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": result.get("error", "Error en n8n")}
        )
        
except Exception as e:
    return JSONResponse(
        status_code=500,
        content={"status": "error", "detail": str(e)}
    )
```
