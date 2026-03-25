from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Literal
import os
import httpx
import sys
sys.path.insert(0, '/app')
from database import get_db

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"


class SessionCreate(BaseModel):
    client_id: Optional[str] = None
    agent_name: str = 'Kea'
    agent_role: str = 'Consultora Comercial'
    agent_tone: Literal['formal', 'friendly', 'technical', 'consultive'] = 'consultive'


class SessionUpdate(BaseModel):
    id: str
    quote_id: Optional[str] = None
    agent_name: Optional[str] = None
    agent_role: Optional[str] = None
    agent_tone: Optional[Literal['formal', 'friendly', 'technical', 'consultive']] = None


class SessionDelete(BaseModel):
    id: str


class MessageCreate(BaseModel):
    session_id: str
    role: Literal['user', 'model']
    content: str


class CompletionRequest(BaseModel):
    session_id: str
    message: str


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/chat/health")
def health():
    return {"status": "ok"}


# ── Sessions ──────────────────────────────────────────────────────────────────

@app.get("/chat/sessions")
def list_sessions(client_id: Optional[str] = None):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        sql = "SELECT * FROM chat_sessions WHERE 1=1"
        params = []
        if client_id:
            sql += " AND client_id = %s"
            params.append(client_id)
        sql += " ORDER BY created_at DESC"
        cursor.execute(sql, params)
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


@app.get("/chat/sessions/{session_id}")
def get_session(session_id: str):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM chat_sessions WHERE id = %s", (session_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(404, "Session not found")
        return row
    finally:
        cursor.close()
        conn.close()


@app.get("/chat/sessions/{session_id}/messages")
def list_messages(session_id: str):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT * FROM chat_messages WHERE session_id = %s ORDER BY sent_at ASC",
            (session_id,)
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


@app.post("/chat/sessions", status_code=201)
def create_session(body: SessionCreate):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """INSERT INTO chat_sessions (client_id, agent_name, agent_role, agent_tone)
               VALUES (%s, %s, %s, %s)""",
            (body.client_id, body.agent_name, body.agent_role, body.agent_tone)
        )
        conn.commit()
        cursor.execute(
            "SELECT * FROM chat_sessions WHERE client_id <=> %s ORDER BY created_at DESC LIMIT 1",
            (body.client_id,)
        )
        return cursor.fetchone()
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()


@app.post("/chat/sessions/update")
def update_session(body: SessionUpdate):
    conn = get_db()
    cursor = conn.cursor()
    try:
        fields = {k: v for k, v in body.model_dump().items() if k != 'id' and v is not None}
        if not fields:
            raise HTTPException(400, "No fields to update")
        set_clause = ", ".join(f"{k} = %s" for k in fields)
        cursor.execute(
            f"UPDATE chat_sessions SET {set_clause} WHERE id = %s",
            (*fields.values(), body.id)
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(404, "Session not found")
        return {"id": body.id}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()


@app.post("/chat/sessions/delete")
def delete_session(body: SessionDelete):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM chat_sessions WHERE id = %s", (body.id,))
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(404, "Session not found")
        return {"deleted": True, "id": body.id}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()


# ── Messages ──────────────────────────────────────────────────────────────────

@app.post("/chat/messages", status_code=201)
def add_message(body: MessageCreate):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id FROM chat_sessions WHERE id = %s", (body.session_id,))
        if not cursor.fetchone():
            raise HTTPException(404, "Session not found")
        cursor.execute(
            "INSERT INTO chat_messages (session_id, role, content) VALUES (%s, %s, %s)",
            (body.session_id, body.role, body.content)
        )
        conn.commit()
        cursor.execute("SELECT * FROM chat_messages WHERE id = LAST_INSERT_ID()")
        return cursor.fetchone()
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()


# ── Completions (Gemini Flash) ────────────────────────────────────────────────

@app.post("/chat/completions")
def completions(body: CompletionRequest):
    if not GEMINI_API_KEY:
        raise HTTPException(500, "GEMINI_API_KEY not configured")

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        # 1. Valida sessão
        cursor.execute("SELECT * FROM chat_sessions WHERE id = %s", (body.session_id,))
        session = cursor.fetchone()
        if not session:
            raise HTTPException(404, "Session not found")

        # 2. Busca system_prompt do agente ativo
        cursor.execute("SELECT system_prompt, name, role, tone, services, objections, closing_style FROM agent_profiles WHERE is_active = 1 LIMIT 1")
        agent = cursor.fetchone()
        if agent and agent['system_prompt']:
            system_prompt = agent['system_prompt']
        elif agent:
            system_prompt = (
                f"Você é {agent['name']}, {agent['role']} da KeaLabs. "
                f"Tom: {agent['tone']}. "
                f"Serviços: {agent['services']}. "
                f"Objeções: {agent['objections']}. "
                f"Fechamento: {agent['closing_style']}."
            )
        else:
            system_prompt = "Você é Kea, consultora comercial da KeaLabs. Seja objetiva e consultiva."

        # 3. Salva mensagem do usuário
        cursor.execute(
            "INSERT INTO chat_messages (session_id, role, content) VALUES (%s, 'user', %s)",
            (body.session_id, body.message)
        )
        conn.commit()

        # 4. Busca histórico completo da sessão
        cursor.execute(
            "SELECT role, content FROM chat_messages WHERE session_id = %s ORDER BY sent_at ASC",
            (body.session_id,)
        )
        history = cursor.fetchall()

        # 5. Monta payload Gemini
        contents = [{"role": msg['role'], "parts": [{"text": msg['content']}]} for msg in history]
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": contents,
            "generationConfig": {
                "temperature": 0.7,
                "maxOutputTokens": 1024
            }
        }

        # 6. Chama Gemini Flash
        response = httpx.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            json=payload,
            timeout=30
        )
        if response.status_code != 200:
            raise HTTPException(502, f"Gemini error: {response.text}")

        reply = response.json()["candidates"][0]["content"]["parts"][0]["text"]

        # 7. Salva resposta do modelo
        cursor.execute(
            "INSERT INTO chat_messages (session_id, role, content) VALUES (%s, 'model', %s)",
            (body.session_id, reply)
        )
        conn.commit()

        return {"session_id": body.session_id, "reply": reply}

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()
