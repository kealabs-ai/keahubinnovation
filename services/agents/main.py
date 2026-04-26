from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Literal
import sys
sys.path.insert(0, '/app')
from database import get_db

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

LLM_MODELS = [
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-2.5-flash-preview-05-20",
    "gemini-2.5-pro-preview-06-05",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
    "gemini-1.5-pro",
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-3.5-turbo",
    "llama3-8b-8192",
    "llama3-70b-8192",
    "mixtral-8x7b-32768",
]


# ── Migration: garante coluna llm_model na tabela ─────────────────────────────
@app.on_event("startup")
def migrate():
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            ALTER TABLE agent_profiles
            ADD COLUMN IF NOT EXISTS llm_model VARCHAR(100)
            NOT NULL DEFAULT 'gemini-2.0-flash'
        """)
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        cursor.close()
        conn.close()


class AgentCreate(BaseModel):
    name: str = 'Kea'
    company: str = 'KeaLabs'
    role: str = 'Consultora Comercial'
    tone: Literal['formal', 'friendly', 'technical', 'consultive'] = 'consultive'
    services: str
    objections: str
    closing_style: str
    system_prompt: Optional[str] = None
    llm_model: str = 'gemini-2.0-flash'
    is_active: bool = True


class AgentUpdate(BaseModel):
    id: str
    name: Optional[str] = None
    company: Optional[str] = None
    role: Optional[str] = None
    tone: Optional[Literal['formal', 'friendly', 'technical', 'consultive']] = None
    services: Optional[str] = None
    objections: Optional[str] = None
    closing_style: Optional[str] = None
    system_prompt: Optional[str] = None
    llm_model: Optional[str] = None
    is_active: Optional[bool] = None


class AgentDelete(BaseModel):
    id: str


@app.get("/agents/health")
def health():
    return {"status": "ok", "available_models": LLM_MODELS}


@app.get("/agents")
def list_agents(active_only: bool = False):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        sql = "SELECT * FROM agent_profiles"
        if active_only:
            sql += " WHERE is_active = 1"
        sql += " ORDER BY created_at DESC"
        cursor.execute(sql)
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


@app.get("/agents/active")
def get_active_agent():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM agent_profiles WHERE is_active = 1 LIMIT 1")
        row = cursor.fetchone()
        if not row:
            raise HTTPException(404, "No active agent found")
        return row
    finally:
        cursor.close()
        conn.close()


@app.get("/agents/models")
def list_models():
    return {"models": LLM_MODELS}


@app.get("/agents/{agent_id}")
def get_agent(agent_id: str):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM agent_profiles WHERE id = %s", (agent_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(404, "Agent not found")
        return row
    finally:
        cursor.close()
        conn.close()


@app.post("/agents", status_code=201)
def create_agent(body: AgentCreate):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """INSERT INTO agent_profiles
               (name, company, role, tone, services, objections, closing_style,
                system_prompt, llm_model, is_active)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (body.name, body.company, body.role, body.tone,
             body.services, body.objections, body.closing_style,
             body.system_prompt, body.llm_model, body.is_active)
        )
        conn.commit()
        cursor.execute("SELECT * FROM agent_profiles ORDER BY created_at DESC LIMIT 1")
        return cursor.fetchone()
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()


@app.post("/agents/update")
def update_agent(body: AgentUpdate):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        fields = {k: v for k, v in body.model_dump().items() if k != 'id' and v is not None}
        if not fields:
            raise HTTPException(400, "No fields to update")
        set_clause = ", ".join(f"{k} = %s" for k in fields)
        cursor.execute(
            f"UPDATE agent_profiles SET {set_clause} WHERE id = %s",
            (*fields.values(), body.id)
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(404, "Agent not found")
        cursor.execute("SELECT * FROM agent_profiles WHERE id = %s", (body.id,))
        return cursor.fetchone()
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()


@app.post("/agents/delete")
def delete_agent(body: AgentDelete):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM agent_profiles WHERE id = %s", (body.id,))
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(404, "Agent not found")
        return {"deleted": True, "id": body.id}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()
