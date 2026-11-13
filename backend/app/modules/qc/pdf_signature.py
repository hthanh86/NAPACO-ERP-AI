"""Locate an approved signature region in Google's PDF; fail closed on ambiguity."""
from io import BytesIO
from fastapi import HTTPException
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from app.core.performance import measure


@measure('pdf.signature_overlay')
def apply_signature(content, data, marker, background):
    if not content.startswith(b'%PDF-') or len(content) < 1000:
        raise HTTPException(502, 'Google chưa trả về PDF hợp lệ hoặc PDF rỗng.')
    reader = PdfReader(BytesIO(content))
    found = []
    for index, page in enumerate(reader.pages):
        state = {'color':None,'stack':[],'points':[]}
        def visitor(op,args,cm,tm):
            if op == b'q':state['stack'].append(state['color'])
            elif op == b'Q':state['color']=state['stack'].pop() if state['stack'] else None
            elif op == b'rg':state['color']=tuple(float(x) for x in args[:3])
            elif op in {b'g',b'k',b'sc',b'scn'}:state['color']=None
            color=state['color']
            selected=color is not None and all(abs(a-b)<0.003 for a,b in zip(color,marker))
            def point(x,y):return (float(x)*cm[0]+float(y)*cm[2]+cm[4],float(x)*cm[1]+float(y)*cm[3]+cm[5])
            if op == b're':
                x,y,w,h=map(float,args);state['points']=[point(x,y),point(x+w,y+h),point(x+w,y),point(x,y+h)] if selected else []
            elif op == b'm':state['points']=[point(*args)] if selected else []
            elif op == b'l' and selected:state['points'].append(point(*args))
            elif op in {b'f',b'f*',b'B',b'B*'}:
                if selected and state['points']:
                    points=state['points'];xs=[p[0] for p in points];ys=[p[1] for p in points]
                    if max(xs)-min(xs)>5 and max(ys)-min(ys)>5:found.append((index,(min(xs),min(ys),max(xs),max(ys))))
                state['points']=[]
            elif op == b'n':state['points']=[]
        page.extract_text(visitor_operand_before=visitor)
    if not found or len({p for p,_ in found}) != 1:
        raise HTTPException(502, 'Không xác định chắc vùng chữ ký trên PDF Google. Chưa lưu PDF; kiểm tra mapping vùng ký và thử lại.')
    page_index=found[0][0]
    x0=min(b[0] for _,b in found);y0=min(b[1] for _,b in found);x1=max(b[2] for _,b in found);y1=max(b[3] for _,b in found)
    # Multiple unrelated regions must never become one guessed rectangle.
    if any(not (b[0] <= x0+1 and b[2] >= x1-1) for _,b in found):
        raise HTTPException(502, 'Vùng chữ ký PDF bị chia hoặc trùng màu định vị. Không xuất chữ ký vào vị trí suy đoán.')
    bottom=None
    for _,box in sorted(found,key=lambda item:item[1][1]):
        if bottom is not None and box[1]>bottom+1:
            raise HTTPException(502,'Vùng định vị chữ ký không liên tục. Chưa lưu PDF để tránh ghép sai vị trí.')
        bottom=max(bottom or box[3],box[3])
    if x1-x0 < 65 or y1-y0 < 28:
        raise HTTPException(422, 'Vùng chữ ký quá nhỏ. Cần quản lý chọn một vùng lớn hơn trên template.')
    page=reader.pages[page_index];out=BytesIO()
    c=canvas.Canvas(out,pagesize=(float(page.mediabox.width),float(page.mediabox.height)))
    c.setFillColorRGB(*background);c.rect(x0+.1,y0+.1,x1-x0-.2,y1-y0-.2,fill=1,stroke=0)
    strokes=data['input']['signature'];points=[p for stroke in strokes for p in stroke]
    min_x,max_x=min(p[0] for p in points),max(p[0] for p in points)
    min_y,max_y=min(p[1] for p in points),max(p[1] for p in points)
    sx=max((max_x-min_x)*900,1);sy=max((max_y-min_y)*240,1)
    scale=min((x1-x0-10)/sx,(y1-y0-18)/sy)
    left=x0+(x1-x0-sx*scale)/2;bottom=y0+14+(y1-y0-18-sy*scale)/2
    ink=(.08,.16,.28) if sum(background)/3>.4 else (.95,.95,.95)
    c.setStrokeColorRGB(*ink);c.setLineWidth(.8)
    for stroke in strokes:
        path=c.beginPath()
        for i,(x,y) in enumerate(stroke):
            (path.moveTo if i==0 else path.lineTo)(left+(x-min_x)*900*scale,bottom+(max_y-y)*240*scale)
        c.drawPath(path)
    if 'QC-Signature' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('QC-Signature','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
    label=data['signer']['name'];font_size=min(8,(x1-x0-8)/max(pdfmetrics.stringWidth(label,'QC-Signature',1),1))
    if font_size < 4:
        raise HTTPException(422, 'Vùng chữ ký không đủ rộng để hiển thị tên người ký.')
    c.setFillColorRGB(*ink);c.setFont('QC-Signature',font_size)
    c.drawCentredString((x0+x1)/2,y0+4,label);c.save()
    # pypdf 7 requires the page to belong to a writer before merging content.
    writer=PdfWriter(clone_from=reader)
    writer.pages[page_index].merge_page(PdfReader(BytesIO(out.getvalue())).pages[0])
    writer.add_metadata({'/Title':data['context']['qc_id']+'_Bien_Ban_Kiem_Tra',
                         '/Author':data['signer']['name'],'/Subject':'Internal QC acknowledgement '+data['signer']['content_hash'],
                         '/Keywords':'Signed '+data['signer'].get('signed_at','')})
    final=BytesIO();writer.write(final)
    verified=PdfReader(BytesIO(final.getvalue()))
    if not verified.pages or not any((p.extract_text() or '').strip() for p in verified.pages):
        raise HTTPException(502,'PDF sau ghép chữ ký không có nội dung đọc được.')
    return final.getvalue()
