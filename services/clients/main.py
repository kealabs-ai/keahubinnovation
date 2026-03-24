from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import sys
sys.path.insert(0, '/app')
from database import get_db

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class ClientCreate(BaseModel):
    name: str
    email: Optional[str] = None
    cpf_cnpj: Optional[str] = None
    phone: Optional[str] = None


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    cpf_cnpj: Optional[str] = None
    phone: Optional[str] = None


@app.get("/clients/health")
def health():
    return {"status": "ok"}


@app.get("/clients")
def list_clients():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM clients ORDER BY created_at DESC")
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


@app.get("/clients/{client_id}")
def get_client(client_id: str):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM clients WHERE id = %s", (client_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(404, "Client not found")
        return row
    finally:
        cursor.close()
        conn.close()


@app.post("/clients", status_code=201)
def create_client(body: ClientCreate):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "INSERT INTO clients (name, email, cpf_cnpj, phone) VALUES (%s, %s, %s, %s)",
            (body.name, body.email, body.cpf_cnpj, body.phone)
        )
        conn.commit()
        cursor.execute("SELECT * FROM clients WHERE id = LAST_INSERT_ID()")
        # UUID default — fetch by email or cpf_cnpj
        cursor.execute("SELECT * FROM clients WHERE name = %s ORDER BY created_at DESC LIMIT 1", (body.name,))
        return cursor.fetchone()
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()


@app.put("/clients/{client_id}")
def update_client(client_id: str, body: ClientUpdate):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        if not fields:
            raise HTTPException(400, "No fields to update")
        set_clause = ", ".join(f"{k} = %s" for k in fields)
        cursor.execute(
            f"UPDATE clients SET {set_clause} WHERE id = %s",
            (*fields.values(), client_id)
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(404, "Client not found")
        cursor.execute("SELECT * FROM clients WHERE id = %s", (client_id,))
        return cursor.fetchone()
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()


@app.delete("/clients/{client_id}", status_code=204)
def delete_client(client_id: str):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM clients WHERE id = %s", (client_id,))
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(404, "Client not found")
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()
