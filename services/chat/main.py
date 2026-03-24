from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Literal
import sys
sys.path.append('..')
from database import get_db

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class SessionCreate(BaseModel):
    client_id: Optional[str] = None
    agent_name: str = 'Kea'
    agent_role: str = 'Consultora Comercial'
    agent_tone: Literal['formal', 'friendly', 'technical', 'consultive'] = 'consultive'


class SessionUpdate(BaseModel):
    quote_id: Optional[str] = None
    agent_name: Optional[str] = None
    agent_role: Optional[str] = None
    agent_tone: Optional[Literal['formal', 'friendly', 'technical', 'consultive']] = None


class MessageCreate(BaseModel):
    role: Literal['user', 'model']
    content: str


@app.get("/chat/health")
def health():
    return {"status": "ok"}


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


@app.patch("/chat/sessions/{session_id}")
def update_session(session_id: str, body: SessionUpdate):
    conn = get_db()
    cursor = conn.cursor()
    try:
        fields = {k: v for k, v in body.model_dump().items() if v is not None}
        if not fields:
            raise HTTPException(400, "No fields to update")
        set_clause = ", ".join(f"{k} = %s" for k in fields)
        cursor.execute(
            f"UPDATE chat_sessions SET {set_clause} WHERE id = %s",
            (*fields.values(), session_id)
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(404, "Session not found")
        return {"id": session_id}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
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


@app.post("/chat/sessions/{session_id}/messages", status_code=201)
def add_message(session_id: str, body: MessageCreate):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id FROM chat_sessions WHERE id = %s", (session_id,))
        if not cursor.fetchone():
            raise HTTPException(404, "Session not found")
        cursor.execute(
            "INSERT INTO chat_messages (session_id, role, content) VALUES (%s, %s, %s)",
            (session_id, body.role, body.content)
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


@app.delete("/chat/sessions/{session_id}", status_code=204)
def delete_session(session_id: str):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM chat_sessions WHERE id = %s", (session_id,))
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(404, "Session not found")
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()
