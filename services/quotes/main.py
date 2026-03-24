from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Literal
import sys
sys.path.insert(0, '/app')
from database import get_db

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── Models ────────────────────────────────────────────────────────────────────

class BreakdownItem(BaseModel):
    item_key: str
    item_value: float


class DetailWeb(BaseModel):
    menu_count: int = 6
    include_asaas_integration: bool = False


class DetailMiniSite(BaseModel):
    page_count: int = 3
    include_instagram: bool = False
    include_whatsapp_button: bool = False


class DetailBI(BaseModel):
    complexity: Literal['standard', 'advanced'] = 'standard'
    sources: List[Literal['excel', 'api', 'database']] = []


class DetailAIAgent(BaseModel):
    plan: Literal['free', 'starter', 'pro', 'enterprise'] = 'free'
    agent_count: int = 1
    include_rag: bool = False
    include_voice: bool = False


class Modules(BaseModel):
    n8n_automation: bool = False
    whatsapp_gateway: bool = False
    agile_setup: bool = False
    agile_mentoring_hours: int = 0
    hosting_plan: Optional[Literal['single', 'premium', 'business', 'vps-starter', 'vps-pro', 'vps-ultra']] = None


class QuoteCreate(BaseModel):
    client_id: str
    service_type: Literal['WEB', 'BI', 'MINI_SITE', 'AI_AGENT']
    description: Optional[str] = None
    setup_value: float
    monthly_value: float
    breakdown: List[BreakdownItem] = []
    modules: Optional[Modules] = None
    detail_web: Optional[DetailWeb] = None
    detail_mini_site: Optional[DetailMiniSite] = None
    detail_bi: Optional[DetailBI] = None
    detail_ai_agent: Optional[DetailAIAgent] = None


class QuoteStatusUpdate(BaseModel):
    status: Literal['PENDING', 'APPROVED', 'REJECTED']
    note: Optional[str] = None


class AsaasUpdate(BaseModel):
    asaas_customer_id: Optional[str] = None
    asaas_charge_id: Optional[str] = None


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/quotes/health")
def health():
    return {"status": "ok"}


@app.get("/quotes")
def list_quotes(status: Optional[str] = None, service_type: Optional[str] = None):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        sql = "SELECT * FROM vw_quotes_full WHERE 1=1"
        params = []
        if status:
            sql += " AND status = %s"
            params.append(status)
        if service_type:
            sql += " AND service_type = %s"
            params.append(service_type)
        sql += " ORDER BY created_at DESC"
        cursor.execute(sql, params)
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


@app.get("/quotes/metrics/by-service")
def metrics_by_service():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM vw_metrics_by_service")
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


@app.get("/quotes/metrics/monthly")
def metrics_monthly():
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM vw_metrics_monthly")
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


@app.get("/quotes/{quote_id}")
def get_quote(quote_id: str):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT * FROM vw_quotes_full WHERE quote_id = %s", (quote_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(404, "Quote not found")

        cursor.execute("SELECT item_key, item_value FROM quote_breakdown WHERE quote_id = %s", (quote_id,))
        row['breakdown'] = cursor.fetchall()

        cursor.execute("SELECT * FROM quote_modules WHERE quote_id = %s", (quote_id,))
        row['modules'] = cursor.fetchone()

        if row['service_type'] == 'WEB':
            cursor.execute("SELECT * FROM quote_detail_web WHERE quote_id = %s", (quote_id,))
            row['detail'] = cursor.fetchone()
        elif row['service_type'] == 'MINI_SITE':
            cursor.execute("SELECT * FROM quote_detail_mini_site WHERE quote_id = %s", (quote_id,))
            row['detail'] = cursor.fetchone()
        elif row['service_type'] == 'BI':
            cursor.execute("SELECT * FROM quote_detail_bi WHERE quote_id = %s", (quote_id,))
            detail = cursor.fetchone()
            if detail:
                cursor.execute("SELECT source FROM quote_bi_sources WHERE quote_id = %s", (quote_id,))
                detail['sources'] = [r['source'] for r in cursor.fetchall()]
            row['detail'] = detail
        elif row['service_type'] == 'AI_AGENT':
            cursor.execute("SELECT * FROM quote_detail_ai_agent WHERE quote_id = %s", (quote_id,))
            row['detail'] = cursor.fetchone()

        return row
    finally:
        cursor.close()
        conn.close()


@app.get("/quotes/{quote_id}/history")
def get_quote_history(quote_id: str):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            "SELECT * FROM quote_status_history WHERE quote_id = %s ORDER BY changed_at ASC",
            (quote_id,)
        )
        return cursor.fetchall()
    finally:
        cursor.close()
        conn.close()


@app.post("/quotes", status_code=201)
def create_quote(body: QuoteCreate):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute(
            """INSERT INTO quotes (client_id, service_type, description, setup_value, monthly_value)
               VALUES (%s, %s, %s, %s, %s)""",
            (body.client_id, body.service_type, body.description, body.setup_value, body.monthly_value)
        )
        cursor.execute("SELECT LAST_INSERT_ID() as lid")
        # UUID-based — get by rowid trick won't work; fetch via client+service+created
        cursor.execute(
            "SELECT id FROM quotes WHERE client_id = %s AND service_type = %s ORDER BY created_at DESC LIMIT 1",
            (body.client_id, body.service_type)
        )
        quote_id = cursor.fetchone()['id']

        if body.breakdown:
            cursor.executemany(
                "INSERT INTO quote_breakdown (quote_id, item_key, item_value) VALUES (%s, %s, %s)",
                [(quote_id, b.item_key, b.item_value) for b in body.breakdown]
            )

        if body.modules:
            m = body.modules
            cursor.execute(
                """INSERT INTO quote_modules
                   (quote_id, n8n_automation, whatsapp_gateway, agile_setup, agile_mentoring_hours, hosting_plan)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (quote_id, m.n8n_automation, m.whatsapp_gateway, m.agile_setup, m.agile_mentoring_hours, m.hosting_plan)
            )

        if body.service_type == 'WEB' and body.detail_web:
            d = body.detail_web
            cursor.execute(
                "INSERT INTO quote_detail_web (quote_id, menu_count, include_asaas_integration) VALUES (%s, %s, %s)",
                (quote_id, d.menu_count, d.include_asaas_integration)
            )
        elif body.service_type == 'MINI_SITE' and body.detail_mini_site:
            d = body.detail_mini_site
            cursor.execute(
                """INSERT INTO quote_detail_mini_site
                   (quote_id, page_count, include_instagram, include_whatsapp_button)
                   VALUES (%s, %s, %s, %s)""",
                (quote_id, d.page_count, d.include_instagram, d.include_whatsapp_button)
            )
        elif body.service_type == 'BI' and body.detail_bi:
            d = body.detail_bi
            cursor.execute(
                "INSERT INTO quote_detail_bi (quote_id, complexity) VALUES (%s, %s)",
                (quote_id, d.complexity)
            )
            if d.sources:
                cursor.executemany(
                    "INSERT INTO quote_bi_sources (quote_id, source) VALUES (%s, %s)",
                    [(quote_id, s) for s in d.sources]
                )
        elif body.service_type == 'AI_AGENT' and body.detail_ai_agent:
            d = body.detail_ai_agent
            cursor.execute(
                """INSERT INTO quote_detail_ai_agent
                   (quote_id, plan, agent_count, include_rag, include_voice)
                   VALUES (%s, %s, %s, %s, %s)""",
                (quote_id, d.plan, d.agent_count, d.include_rag, d.include_voice)
            )

        conn.commit()
        return {"id": quote_id}
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()


@app.patch("/quotes/{quote_id}/status")
def update_status(quote_id: str, body: QuoteStatusUpdate):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT status FROM quotes WHERE id = %s", (quote_id,))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(404, "Quote not found")
        cursor.execute("UPDATE quotes SET status = %s WHERE id = %s", (body.status, quote_id))
        conn.commit()
        return {"id": quote_id, "status": body.status}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()


@app.patch("/quotes/{quote_id}/asaas")
def update_asaas(quote_id: str, body: AsaasUpdate):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE quotes SET asaas_customer_id = %s, asaas_charge_id = %s WHERE id = %s",
            (body.asaas_customer_id, body.asaas_charge_id, quote_id)
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(404, "Quote not found")
        return {"id": quote_id}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()


@app.delete("/quotes/{quote_id}", status_code=204)
def delete_quote(quote_id: str):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM quotes WHERE id = %s", (quote_id,))
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(404, "Quote not found")
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()
