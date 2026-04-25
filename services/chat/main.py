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

LLM_MODELS = [
    "gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-flash", "gemini-1.5-pro",
    "gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo",
    "llama3-8b-8192", "llama3-70b-8192", "mixtral-8x7b-32768",
]

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")  # gemini | openai | groq
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-2.0-flash")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")


class SessionCreate(BaseModel):
    client_id: Optional[str] = None
    agent_name: str = 'Kea'
    agent_role: str = 'Consultora Comercial'
    agent_tone: Literal['formal', 'friendly', 'technical', 'consultive'] = 'consultive'
    llm_model: Optional[str] = None  # None = usa o modelo do agente ativo


class SessionUpdate(BaseModel):
    id: str
    quote_id: Optional[str] = None
    agent_name: Optional[str] = None
    agent_role: Optional[str] = None
    agent_tone: Optional[Literal['formal', 'friendly', 'technical', 'consultive']] = None
    llm_model: Optional[str] = None


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

@app.on_event("startup")
def migrate():
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            ALTER TABLE chat_sessions
            ADD COLUMN IF NOT EXISTS llm_model VARCHAR(100) NULL
        """)
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        cursor.close()
        conn.close()


@app.get("/chat/health")
def health():
    return {
        "status": "ok",
        "llm_provider": LLM_PROVIDER,
        "llm_model": LLM_MODEL,
        "available_models": LLM_MODELS,
    }


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


@app.get("/chat/models")
def list_models():
    return {"models": LLM_MODELS}


@app.post("/chat/sessions", status_code=201)
def create_session(body: SessionCreate):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """INSERT INTO chat_sessions (client_id, agent_name, agent_role, agent_tone, llm_model)
               VALUES (%s, %s, %s, %s, %s)""",
            (body.client_id, body.agent_name, body.agent_role, body.agent_tone, body.llm_model)
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


# ── Messages (salva + chama Gemini 2.0 Flash) ────────────────────────────────

def _get_system_prompt(conn, override_model: Optional[str] = None) -> tuple[str, str]:
    """Retorna (system_prompt, llm_model). override_model da sessão tem prioridade."""
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(
            "SELECT system_prompt, name, role, tone, services, objections, closing_style, "
            "COALESCE(llm_model, 'gemini-2.0-flash') as llm_model "
            "FROM agent_profiles WHERE is_active = 1 LIMIT 1"
        )
        agent = cur.fetchone()
    finally:
        cur.close()
    if not agent:
        return (
            "Você é Kea, consultora comercial da KeaLabs — empresa de tecnologia "
            "especializada em sites web, automações, BI e agentes de IA. "
            "Seja objetiva, consultiva e sempre termine com um próximo passo concreto.",
            override_model or "gemini-2.0-flash"
        )
    model = override_model or agent.get('llm_model') or 'gemini-2.0-flash'
    if agent.get('system_prompt'):
        return agent['system_prompt'], model
    prompt = (
        f"Você é {agent['name']}, {agent['role']} da KeaLabs. "
        f"Tom: {agent['tone']}. Serviços: {agent['services']}. "
        f"Objeções: {agent['objections']}. Fechamento: {agent['closing_style']}."
    )
    return prompt, model


@app.post("/chat/messages", status_code=201)
def add_message(body: MessageCreate):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        # Valida sessão
        cursor.execute("SELECT * FROM chat_sessions WHERE id = %s", (body.session_id,))
        session = cursor.fetchone()
        if not session:
            raise HTTPException(404, "Sessão não encontrada. Inicie uma nova conversa.")

        # Salva mensagem do usuário
        cursor.execute(
            "INSERT INTO chat_messages (session_id, role, content) VALUES (%s, %s, %s)",
            (body.session_id, body.role, body.content)
        )
        conn.commit()
        cursor.execute("SELECT * FROM chat_messages WHERE id = LAST_INSERT_ID()")
        user_msg = cursor.fetchone()

        # Só chama LLM se for mensagem do usuário
        if body.role != 'user':
            return [user_msg]

        # llm_model da sessão tem prioridade sobre o do agente ativo
        session_model = session.get('llm_model') if session else None
        system_prompt, llm_model = _get_system_prompt(conn, override_model=session_model)

        # Busca histórico completo
        cursor.execute(
            "SELECT role, content FROM chat_messages "
            "WHERE session_id = %s ORDER BY sent_at ASC",
            (body.session_id,)
        )
        history = cursor.fetchall()

        reply = _call_llm(system_prompt, history, llm_model)

        # Salva resposta do modelo
        cursor.execute(
            "INSERT INTO chat_messages (session_id, role, content) VALUES (%s, 'model', %s)",
            (body.session_id, reply)
        )
        conn.commit()
        cursor.execute("SELECT * FROM chat_messages WHERE id = LAST_INSERT_ID()")
        ai_msg = cursor.fetchone()

        return [user_msg, ai_msg]

    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()


# ── LLM dispatcher ───────────────────────────────────────────────────────────

def _call_llm(system_prompt: str, history: list, llm_model: str) -> str:
    # Detecta provider pelo nome do modelo
    model = llm_model or LLM_MODEL
    if model.startswith('gemini'):
        provider = 'gemini'
    elif model.startswith('gpt'):
        provider = 'openai'
    else:
        provider = 'groq'

    if provider == "gemini":
        if not GEMINI_API_KEY:
            raise HTTPException(500, "GEMINI_API_KEY não configurada.")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": m['role'], "parts": [{"text": m['content']}]} for m in history],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 1024}
        }
        resp = httpx.post(url, json=payload, timeout=30)
        if resp.status_code != 200:
            raise HTTPException(502, f"Erro Gemini: {resp.text}")
        candidates = resp.json().get("candidates", [])
        if not candidates:
            raise HTTPException(502, "Gemini não retornou resposta.")
        return candidates[0]["content"]["parts"][0]["text"]

    if provider in ("openai", "groq"):
        api_key = OPENAI_API_KEY if provider == "openai" else GROQ_API_KEY
        if not api_key:
            raise HTTPException(500, f"{provider.upper()}_API_KEY não configurada.")
        base_url = (
            "https://api.openai.com/v1"
            if provider == "openai"
            else "https://api.groq.com/openai/v1"
        )
        messages = [{"role": "system", "content": system_prompt}] + [
            {"role": "assistant" if m['role'] == 'model' else m['role'], "content": m['content']}
            for m in history
        ]
        resp = httpx.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "messages": messages, "temperature": 0.7, "max_tokens": 1024},
            timeout=30
        )
        if resp.status_code != 200:
            raise HTTPException(502, f"Erro {provider}: {resp.text}")
        return resp.json()["choices"][0]["message"]["content"]

    raise HTTPException(500, f"Modelo '{model}' não suportado. Use gemini-*, gpt-* ou modelos Groq.")


# ── Completions (mantido por compatibilidade) ─────────────────────────────────

@app.post("/chat/completions")
def completions(body: CompletionRequest):
    result = add_message(MessageCreate(
        session_id=body.session_id, role='user', content=body.message
    ))
    msgs = result if isinstance(result, list) else [result]
    reply = next((m['content'] for m in msgs if m.get('role') == 'model'), '')
    return {"session_id": body.session_id, "reply": reply}
