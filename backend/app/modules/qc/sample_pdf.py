"""Attach the two sample confirmations to the same template-derived QC PDF."""
from io import BytesIO
from xml.sax.saxutils import escape
from fastapi import HTTPException
from pypdf import PdfReader,PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,KeepTogether
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from app.modules.qc.pdf import Signature


def append_confirmations(content,saved):
    from app.modules.production.sample_service import SAMPLE,DECISIONS
    sample=saved[SAMPLE]
    if sample['state']!='signed' or set(sample['signatures'])!={'technical','qc'}:
        raise HTTPException(409,'Chỉ xuất phiếu mẫu đủ hai xác nhận; phiếu hủy không được xuất bản dùng chạy.')
    if 'QC-Sample' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('QC-Sample','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
    style=ParagraphStyle('SampleProof',fontName='QC-Sample',fontSize=10,leading=15,spaceAfter=6)
    def p(value):return Paragraph(escape(str(value or '')).replace('\n','<br/>'),style)
    context=saved['context'];output=BytesIO()
    story=[p('XÁC NHẬN KIỂM MẪU — '+context['qc_id']),
        p('LSX: '+context['production_order_id']+' · Máy: '+context['machine_id']),
        p('CTĐH: '+context['order_line_ids']),p('Đợt chạy: '+context['setup_id']),
        p('Kết luận: '+context['conclusion']+' · Quyết định: '+DECISIONS[sample['decision']]),
        p('Nội dung / phương án xử lý: '+context['qc_note']),Spacer(1,12)]
    for role,label in [('technical','KỸ THUẬT XÁC NHẬN'),('qc','QC XÁC NHẬN')]:
        entry=sample['signatures'][role];proof=entry['proof']
        story.append(KeepTogether([p(label),Signature(entry['strokes']),
            p(proof['name']+' · '+proof['email']),p('Ký lúc UTC: '+proof['signed_at']),
            p('Dấu nội dung: '+proof['content_hash']),p('Dấu xác nhận: '+proof['nonce']),Spacer(1,12)]))
    story.append(p('Trang xác nhận thuộc cùng phiếu QC và bản chụp template; không dùng lại để mở chạy cho đợt khác.'))
    SimpleDocTemplate(output,pagesize=A4,leftMargin=36,rightMargin=36,topMargin=36,bottomMargin=36).build(story)
    writer=PdfWriter(clone_from=PdfReader(BytesIO(content)))
    for page in PdfReader(BytesIO(output.getvalue())).pages:writer.add_page(page)
    result=BytesIO();writer.write(result);return result.getvalue()
