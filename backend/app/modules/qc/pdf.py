"""Render only the form snapshot stored on the QC, never the current registry."""
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape
from app.modules.qc.forms import document_id
from app.core.performance import measure, record
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, LongTable, TableStyle, Flowable, KeepTogether

FONT = '/usr/share/fonts/truetype/dejavu/'


class Signature(Flowable):
    def __init__(self, strokes):
        super().__init__()
        self.strokes = strokes
        self.width, self.height = 240, 80

    def draw(self):
        self.canv.setStrokeColor(colors.HexColor('#183a68'))
        self.canv.setLineWidth(1.4)
        for stroke in self.strokes:
            path = self.canv.beginPath()
            for index, (x,y) in enumerate(stroke):
                (path.moveTo if index == 0 else path.lineTo)(x*self.width, (1-y)*self.height)
            self.canv.drawPath(path)


@measure('pdf.render_reportlab')
def render_pdf(obj):
    for name, file in [('QC','DejaVuSans.ttf'), ('QC-Bold','DejaVuSans-Bold.ttf')]:
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(Path(FONT)/file)))
    data = obj.form_data
    form_id = data.get('document_id') or document_id(obj.id)
    snapshot, entered, signer = data['definition'], data['input'], data['signer']
    styles = getSampleStyleSheet()
    normal = ParagraphStyle('QCText', fontName='QC', fontSize=8, leading=12, spaceAfter=3)
    heading = ParagraphStyle('QCHeading', parent=normal, fontName='QC-Bold', fontSize=16, leading=22)
    def p(value, style=normal):
        return Paragraph(escape(str(value or '')).replace('\n','<br/>'), style)
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=landscape(A4), leftMargin=28, rightMargin=28,
                            topMargin=28, bottomMargin=30, title=form_id, author=signer['name'])
    context = data['context']
    story = [p('NAPACO ERP - PHIẾU KIỂM TRA CHẤT LƯỢNG', heading), p(form_id+' | Phiếu QC: '+obj.id),
             p(snapshot['name']+' | '+snapshot['code']+' | Phiên bản '+str(snapshot['version'])),
             p('Đối tượng: '+context['object_id']+' | Nhựa: '+entered['resin']+' | Số lượng kiểm tra: '+context['quantity']),
             p('Ngày kiểm tra: '+context['checked_at']), Spacer(1,10)]
    rows = [[p(value) for value in ['Hạng mục kiểm tra','Tiêu chuẩn kỹ thuật','Phương pháp đo','Kết quả thực tế','Đánh giá','Dung sai / Ghi chú']]]
    answers = {item['id']:item for item in entered['answers']}
    for criterion in snapshot['criteria']:
        answer = answers[criterion['id']]
        rows.append([p(criterion['name']), p(criterion['standard']), p(criterion['method']),
                     p('' if answer['assessment']=='NA' else answer['actual']+(' '+criterion['unit'] if criterion['unit'] and answer['actual'] else '')),
                     p('Không áp dụng' if answer['assessment']=='NA' else answer['assessment']),
                     p(answer['note'] if snapshot.get('tolerance_as_hint') else criterion['tolerance']+('\n'+answer['note'] if answer['note'] else ''))])
    table = LongTable(rows, colWidths=[125,130,115,140,65,doc.width-575], repeatRows=1, splitInRow=1)
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#dce7f8')),
        ('GRID',(0,0),(-1,-1),.4,colors.HexColor('#b5c4d8')), ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(-1,-1),7), ('RIGHTPADDING',(0,0),(-1,-1),7),
        ('TOPPADDING',(0,0),(-1,-1),7), ('BOTTOMPADDING',(0,0),(-1,-1),7)]))
    story.extend([table, Spacer(1,12), p('Kết luận: '+entered['conclusion']), p('Ghi chú: '+entered['note']),
                  p(snapshot.get('applicability_note','')), Spacer(1,8)])
    story.append(KeepTogether([p('NGƯỜI KIỂM TRA XÁC NHẬN'), Signature(entered['signature']),
        p(signer['name']+' | Mã người dùng: '+signer['user_id']), p('Thời điểm ký (UTC): '+signer['signed_at']),
        p('Chữ ký xác nhận nội bộ được ghi nhận từ tài khoản ERP; không phải chữ ký số chứng thư.')]))
    def footer(canvas, document):
        canvas.setFont('QC', 8)
        canvas.drawString(28,16,form_id+' | '+snapshot['code'])
        canvas.drawRightString(landscape(A4)[0]-28,16,'Trang '+str(document.page))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    content = output.getvalue()
    record('pdf.output', 0, bytes=len(content))
    return content
