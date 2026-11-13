"""Size the temporary QC sheet for print, including vertically merged notes."""
import math
import re
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from app.modules.qc import mapping


def font_name(style):
    family=str(style.get('fontFamily','Arial')).lower()
    face='DejaVuSerif' if any(name in family for name in ('times','georgia','cambria')) or ('serif' in family and 'sans' not in family) else 'DejaVuSans'
    suffix='-Bold' if style.get('bold') else ''
    if style.get('italic'):suffix+=('Italic' if face=='DejaVuSerif' else 'Oblique') if suffix else ('-Italic' if face=='DejaVuSerif' else '-Oblique')
    name='QC-Layout-'+face+suffix
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(name,'/usr/share/fonts/truetype/dejavu/'+face+suffix+'.ttf'))
    return name


def wrapped_lines(text,font,size,width):
    count=0
    for paragraph in str(text).replace('\r\n','\n').replace('\r','\n').expandtabs(4).split('\n'):
        lines=1;used=0
        for word in re.findall(r'\S+\s*',paragraph):
            length=pdfmetrics.stringWidth(word,font,size)*96/72
            if used and used+length>width:lines+=1;used=0
            if length<=width:used+=length;continue
            # Sheets also wraps long IDs/words without spaces.
            for char in word:
                length=pdfmetrics.stringWidth(char,font,size)*96/72
                if used and used+length>width:lines+=1;used=0
                used+=length
        count+=lines
    return count


def fit_content(snapshot,layout,values,gid):
    grid=snapshot.get('grid') or {};r_start=grid.get('startRow',0);c_start=grid.get('startColumn',0)
    def metadata(key,index,start):
        rows=grid.get(key) or []
        return rows[index-start] if start<=index<start+len(rows) else {}
    heights=[metadata('rowMetadata',r,r_start).get('pixelSize',21) for r in range(snapshot['row_count'])]
    original=list(heights)
    hidden_rows={r for r in range(len(heights)) if metadata('rowMetadata',r,r_start).get('hiddenByUser') or metadata('rowMetadata',r,r_start).get('hiddenByFilter')}
    widths=[0 if metadata('columnMetadata',c,c_start).get('hiddenByUser') else metadata('columnMetadata',c,c_start).get('pixelSize',100) for c in range(snapshot['column_count'])]
    cells=mapping.cells(snapshot);content={cell:data.get('formattedValue','') for cell,data in cells.items()}
    content.update(values)
    signature=mapping.region(snapshot,layout['signature_cell'],layout.get('signature_end_cell'))
    requests=[]
    for cell,text in content.items():
        if not str(text):continue
        if mapping.anchor(snapshot,cell)!=cell:continue
        r0,c0,r1,c1=mapping.region(snapshot,cell)
        a,b,x,y=signature
        if r0<x and r1>a and c0<y and c1>b:continue
        visible=[r for r in range(r0,r1) if r not in hidden_rows]
        if not visible:continue
        fmt=cells.get(cell,{}).get('effectiveFormat') or {}
        if cell not in values and fmt.get('wrapStrategy')!='WRAP':continue
        style=fmt.get('textFormat') or {};size=style.get('fontSize',10)
        padding=fmt.get('padding') or {}
        available=max(1,sum(widths[c0:c1])-padding.get('left',3)-padding.get('right',3)-4)
        # A conservative width/leading allowance covers Google font substitution.
        lines=wrapped_lines(text,font_name(style),size,available*.92)
        required=math.ceil(lines*size*96/72*1.4+padding.get('top',3)+padding.get('bottom',3)+4)
        current=sum(heights[r] for r in visible)
        if required>current:heights[visible[-1]]+=required-current
        requests.append({'repeatCell':{'range':{'sheetId':gid,'startRowIndex':r0,'endRowIndex':r1,'startColumnIndex':c0,'endColumnIndex':c1},'cell':{'userEnteredFormat':{'wrapStrategy':'WRAP'}},'fields':'userEnteredFormat.wrapStrategy'}})
    for row,(before,after) in enumerate(zip(original,heights)):
        if after>before:requests.append({'updateDimensionProperties':{'range':{'sheetId':gid,'dimension':'ROWS','startIndex':row,'endIndex':row+1},'properties':{'pixelSize':after},'fields':'pixelSize'}})
    return requests
