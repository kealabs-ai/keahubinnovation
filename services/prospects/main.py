from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Literal
import sys
sys.path.insert(0, '/app')
from database import get_db

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class ProspectCreate(BaseModel):
    name: str
    email: Optional[str] = None
    cpf_cnpj: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    source: Optional[Literal['instagram', 'whatsapp', 'site', 'indicacao', 'outro']] = 'outro'
    notes: Optional[str] = None


class ProspectUpdate(BaseModel):
    id: str
    name: Optional[str] = None
    email: Optional[str] = None
    cpf_cnpj: Optional[str] = None
    phone: Optional[str] = None
    company: Optional[str] = None
    source: Optional[Literal['instagram', 'whatsapp', 'site', 'indicacao', 'outro']] = None
    notes: Optional[str] = None
    status: Optional[Literal['NEW', 'CONTACTED', 'NEGOTIATING', 'APPROVED', 'REJECTED']] = None


class ProspectStatusUpdate(BaseModel):
    id: str
    status: Literal['NEW', 'CONTACTED', 'NEGOTIATING', 'APPROVED', 'REJECTED']
    notes: Optional[str] = None


class ProspectDelete(BaseModel):
    id: str


class ProspectConvert(BaseModel):
    id: str


@app.get("/prospects/health")
def health():
    return {"status": "ok"}


@app.get("/prospects")
def list_prospects(status: Optional[str] = None, source: Optional[str] = None):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        sql = "SELECT * FROM prospects WHERE 1=1"
        params = []
        if status:
            sql += " AND status = %s"
            params.append(status)
        if source:
            sql += " AND source = %s"
            params.append(source)
        sql += " ORDER BY created_at DESC"
        cursor.execute(sql, params)
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


@app.get("/prospects/metrics")
def metrics():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("""
            SELECT
                status,
                COUNT(*) AS total,
                COUNT(CASE WHEN DATE(created_at) = CURDATE() THEN 1 END) AS today
            FROM prospects
            GROUP BY status
        """)
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


@app.get("/prospects/{prospect_id}")
def get_prospect(prospect_id: str):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM prospects WHERE id = %s", (prospect_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(404, "Prospect not found")
        return row
    finally:
        cursor.close()
        conn.close()


@app.post("/prospects", status_code=201)
def create_prospect(body: ProspectCreate):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """INSERT INTO prospects (name, email, cpf_cnpj, phone, company, source, notes)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (body.name, body.email, body.cpf_cnpj, body.phone, body.company, body.source, body.notes)
        )
        conn.commit()
        cursor.execute("SELECT * FROM prospects WHERE name = %s ORDER BY created_at DESC LIMIT 1", (body.name,))
        return cursor.fetchone()
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()


@app.post("/prospects/update")
def update_prospect(body: ProspectUpdate):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        fields = {k: v for k, v in body.model_dump().items() if k != 'id' and v is not None}
        if not fields:
            raise HTTPException(400, "No fields to update")
        set_clause = ", ".join(f"{k} = %s" for k in fields)
        cursor.execute(
            f"UPDATE prospects SET {set_clause} WHERE id = %s",
            (*fields.values(), body.id)
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(404, "Prospect not found")
        cursor.execute("SELECT * FROM prospects WHERE id = %s", (body.id,))
        return cursor.fetchone()
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()


@app.post("/prospects/update-status")
def update_status(body: ProspectStatusUpdate):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id FROM prospects WHERE id = %s", (body.id,))
        if not cursor.fetchone():
            raise HTTPException(404, "Prospect not found")
        cursor.execute(
            "UPDATE prospects SET status = %s, notes = COALESCE(%s, notes) WHERE id = %s",
            (body.status, body.notes, body.id)
        )
        conn.commit()
        cursor.execute("SELECT * FROM prospects WHERE id = %s", (body.id,))
        return cursor.fetchone()
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()


@app.post("/prospects/convert")
def convert_to_client(body: ProspectConvert):
    """Aprova o prospect e cria o cliente na carteira de clientes."""
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM prospects WHERE id = %s", (body.id,))
        prospect = cursor.fetchone()
        if not prospect:
            raise HTTPException(404, "Prospect not found")
        if prospect['status'] == 'APPROVED':
            raise HTTPException(400, "Prospect already converted")

        # Verifica se já existe cliente com mesmo nome
        cursor.execute("SELECT id FROM clients WHERE name = %s LIMIT 1", (prospect['name'],))
        existing = cursor.fetchone()
        if existing:
            client_id = existing['id']
            cursor.execute(
                "UPDATE clients SET email=%s, cpf_cnpj=%s, phone=%s WHERE id=%s",
                (prospect['email'], prospect['cpf_cnpj'], prospect['phone'], client_id)
            )
        else:
            cursor.execute(
                "INSERT INTO clients (name, email, cpf_cnpj, phone) VALUES (%s, %s, %s, %s)",
                (prospect['name'], prospect['email'], prospect['cpf_cnpj'], prospect['phone'])
            )
            cursor.execute(
                "SELECT id FROM clients WHERE name = %s ORDER BY created_at DESC LIMIT 1",
                (prospect['name'],)
            )
            client_id = cursor.fetchone()['id']

        # Marca prospect como APPROVED e vincula ao client_id
        cursor.execute(
            "UPDATE prospects SET status = 'APPROVED', client_id = %s WHERE id = %s",
            (client_id, body.id)
        )
        conn.commit()

        cursor.execute("SELECT * FROM clients WHERE id = %s", (client_id,))
        client = cursor.fetchone()
        return {"prospect_id": body.id, "client_id": client_id, "client": client}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()


@app.post("/prospects/delete")
def delete_prospect(body: ProspectDelete):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM prospects WHERE id = %s", (body.id,))
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(404, "Prospect not found")
        return {"deleted": True, "id": body.id}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()
