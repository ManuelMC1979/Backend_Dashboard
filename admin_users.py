# admin_users.py
# CRUD de usuarios para rol admin
# Endpoints: GET/POST/PUT/DELETE /api/admin/users

from fastapi import APIRouter, HTTPException, Header
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, EmailStr
from datetime import datetime
import bcrypt

import mysql.connector
from mysql.connector import Error
from config import DB_CONFIG

# Importar TOKENS y ROLE_MAP del módulo principal de auth
from api_dashboard import TOKENS, ROLE_MAP

router = APIRouter()


# --- SCHEMAS PYDANTIC ---

class UserOutAdmin(BaseModel):
    id: int
    rut: Optional[str] = None
    nombre: str
    nombre_mostrar: Optional[str] = None
    correo: Optional[str] = None
    rol: str
    role_id: int
    is_active: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class UserCreateAdmin(BaseModel):
    rut: str
    nombre: str
    nombre_mostrar: Optional[str] = None
    correo: Optional[str] = None
    password: str
    role_id: int
    is_active: Optional[int] = 1

class UserUpdateAdmin(BaseModel):
    rut: Optional[str] = None
    nombre: Optional[str] = None
    nombre_mostrar: Optional[str] = None
    correo: Optional[str] = None
    password: Optional[str] = None
    role_id: Optional[int] = None
    is_active: Optional[int] = None


# --- HELPERS ---

def get_db_conn():
    try:
        return mysql.connector.connect(**DB_CONFIG)
    except Error as e:
        raise HTTPException(status_code=500, detail=f"Error conexión BD: {e}")


def get_current_user_from_token(authorization: str = Header(None)) -> Dict[str, Any]:
    """Obtiene el usuario actual desde el token en header Authorization: Bearer <token>"""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="No autenticado")
    
    token = authorization.split(" ", 1)[1]
    session = TOKENS.get(token)
    
    if not session:
        raise HTTPException(status_code=401, detail="Token inválido")
    
    if session["expires_at"] < datetime.utcnow():
        TOKENS.pop(token, None)
        raise HTTPException(status_code=401, detail="Token expirado")
    
    conn = get_db_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT id, nombre, correo, role_id, is_active FROM users WHERE id = %s", (session["user_id"],))
        user = cur.fetchone()
        if not user:
            raise HTTPException(status_code=401, detail="Usuario no encontrado")
        user["rol"] = ROLE_MAP.get(int(user["role_id"]), "ejecutivo")
        return user
    finally:
        cur.close()
        conn.close()


def require_admin(authorization: str = Header(None)) -> Dict[str, Any]:
    """Verifica que el usuario actual sea admin (role_id=99)"""
    user = get_current_user_from_token(authorization)
    if user["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Solo admin puede acceder")
    return user


def hash_password(plain: str) -> str:
    """Genera hash bcrypt de password"""
    if len(plain.encode("utf-8")) > 72:
        raise HTTPException(status_code=400, detail="Password demasiado largo (max 72 bytes)")
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


# --- ENDPOINTS CRUD ---

@router.get("/users", response_model=List[UserOutAdmin])
def list_users(authorization: str = Header(None)):
    """Lista todos los usuarios (solo admin)"""
    require_admin(authorization)
    
    conn = get_db_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            SELECT id, rut, nombre, nombre_mostrar, correo, role_id, is_active, created_at, updated_at
            FROM users
            ORDER BY id
        """)
        users = cur.fetchall()
        
        result = []
        for u in users:
            result.append({
                "id": u["id"],
                "rut": u.get("rut"),
                "nombre": u["nombre"],
                "nombre_mostrar": u.get("nombre_mostrar"),
                "correo": u.get("correo"),
                "rol": ROLE_MAP.get(int(u["role_id"]), "ejecutivo"),
                "role_id": u["role_id"],
                "is_active": u["is_active"],
                "created_at": u.get("created_at"),
                "updated_at": u.get("updated_at"),
            })
        
        print(f"[admin/users] list ok count={len(result)}")
        return result
    finally:
        cur.close()
        conn.close()


@router.post("/users", response_model=UserOutAdmin, status_code=201)
def create_user(data: UserCreateAdmin, authorization: str = Header(None)):
    """Crea un nuevo usuario (solo admin)"""
    require_admin(authorization)
    
    # Validar password
    if not data.password or len(data.password) < 6:
        raise HTTPException(status_code=400, detail="Password debe tener al menos 6 caracteres")
    
    pw_hash = hash_password(data.password)
    correo = data.correo.lower().strip() if data.correo else None
    
    conn = get_db_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("""
            INSERT INTO users (rut, nombre, nombre_mostrar, correo, password_hash, role_id, is_active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
        """, (
            data.rut.strip(),
            data.nombre.strip(),
            data.nombre_mostrar.strip() if data.nombre_mostrar else None,
            correo,
            pw_hash,
            data.role_id,
            data.is_active if data.is_active is not None else 1
        ))
        conn.commit()
        user_id = cur.lastrowid
        
        # Obtener usuario creado
        cur.execute("""
            SELECT id, rut, nombre, nombre_mostrar, correo, role_id, is_active, created_at, updated_at
            FROM users WHERE id = %s
        """, (user_id,))
        u = cur.fetchone()
        
        print(f"[admin/users] create ok id={user_id}")
        return {
            "id": u["id"],
            "rut": u.get("rut"),
            "nombre": u["nombre"],
            "nombre_mostrar": u.get("nombre_mostrar"),
            "correo": u.get("correo"),
            "rol": ROLE_MAP.get(int(u["role_id"]), "ejecutivo"),
            "role_id": u["role_id"],
            "is_active": u["is_active"],
            "created_at": u.get("created_at"),
            "updated_at": u.get("updated_at"),
        }
    except Error as e:
        conn.rollback()
        if "Duplicate entry" in str(e):
            raise HTTPException(status_code=400, detail="El correo ya existe")
        raise HTTPException(status_code=500, detail=f"Error creando usuario: {e}")
    finally:
        cur.close()
        conn.close()


@router.put("/users/{user_id}", response_model=UserOutAdmin)
def update_user(user_id: int, data: UserUpdateAdmin, authorization: str = Header(None)):
    """Actualiza un usuario (solo admin)"""
    require_admin(authorization)
    
    fields = []
    values = []
    
    if data.rut is not None:
        fields.append("rut = %s")
        values.append(data.rut.strip())
    
    if data.nombre is not None:
        fields.append("nombre = %s")
        values.append(data.nombre.strip())
    
    if data.nombre_mostrar is not None:
        fields.append("nombre_mostrar = %s")
        values.append(data.nombre_mostrar.strip() if data.nombre_mostrar else None)
    
    if data.correo is not None:
        fields.append("correo = %s")
        values.append(data.correo.lower().strip() if data.correo else None)
    
    if data.role_id is not None:
        fields.append("role_id = %s")
        values.append(data.role_id)
    
    if data.is_active is not None:
        fields.append("is_active = %s")
        values.append(data.is_active)
    
    if data.password is not None and data.password:
        if len(data.password) < 6:
            raise HTTPException(status_code=400, detail="Password debe tener al menos 6 caracteres")
        fields.append("password_hash = %s")
        values.append(hash_password(data.password))
    
    if not fields:
        raise HTTPException(status_code=400, detail="Nada que actualizar")
    
    fields.append("updated_at = NOW()")
    values.append(user_id)
    
    sql = f"UPDATE users SET {', '.join(fields)} WHERE id = %s"
    
    conn = get_db_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, tuple(values))
        conn.commit()
        
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        
        # Obtener usuario actualizado
        cur.execute("""
            SELECT id, rut, nombre, nombre_mostrar, correo, role_id, is_active, created_at, updated_at
            FROM users WHERE id = %s
        """, (user_id,))
        u = cur.fetchone()
        
        print(f"[admin/users] update ok id={user_id}")
        return {
            "id": u["id"],
            "rut": u.get("rut"),
            "nombre": u["nombre"],
            "nombre_mostrar": u.get("nombre_mostrar"),
            "correo": u.get("correo"),
            "rol": ROLE_MAP.get(int(u["role_id"]), "ejecutivo"),
            "role_id": u["role_id"],
            "is_active": u["is_active"],
            "created_at": u.get("created_at"),
            "updated_at": u.get("updated_at"),
        }
    except Error as e:
        conn.rollback()
        if "Duplicate entry" in str(e):
            raise HTTPException(status_code=400, detail="El correo ya existe")
        raise HTTPException(status_code=500, detail=f"Error actualizando usuario: {e}")
    finally:
        cur.close()
        conn.close()


@router.delete("/users/{user_id}", response_model=UserOutAdmin)
def disable_user(user_id: int, authorization: str = Header(None)):
    """Desactiva un usuario (is_active=0), NO lo borra físicamente (solo admin)"""
    require_admin(authorization)
    
    conn = get_db_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("UPDATE users SET is_active = 0, updated_at = NOW() WHERE id = %s", (user_id,))
        conn.commit()
        
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        
        # Obtener usuario desactivado
        cur.execute("""
            SELECT id, rut, nombre, nombre_mostrar, correo, role_id, is_active, created_at, updated_at
            FROM users WHERE id = %s
        """, (user_id,))
        u = cur.fetchone()
        
        print(f"[admin/users] disable ok id={user_id}")
        return {
            "id": u["id"],
            "rut": u.get("rut"),
            "nombre": u["nombre"],
            "nombre_mostrar": u.get("nombre_mostrar"),
            "correo": u.get("correo"),
            "rol": ROLE_MAP.get(int(u["role_id"]), "ejecutivo"),
            "role_id": u["role_id"],
            "is_active": u["is_active"],
            "created_at": u.get("created_at"),
            "updated_at": u.get("updated_at"),
        }
    finally:
        cur.close()
        conn.close()
