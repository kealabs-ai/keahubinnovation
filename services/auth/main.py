from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional, Literal
import sys, os, jwt, bcrypt, secrets
from datetime import datetime, timedelta
sys.path.insert(0, '/app')
from database import get_db

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

security = HTTPBearer()
JWT_SECRET = os.getenv("JWT_SECRET", "changeme")
JWT_EXPIRY_HOURS = int(os.getenv("JWT_EXPIRY_HOURS", 8))


# ── Models ────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    name: str
    email: str
    password: str
    role: Literal['admin', 'vendedor', 'usuario'] = 'usuario'

class UserUpdate(BaseModel):
    id: str
    name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[Literal['admin', 'vendedor', 'usuario']] = None
    active: Optional[bool] = None

class UserDelete(BaseModel):
    id: str

class ChangePassword(BaseModel):
    email: str
    current_password: str
    new_password: str

    def validate_fields(self):
        if not self.email or not self.current_password or not self.new_password:
            raise HTTPException(400, "Todos os campos são obrigatórios")

class LoginDTO(BaseModel):
    email: str
    password: str

class RefreshTokenDTO(BaseModel):
    refresh_token: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def _verify(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())

def _create_token(user: dict) -> str:
    payload = {
        "sub": user["id"],
        "name": user["name"],
        "email": user["email"],
        "role": user["role"],
        "type": "access",
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def _create_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "type": "refresh",
        "exp": datetime.utcnow() + timedelta(days=30)
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")

def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expirado")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Token inválido")

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    return _decode_token(credentials.credentials)

def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "Acesso restrito a administradores")
    return user


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/auth/health")
def health():
    return {"status": "ok"}


@app.post("/auth/login")
def login(body: LoginDTO):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM auth_users WHERE email = %s AND active = 1", (body.email,))
        user = cursor.fetchone()
        if not user or not _verify(body.password, user["password_hash"]):
            raise HTTPException(401, "Credenciais inválidas")

        cursor.execute(
            "UPDATE auth_users SET last_login = NOW() WHERE id = %s", (user["id"],)
        )
        conn.commit()

        token = _create_token(user)
        return {
            "access_token": token,
            "refresh_token": _create_refresh_token(user["id"]),
            "token_type": "bearer",
            "expires_in": JWT_EXPIRY_HOURS * 3600,
            "user": {
                "id": user["id"],
                "name": user["name"],
                "email": user["email"],
                "role": user["role"]
            }
        }
    finally:
        cursor.close()
        conn.close()


@app.get("/auth/me")
def me(user: dict = Depends(get_current_user)):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, name, email, role, active, last_login, created_at FROM auth_users WHERE id = %s",
            (user["sub"],)
        )
        row = cursor.fetchone()
        if not row:
            raise HTTPException(404, "Usuário não encontrado")
        return row
    finally:
        cursor.close()
        conn.close()


@app.post("/auth/validate")
def validate_token(user: dict = Depends(get_current_user)):
    if user.get("type") != "access":
        raise HTTPException(401, "Token inválido para autenticação")
    return {"valid": True, "user": user}


@app.post("/auth/refresh")
def refresh_token(body: RefreshTokenDTO):
    payload = _decode_token(body.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(401, "Token de refresh inválido")

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT * FROM auth_users WHERE id = %s AND active = 1", (payload["sub"],)
        )
        user = cursor.fetchone()
        if not user:
            raise HTTPException(401, "Usuário inativo ou não encontrado")

        return {
            "access_token": _create_token(user),
            "refresh_token": _create_refresh_token(user["id"]),
            "token_type": "bearer"
        }
    finally:
        cursor.close()
        conn.close()


@app.get("/auth/users")
def list_users(user: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT id, name, email, role, active, last_login, created_at FROM auth_users ORDER BY created_at DESC"
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


@app.post("/auth/users", status_code=201)
def create_user(body: UserCreate, user: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id FROM auth_users WHERE email = %s", (body.email,))
        if cursor.fetchone():
            raise HTTPException(400, "E-mail já cadastrado")

        cursor.execute(
            "INSERT INTO auth_users (name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
            (body.name, body.email, _hash(body.password), body.role)
        )
        conn.commit()
        cursor.execute(
            "SELECT id, name, email, role, active, created_at FROM auth_users WHERE email = %s", (body.email,)
        )
        return cursor.fetchone()
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()


@app.post("/auth/users/update")
def update_user(body: UserUpdate, user: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        fields = {k: v for k, v in body.model_dump().items() if k != "id" and v is not None}
        if not fields:
            raise HTTPException(400, "Nenhum campo para atualizar")
        set_clause = ", ".join(f"{k} = %s" for k in fields)
        cursor.execute(
            f"UPDATE auth_users SET {set_clause} WHERE id = %s",
            (*fields.values(), body.id)
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(404, "Usuário não encontrado")
        cursor.execute(
            "SELECT id, name, email, role, active, created_at FROM auth_users WHERE id = %s", (body.id,)
        )
        return cursor.fetchone()
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()


@app.post("/auth/users/change-password")
def change_password(body: ChangePassword):
    body.validate_fields()
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, password_hash FROM auth_users WHERE email = %s", (body.email,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(404, "Usuário não encontrado")
        if not _verify(body.current_password, row["password_hash"]):
            raise HTTPException(401, "Senha atual incorreta")
        cursor.execute(
            "UPDATE auth_users SET password_hash = %s WHERE id = %s",
            (_hash(body.new_password), row["id"])
        )
        conn.commit()
        return {"updated": True, "id": row["id"]}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()


@app.post("/auth/users/delete")
def delete_user(body: UserDelete, user: dict = Depends(require_admin)):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM auth_users WHERE id = %s", (body.id,))
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(404, "Usuário não encontrado")
        return {"deleted": True, "id": body.id}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()
