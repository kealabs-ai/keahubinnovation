from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Literal, Union
import sys
sys.path.insert(0, '/app')
from database import get_db

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


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


# ── Frontend DTO ──────────────────────────────────────────────────────────────

class FrontendModules(BaseModel):
    n8nAutomation: Optional[bool] = False
    whatsappGateway: Optional[bool] = False
    agileSetup: Optional[bool] = False
    agileMentoringHours: Optional[int] = 0
    hosting: Optional[str] = None


class WebPricingInput(BaseModel):
    serviceType: Literal['WEB']
    menuCount: int = 6
    includeAsaasIntegration: bool = False
    modules: Optional[FrontendModules] = None


class BIPricingInput(BaseModel):
    serviceType: Literal['BI']
    sources: List[Literal['excel', 'api', 'database']] = []
    complexity: Literal['standard', 'advanced'] = 'standard'
    modules: Optional[FrontendModules] = None


class MiniSitePricingInput(BaseModel):
    serviceType: Literal['MINI_SITE']
    pageCount: int = 3
    includeInstagram: bool = False
    includeWhatsappButton: bool = False
    modules: Optional[FrontendModules] = None


class AIAgentPricingInput(BaseModel):
    serviceType: Literal['AI_AGENT']
    plan: Literal['free', 'starter', 'pro', 'enterprise'] = 'free'
    agentCount: int = 1
    includeRAG: bool = False
    includeVoice: bool = False
    modules: Optional[FrontendModules] = None


class CreateQuoteDTO(BaseModel):
    clientName: str
    clientEmail: Optional[str] = None
    clientCpfCnpj: Optional[str] = None
    clientPhone: Optional[str] = None
    pricing: Union[WebPricingInput, BIPricingInput, MiniSitePricingInput, AIAgentPricingInput]


def _get_settings(cursor) -> dict:
    cursor.execute("SELECT setting_key, setting_value FROM system_settings")
    return {r['setting_key']: float(r['setting_value']) if r['setting_value'].replace('.','',1).isdigit() else r['setting_value']
            for r in cursor.fetchall()}


def _calc_pricing(pricing, s: dict) -> tuple[float, float, list]:
    """Returns (setup, monthly, breakdown_items)"""
    breakdown = []
    modules = pricing.modules or FrontendModules()
    st = pricing.serviceType

    if st == 'WEB':
        base = s.get('web_base', 1500)
        breakdown.append(('Base Web', base))
        extra_menus = max(0, pricing.menuCount - int(s.get('web_free_menus', 6)))
        if extra_menus:
            v = extra_menus * s.get('web_extra_menu_price', 100)
            breakdown.append((f'Menus extras ({extra_menus})', v))
            base += v
        if pricing.includeAsaasIntegration:
            v = s.get('web_asaas_integration', 300)
            breakdown.append(('Integração Asaas', v))
            base += v
        setup = base

    elif st == 'MINI_SITE':
        base = s.get('mini_site_base', 800)
        breakdown.append(('Base Mini Site', base))
        extra_pages = max(0, pricing.pageCount - int(s.get('mini_site_free_pages', 3)))
        if extra_pages:
            v = extra_pages * s.get('mini_site_extra_page', 150)
            breakdown.append((f'Páginas extras ({extra_pages})', v))
            base += v
        if pricing.includeInstagram:
            v = s.get('mini_site_instagram', 200)
            breakdown.append(('Instagram', v))
            base += v
        if pricing.includeWhatsappButton:
            v = s.get('mini_site_whatsapp', 100)
            breakdown.append(('Botão WhatsApp', v))
            base += v
        setup = base

    elif st == 'BI':
        bi_prices = {'excel': s.get('bi_excel', 800), 'api': s.get('bi_api', 1200), 'database': s.get('bi_database', 1500)}
        base = sum(bi_prices[src] for src in pricing.sources)
        for src in pricing.sources:
            breakdown.append((f'BI {src.capitalize()}', bi_prices[src]))
        if pricing.complexity == 'advanced':
            mult = s.get('bi_advanced_multiplier', 1.3)
            base = round(base * mult, 2)
            breakdown.append(('Multiplicador Advanced', round(base * (mult - 1), 2)))
        setup = base

    elif st == 'AI_AGENT':
        plan_keys = {'free': 'agent_free', 'starter': 'agent_starter', 'pro': 'agent_pro', 'enterprise': 'agent_enterprise'}
        pk = plan_keys[pricing.plan]
        setup = s.get(f'{pk}_setup', 0)
        breakdown.append((f'Plano {pricing.plan.capitalize()}', setup))
        extra_agents = max(0, pricing.agentCount - 1)
        if extra_agents:
            v = extra_agents * s.get('agent_extra_agent_price', 400)
            breakdown.append((f'Agentes extras ({extra_agents})', v))
            setup += v
        if pricing.includeRAG:
            v = s.get('agent_rag', 500)
            breakdown.append(('Base de Conhecimento RAG', v))
            setup += v
        if pricing.includeVoice:
            v = s.get('agent_voice', 400)
            breakdown.append(('Canal de Voz', v))
            setup += v
    else:
        setup = 0

    # Módulos
    if modules.n8nAutomation:
        v = s.get('module_n8n', 500)
        breakdown.append(('n8n Automation', v))
        setup += v
    if modules.whatsappGateway:
        v = s.get('module_whatsapp', 400)
        breakdown.append(('WhatsApp Gateway', v))
        setup += v
    if modules.agileSetup:
        v = s.get('module_agile_setup', 600)
        breakdown.append(('Agile Setup', v))
        setup += v
    if modules.agileMentoringHours and modules.agileMentoringHours > 0:
        v = modules.agileMentoringHours * s.get('module_mentoring_hour', 200)
        breakdown.append((f'Mentoria ({modules.agileMentoringHours}h)', v))
        setup += v

    hosting_prices = {
        'single': s.get('hosting_single', 30), 'premium': s.get('hosting_premium', 60),
        'business': s.get('hosting_business', 100), 'vps-starter': s.get('hosting_vps_starter', 150),
        'vps-pro': s.get('hosting_vps_pro', 250), 'vps-ultra': s.get('hosting_vps_ultra', 400),
    }
    hosting_monthly = 0
    if modules.hosting and modules.hosting in hosting_prices:
        hosting_monthly = hosting_prices[modules.hosting]
        breakdown.append((f'Hospedagem {modules.hosting}', hosting_monthly))

    agent_monthly = 0
    if st == 'AI_AGENT':
        plan_keys = {'free': 'agent_free', 'starter': 'agent_starter', 'pro': 'agent_pro', 'enterprise': 'agent_enterprise'}
        agent_monthly = s.get(f"{plan_keys[pricing.plan]}_monthly", 0)

    monthly = round(setup * s.get('monthly_support_rate', 0.15) + hosting_monthly + agent_monthly, 2)
    setup = round(setup, 2)

    return setup, monthly, [{'item_key': k, 'item_value': v} for k, v in breakdown]


class QuoteStatusUpdate(BaseModel):
    id: str
    status: Literal['PENDING', 'APPROVED', 'REJECTED']
    note: Optional[str] = None


class AsaasUpdate(BaseModel):
    id: str
    asaas_customer_id: Optional[str] = None
    asaas_charge_id: Optional[str] = None


class QuoteDelete(BaseModel):
    id: str


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
def create_quote(body: CreateQuoteDTO):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        settings = _get_settings(cursor)
        setup_value, monthly_value, breakdown = _calc_pricing(body.pricing, settings)
        st = body.pricing.serviceType
        modules = body.pricing.modules or FrontendModules()

        # Upsert client
        cursor.execute("SELECT id FROM clients WHERE name = %s LIMIT 1", (body.clientName,))
        row = cursor.fetchone()
        if row:
            client_id = row['id']
            cursor.execute(
                "UPDATE clients SET email=%s, cpf_cnpj=%s, phone=%s WHERE id=%s",
                (body.clientEmail, body.clientCpfCnpj, body.clientPhone, client_id)
            )
        else:
            cursor.execute(
                "INSERT INTO clients (name, email, cpf_cnpj, phone) VALUES (%s, %s, %s, %s)",
                (body.clientName, body.clientEmail, body.clientCpfCnpj, body.clientPhone)
            )
            cursor.execute("SELECT id FROM clients WHERE name = %s ORDER BY created_at DESC LIMIT 1", (body.clientName,))
            client_id = cursor.fetchone()['id']

        cursor.execute(
            "INSERT INTO quotes (client_id, service_type, setup_value, monthly_value) VALUES (%s, %s, %s, %s)",
            (client_id, st, setup_value, monthly_value)
        )
        cursor.execute(
            "SELECT id FROM quotes WHERE client_id = %s AND service_type = %s ORDER BY created_at DESC LIMIT 1",
            (client_id, st)
        )
        quote_id = cursor.fetchone()['id']

        if breakdown:
            cursor.executemany(
                "INSERT INTO quote_breakdown (quote_id, item_key, item_value) VALUES (%s, %s, %s)",
                [(quote_id, b['item_key'], b['item_value']) for b in breakdown]
            )

        cursor.execute(
            """INSERT INTO quote_modules
               (quote_id, n8n_automation, whatsapp_gateway, agile_setup, agile_mentoring_hours, hosting_plan)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (quote_id, modules.n8nAutomation, modules.whatsappGateway, modules.agileSetup,
             modules.agileMentoringHours or 0, modules.hosting)
        )

        if st == 'WEB':
            cursor.execute(
                "INSERT INTO quote_detail_web (quote_id, menu_count, include_asaas_integration) VALUES (%s, %s, %s)",
                (quote_id, body.pricing.menuCount, body.pricing.includeAsaasIntegration)
            )
        elif st == 'MINI_SITE':
            cursor.execute(
                """INSERT INTO quote_detail_mini_site
                   (quote_id, page_count, include_instagram, include_whatsapp_button)
                   VALUES (%s, %s, %s, %s)""",
                (quote_id, body.pricing.pageCount, body.pricing.includeInstagram, body.pricing.includeWhatsappButton)
            )
        elif st == 'BI':
            cursor.execute(
                "INSERT INTO quote_detail_bi (quote_id, complexity) VALUES (%s, %s)",
                (quote_id, body.pricing.complexity)
            )
            if body.pricing.sources:
                cursor.executemany(
                    "INSERT INTO quote_bi_sources (quote_id, source) VALUES (%s, %s)",
                    [(quote_id, src) for src in body.pricing.sources]
                )
        elif st == 'AI_AGENT':
            cursor.execute(
                """INSERT INTO quote_detail_ai_agent
                   (quote_id, plan, agent_count, include_rag, include_voice)
                   VALUES (%s, %s, %s, %s, %s)""",
                (quote_id, body.pricing.plan, body.pricing.agentCount,
                 body.pricing.includeRAG, body.pricing.includeVoice)
            )

        conn.commit()
        cursor.execute("SELECT * FROM vw_quotes_full WHERE quote_id = %s", (quote_id,))
        return cursor.fetchone()
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()


@app.post("/quotes/update-status")
def update_status(body: QuoteStatusUpdate):
    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    try:
        cursor.execute("SELECT status FROM quotes WHERE id = %s", (body.id,))
        if not cursor.fetchone():
            raise HTTPException(404, "Quote not found")
        cursor.execute("UPDATE quotes SET status = %s WHERE id = %s", (body.status, body.id))
        conn.commit()
        return {"id": body.id, "status": body.status}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()


@app.post("/quotes/update-asaas")
def update_asaas(body: AsaasUpdate):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE quotes SET asaas_customer_id = %s, asaas_charge_id = %s WHERE id = %s",
            (body.asaas_customer_id, body.asaas_charge_id, body.id)
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(404, "Quote not found")
        return {"id": body.id}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()


@app.post("/quotes/delete")
def delete_quote(body: QuoteDelete):
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM quotes WHERE id = %s", (body.id,))
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(404, "Quote not found")
        return {"deleted": True, "id": body.id}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(400, str(e))
    finally:
        cursor.close()
        conn.close()
