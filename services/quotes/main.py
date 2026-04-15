from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List, Literal, Union
import sys, io
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
    installments: Optional[int] = 1
    interest_rate: Optional[float] = 0.0
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


# ── PDF Models ───────────────────────────────────────────────────────────────

class PdfRow(BaseModel):
    label: str
    value: str
    bold: Optional[bool] = False

class PdfSubtotal(BaseModel):
    label: str
    value: str

class PdfSection(BaseModel):
    title: str
    rows: List[PdfRow]
    subtotal: Optional[PdfSubtotal] = None

class PdfHostingRow(BaseModel):
    label: str
    spec: str
    price: str

class PdfPayload(BaseModel):
    clientName: str
    clientEmail: Optional[str] = None
    clientCpfCnpj: Optional[str] = None
    clientPhone: Optional[str] = None
    sections: List[PdfSection]
    hosting: Optional[List[PdfHostingRow]] = None
    setupValue: str
    clientCharge: str
    installments: int
    installmentValue: str
    totalCharge: str
    liquidMensal: str
    liquidAntecipado: str
    mdrInfo: str
    date: str


def _generate_pdf(p: PdfPayload) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_RIGHT, TA_CENTER
    import requests as req_lib

    ORANGE  = colors.HexColor('#EA580C')
    DARK    = colors.HexColor('#1F2937')
    GRAY    = colors.HexColor('#6B7280')
    LIGHT   = colors.HexColor('#FAFAFA')
    ORANGE_LIGHT = colors.HexColor('#FFF1E6')
    GREEN   = colors.HexColor('#22C55E')
    GREEN_LIGHT  = colors.HexColor('#F0FDF4')
    WHITE   = colors.white
    W, H    = A4

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
        leftMargin=14*mm, rightMargin=14*mm,
        topMargin=46*mm, bottomMargin=18*mm)

    # ── Logo via URL ──────────────────────────────────────────────────────────
    logo_img = None
    try:
        from reportlab.platypus import Image as RLImage
        r = req_lib.get('https://kealabs.cloud/assets/kealabs_logo_strategic-DId0Dtnm.png', timeout=5)
        logo_buf = io.BytesIO(r.content)
        logo_img = RLImage(logo_buf, width=44*mm, height=18*mm)
    except Exception:
        pass

    # ── Header (canvas) ───────────────────────────────────────────────────────
    def on_first_page(canvas, doc):
        canvas.saveState()
        # fundo laranja
        canvas.setFillColor(ORANGE)
        canvas.rect(0, H - 40*mm, W, 40*mm, fill=1, stroke=0)
        # faixa escura
        canvas.setFillColor(colors.HexColor('#B83700'))
        canvas.rect(0, H - 40*mm, W, 8*mm, fill=1, stroke=0)
        # logo
        if logo_img:
            logo_img.drawOn(canvas, 14*mm, H - 32*mm)
        else:
            canvas.setFillColor(WHITE)
            canvas.setFont('Helvetica-Bold', 20)
            canvas.drawString(14*mm, H - 24*mm, 'KeaLabs')
        # título direita
        canvas.setFillColor(WHITE)
        canvas.setFont('Helvetica-Bold', 13)
        canvas.drawRightString(W - 14*mm, H - 16*mm, 'Proposta Comercial')
        canvas.setFont('Helvetica', 8)
        canvas.drawRightString(W - 14*mm, H - 22*mm, p.date)
        # faixa inferior do header
        canvas.setFont('Helvetica-Oblique', 8)
        canvas.setFillColor(colors.HexColor('#FFFFFF99'))
        canvas.drawString(14*mm, H - 37*mm, 'Gerada automaticamente pelo sistema KeaFlow')
        canvas.setFont('Helvetica-Bold', 7)
        canvas.setFillColor(WHITE)
        canvas.drawRightString(W - 14*mm, H - 37*mm, 'VALIDA POR 15 DIAS')
        # footer
        canvas.setFillColor(ORANGE)
        canvas.rect(0, 0, W, 3*mm, fill=1, stroke=0)
        canvas.setFillColor(DARK)
        canvas.rect(0, 3*mm, W, 12*mm, fill=1, stroke=0)
        canvas.setFillColor(WHITE)
        canvas.setFont('Helvetica-Bold', 9)
        canvas.drawString(14*mm, 10*mm, 'KeaLabs')
        canvas.setFont('Helvetica', 7)
        canvas.setFillColor(colors.HexColor('#9CA3AF'))
        canvas.drawString(14*mm, 6*mm, 'kealabs.cloud - Tecnologia que transforma negocios')
        from datetime import datetime
        canvas.drawRightString(W - 14*mm, 8*mm, f'Gerado em {datetime.now().strftime("%d/%m/%Y %H:%M")}')
        canvas.restoreState()

    # ── Estilos ───────────────────────────────────────────────────────────────
    def sty(name, **kw):
        return ParagraphStyle(name, **kw)

    s_label  = sty('lbl',  fontSize=9,  textColor=GRAY,  fontName='Helvetica')
    s_value  = sty('val',  fontSize=9,  textColor=DARK,  fontName='Helvetica',      alignment=TA_RIGHT)
    s_bold   = sty('bold', fontSize=9,  textColor=DARK,  fontName='Helvetica-Bold', alignment=TA_RIGHT)
    s_orange = sty('org',  fontSize=9,  textColor=ORANGE,fontName='Helvetica-Bold', alignment=TA_RIGHT)
    s_sec    = sty('sec',  fontSize=8,  textColor=WHITE, fontName='Helvetica-Bold')
    s_client_lbl = sty('clbl', fontSize=7.5, textColor=ORANGE, fontName='Helvetica-Bold')
    s_client_val = sty('cval', fontSize=10,  textColor=DARK,   fontName='Helvetica-Bold')
    s_note   = sty('note', fontSize=8,  textColor=GRAY,  fontName='Helvetica', leading=13)
    s_card_lbl = sty('cdlbl', fontSize=7.5, textColor=WHITE, fontName='Helvetica-Bold', alignment=TA_CENTER)
    s_card_val = sty('cdval', fontSize=16,  textColor=WHITE, fontName='Helvetica-Bold', alignment=TA_CENTER)
    s_card_sub = sty('cdsub', fontSize=7.5, textColor=colors.HexColor('#FFFFFF99'), fontName='Helvetica', alignment=TA_CENTER)
    s_hosting_title = sty('htitle', fontSize=9, textColor=colors.HexColor('#166534'), fontName='Helvetica-Bold')
    s_hosting_sub   = sty('hsub',   fontSize=8, textColor=colors.HexColor('#166534'), fontName='Helvetica')

    col_w = W - 28*mm
    story = []

    # ── Cliente ───────────────────────────────────────────────────────────────
    client_data = [
        [Paragraph('CLIENTE', s_client_lbl),   Paragraph('E-MAIL', s_client_lbl),
         Paragraph('CPF / CNPJ', s_client_lbl), Paragraph('TELEFONE', s_client_lbl)],
        [Paragraph(p.clientName or '—', s_client_val),
         Paragraph(p.clientEmail or '—', s_client_val),
         Paragraph(p.clientCpfCnpj or '—', s_client_val),
         Paragraph(p.clientPhone or '—', s_client_val)],
    ]
    client_table = Table(client_data, colWidths=[col_w/4]*4)
    client_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#FFF7F3')),
        ('BOX',        (0,0), (-1,-1), 0.5, colors.HexColor('#FED7AA')),
        ('ROUNDEDCORNERS', [6]),
        ('TOPPADDING',    (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING',   (0,0), (-1,-1), 10),
        ('RIGHTPADDING',  (0,0), (-1,-1), 10),
    ]))
    story.append(client_table)
    story.append(Spacer(1, 5*mm))

    # ── Seções ────────────────────────────────────────────────────────────────
    for sec in p.sections:
        # cabeçalho da seção
        sec_header = Table([[Paragraph(sec.title.upper(), s_sec)]], colWidths=[col_w])
        sec_header.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,-1), ORANGE),
            ('TOPPADDING',    (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LEFTPADDING',   (0,0), (-1,-1), 8),
            ('ROUNDEDCORNERS', [4]),
        ]))
        story.append(sec_header)

        rows_data = []
        for i, row in enumerate(sec.rows):
            bg = LIGHT if i % 2 == 0 else WHITE
            val_style = s_bold if row.bold else s_value
            rows_data.append(([Paragraph(row.label, s_label), Paragraph(row.value, val_style)], bg))

        if rows_data:
            tdata = [r[0] for r in rows_data]
            t = Table(tdata, colWidths=[col_w*0.62, col_w*0.38])
            ts = TableStyle([
                ('BOX',           (0,0), (-1,-1), 0.3, colors.HexColor('#F0E8E0')),
                ('LINEBELOW',     (0,0), (-1,-2), 0.3, colors.HexColor('#F5EDE6')),
                ('TOPPADDING',    (0,0), (-1,-1), 5),
                ('BOTTOMPADDING', (0,0), (-1,-1), 5),
                ('LEFTPADDING',   (0,0), (-1,-1), 8),
                ('RIGHTPADDING',  (0,0), (-1,-1), 8),
            ])
            for i, (_, bg) in enumerate(rows_data):
                ts.add('BACKGROUND', (0,i), (-1,i), bg)
            t.setStyle(ts)
            story.append(t)

        if sec.subtotal:
            sub_t = Table(
                [[Paragraph(sec.subtotal.label, sty('sl', fontSize=9, textColor=ORANGE, fontName='Helvetica-Bold')),
                  Paragraph(sec.subtotal.value, s_orange)]],
                colWidths=[col_w*0.62, col_w*0.38]
            )
            sub_t.setStyle(TableStyle([
                ('BACKGROUND',    (0,0), (-1,-1), ORANGE_LIGHT),
                ('TOPPADDING',    (0,0), (-1,-1), 6),
                ('BOTTOMPADDING', (0,0), (-1,-1), 6),
                ('LEFTPADDING',   (0,0), (-1,-1), 8),
                ('RIGHTPADDING',  (0,0), (-1,-1), 8),
            ]))
            story.append(sub_t)
        story.append(Spacer(1, 4*mm))

    # ── Hospedagem ────────────────────────────────────────────────────────────
    if p.hosting:
        sec_header = Table([[Paragraph('HOSPEDAGEM — INCLUSA NO SERVICO', s_sec)]], colWidths=[col_w])
        sec_header.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,-1), ORANGE),
            ('TOPPADDING',    (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
            ('LEFTPADDING',   (0,0), (-1,-1), 8),
            ('ROUNDEDCORNERS', [4]),
        ]))
        story.append(sec_header)

        notice = Table(
            [[Paragraph('Hospedagem inclusa no servico contratado', s_hosting_title)],
             [Paragraph('Gerenciamento, manutencao e suporte sao de responsabilidade da KeaLabs.', s_hosting_sub)]],
            colWidths=[col_w]
        )
        notice.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,-1), GREEN_LIGHT),
            ('BOX',           (0,0), (-1,-1), 0.5, GREEN),
            ('TOPPADDING',    (0,0), (-1,-1), 6),
            ('BOTTOMPADDING', (0,0), (-1,-1), 6),
            ('LEFTPADDING',   (0,0), (-1,-1), 10),
            ('ROUNDEDCORNERS', [4]),
        ]))
        story.append(notice)

        h_data = []
        for i, h in enumerate(p.hosting):
            bg = LIGHT if i % 2 == 0 else WHITE
            h_data.append((
                [Paragraph(f'<b>{h.label}</b> — {h.spec}', s_label),
                 Paragraph(f'{h.price}/mes', s_bold)],
                bg
            ))
        if h_data:
            ht = Table([r[0] for r in h_data], colWidths=[col_w*0.62, col_w*0.38])
            hts = TableStyle([
                ('BOX',           (0,0), (-1,-1), 0.3, colors.HexColor('#F0E8E0')),
                ('LINEBELOW',     (0,0), (-1,-2), 0.3, colors.HexColor('#F5EDE6')),
                ('TOPPADDING',    (0,0), (-1,-1), 5),
                ('BOTTOMPADDING', (0,0), (-1,-1), 5),
                ('LEFTPADDING',   (0,0), (-1,-1), 8),
                ('RIGHTPADDING',  (0,0), (-1,-1), 8),
            ])
            for i, (_, bg) in enumerate(h_data):
                hts.add('BACKGROUND', (0,i), (-1,i), bg)
            ht.setStyle(hts)
            story.append(ht)

        badge = Table([[Paragraph('GERENCIADO PELA KEALABS', sty('gb', fontSize=7.5, textColor=WHITE, fontName='Helvetica-Bold'))]],
                      colWidths=[50*mm])
        badge.setStyle(TableStyle([
            ('BACKGROUND',    (0,0), (-1,-1), GREEN),
            ('TOPPADDING',    (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
            ('LEFTPADDING',   (0,0), (-1,-1), 8),
            ('ROUNDEDCORNERS', [10]),
        ]))
        story.append(Spacer(1, 2*mm))
        story.append(badge)
        story.append(Spacer(1, 4*mm))

    # ── Resumo Financeiro ─────────────────────────────────────────────────────
    story.append(Spacer(1, 2*mm))
    sum_header = Table([[Paragraph('RESUMO FINANCEIRO', s_sec)]], colWidths=[col_w])
    sum_header.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), ORANGE),
        ('TOPPADDING',    (0,0), (-1,-1), 5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ('LEFTPADDING',   (0,0), (-1,-1), 8),
        ('ROUNDEDCORNERS', [4]),
    ]))
    story.append(sum_header)
    story.append(Spacer(1, 3*mm))

    half = (col_w - 4*mm) / 2
    cards = Table(
        [[
            Table(
                [[Paragraph('SETUP LIQUIDO', s_card_lbl)],
                 [Paragraph(p.setupValue, s_card_val)],
                 [Paragraph('valor liquido para a KeaLabs', s_card_sub)]],
                colWidths=[half]
            ),
            Table(
                [[Paragraph('COBRAR DO CLIENTE', s_card_lbl)],
                 [Paragraph(f'{p.installments}x {p.installmentValue}', s_card_val)],
                 [Paragraph(f'total {p.totalCharge}', s_card_sub)]],
                colWidths=[half]
            ),
        ]],
        colWidths=[half, half], spaceBefore=0
    )
    cards.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (0,0), ORANGE),
        ('BACKGROUND', (1,0), (1,0), DARK),
        ('TOPPADDING',    (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ('LEFTPADDING',   (0,0), (-1,-1), 8),
        ('RIGHTPADDING',  (0,0), (-1,-1), 8),
        ('ROUNDEDCORNERS', [6]),
    ]))
    story.append(cards)
    story.append(Spacer(1, 3*mm))

    notes = Table(
        [[Paragraph(f'<b>Detalhes do parcelamento:</b><br/>{p.mdrInfo}<br/>'
                    f'Liquido mes a mes: <b>{p.liquidMensal}</b> &nbsp;|&nbsp; '
                    f'Liquido antecipado (2 dias): <b>{p.liquidAntecipado}</b>', s_note)]],
        colWidths=[col_w]
    )
    notes.setStyle(TableStyle([
        ('BACKGROUND',    (0,0), (-1,-1), colors.HexColor('#FAFAF9')),
        ('BOX',           (0,0), (-1,-1), 0.5, colors.HexColor('#E5E0D8')),
        ('TOPPADDING',    (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 8),
        ('LEFTPADDING',   (0,0), (-1,-1), 10),
        ('RIGHTPADDING',  (0,0), (-1,-1), 10),
        ('ROUNDEDCORNERS', [4]),
    ]))
    story.append(notes)

    doc.build(story, onFirstPage=on_first_page, onLaterPages=on_first_page)
    return buf.getvalue()


@app.post("/quotes/pdf")
def generate_pdf(body: PdfPayload):
    try:
        pdf_bytes = _generate_pdf(body)
    except Exception as e:
        raise HTTPException(500, f"Erro ao gerar PDF: {e}")
    slug = body.clientName.replace(' ', '-').lower() or 'kealabs'
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type='application/pdf',
        headers={'Content-Disposition': f'attachment; filename="proposta-{slug}.pdf"'}
    )


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

        installments = body.installments or 1
        interest_rate = body.interest_rate or 0.0
        total_with_interest = round(setup_value * (1 + interest_rate / 100), 2) if interest_rate else setup_value
        installment_value = round(total_with_interest / installments, 2) if installments > 1 else total_with_interest

        cursor.execute(
            """INSERT INTO quotes (client_id, service_type, setup_value, monthly_value, installments, interest_rate, installment_value)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (client_id, st, setup_value, monthly_value, installments, interest_rate, installment_value)
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
