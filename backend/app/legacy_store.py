"""Map the unchanged legacy business code to relational MySQL entities.

The sheet-shaped structures exist only inside each request. MySQL tables remain
the source of truth; SourceRow is an immutable migration baseline.
"""
import copy
from datetime import date, datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
from zoneinfo import ZoneInfo
from sqlalchemy import select
from .models import Customer, Product, User, Order, OrderLine, SourceRow, RolePermission
from .film_models import FilmSupplier, FilmMaterial, FilmPO, FilmLine, FilmReceipt, FilmMovement, LegacyState

CONFIG = json.loads(Path('/app/schema.json').read_text())
COLS, NAMES = CONFIG['COLUMNS'], CONFIG['SHEET_NAMES']
SPECS = {
 'CUSTOMERS': (Customer, 'master', {'ID':'id','NAME':'name','ADDRESS':'address','CONTACTER':'contact','PHONE':'phone'}),
 'PRODUCTS': (Product, 'master', {'ID':'id','CUSTOMER_ID':'source_customer_id','NAME':'name','CODE_CUST':'code','TYPE':'type','UNIT':'unit','PRICE':'price'}),
 'EMPLOYEES': (User, 'master', {'ID':'id','NAME':'name','EMAIL':'email','ACCESS':'role'}),
 'ORDERS': (Order, 'operation', {'ID':'id','CUSTOMER_ID':'customer_id','ORDER_DATE':'order_date','DELIVERY_DATE':'delivery_date','PO_NUMBER':'po_number','FILE_URL':'file_url'}),
 'ORDER_DETAILS': (OrderLine, 'operation', {'ID':'id','ORDER_ID':'order_id','PRODUCT_ID':'source_product_id','QTY_ORDER':'quantity','PRICE':'price','QTY_RUN':'produced','QTY_DELIVERED':'delivered','QTY_REMAINING':'remaining_source','NOTE':'note','DELIVERY_DATE':'delivery_date','STAFF_ID':'staff_id','STATUS':'status','UNIT':'unit','KANBAN_ZONE':'zone','PRIORITY_ORDER':'priority','FILM_LINE_ID':'film_line_id'}),
 'FILM_SUPPLIERS': (FilmSupplier, 'master', {'ID':'id','NAME':'name','TYPE':'category'}),
 'FILM_MATERIALS': (FilmMaterial, 'master', {'ID':'id','GRADE':'grade','COLOR':'color','ESD':'esd','THICKNESS':'thickness','WIDTH':'width'}),
 'FILM_PO': (FilmPO, 'operation', {'ID':'id','DATE':'order_date','SUPPLIER':'supplier_id','USER':'staff_id','NOTE':'note','STATUS':'status'}),
 'FILM_LINES': (FilmLine, 'operation', {'ID':'id','PO_ID':'po_id','MATERIAL_ID':'material_id','RESIN':'resin','QTY':'quantity','PRICE':'price','NOTE':'note','STATUS':'status','DELIVERY':'delivery_date','DATE':'order_date','SUPPLIER':'supplier_id'}),
 'FILM_RECEIPTS': (FilmReceipt, 'operation', {'ID':'id','DATE':'receipt_date','PRODUCTION_DATE':'production_date','LINE_ID':'line_id','ROLLS':'rolls','QTY':'quantity','LOCATION':'location','STATUS':'status','USER':'staff_id','IQC_ID':'iqc_id','NOTE':'note'}),
 'FILM_MOVEMENTS': (FilmMovement, 'operation', {'ID':'id','DATE':'moved_at','TYPE':'kind','ORDER_ID':'production_order_id','RECEIPT_ID':'receipt_id','QC_ID':'qc_id','QTY':'quantity','ISSUER':'issuer_id','RECEIVER':'receiver_id','NOTE':'note'}),
}
DATES = {'order_date','delivery_date','receipt_date','production_date'}
NUMBERS = {'price','quantity','produced','delivered','remaining_source','thickness','width','rolls'}
NULLABLE_NUMBERS = {'remaining_source','thickness','width','rolls'}


def value(v):
    if isinstance(v, Decimal): return float(v)
    if isinstance(v, date):
        stamp=v if isinstance(v,datetime) else datetime.combine(v,datetime.min.time(),tzinfo=ZoneInfo(CONFIG['TIMEZONE']))
        return {'__date':stamp.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')}
    return v if v is not None else ''


def text(v):
    if isinstance(v, dict) and '__date' in v:
        return datetime.fromisoformat(v['__date'].replace('Z','+00:00')).astimezone(ZoneInfo(CONFIG['TIMEZONE'])).strftime('%Y-%m-%d')
    if v is None: return ''
    if isinstance(v,float) and v.is_integer(): return str(int(v))
    return str(v).strip()


def date_value(v):
    s=text(v)
    if not s:return None
    for fmt in ['%Y-%m-%d','%Y-%m-%dT%H:%M:%S','%d/%m/%Y','%Y-%m-%d %H:%M:%S']:
        try:return datetime.strptime(s,fmt).date()
        except ValueError:pass
    if isinstance(v,(int,float)):
        from openpyxl.utils.datetime import from_excel
        return from_excel(v).date()
    raise ValueError('Ngày không hợp lệ: '+s)


def scalar(v,attr):
    if attr in DATES:return date_value(v)
    if attr in NUMBERS:
        if text(v)=='':return None if attr in NULLABLE_NUMBERS else Decimal(0)
        n=Decimal(text(v).replace(',','.'))
        if not n.is_finite():raise ValueError('Giá trị số không hợp lệ.')
        return n
    if attr=='priority':return int(float(text(v) or '0'))
    return text(v)


def layout(rows,key):
    headers=[COLS[key]['ID'].casefold()]
    if key=='EMPLOYEES':headers += CONFIG.get('EMPLOYEE_HEADER_ALIASES',{}).get('ID',[])
    idx=next((i for i,row in enumerate(rows[:10]) if any(text(x).casefold() in headers for x in row)),None)
    if idx is None:raise ValueError('Thiếu tiêu đề bảng '+NAMES[key])
    heads=[text(v).casefold() for v in rows[idx]]
    positions={k:heads.index(label.casefold()) for k,label in COLS[key].items() if label.casefold() in heads}
    if key=='EMPLOYEES':
        for k,aliases in CONFIG.get('EMPLOYEE_HEADER_ALIASES',{}).items():
            if k not in positions:
                p=next((i for i,h in enumerate(heads) if h in [x.casefold() for x in aliases]),None)
                if p is not None:positions[k]=p
    return idx,positions


def baseline(db):
    result={'master':{},'operation':{}}
    for row in db.scalars(select(SourceRow).order_by(SourceRow.book,SourceRow.sheet,SourceRow.row_number)):
        rows=result.setdefault(row.book,{}).setdefault(row.sheet,[])
        while len(rows)<row.row_number:rows.append([])
        rows[row.row_number-1]=copy.deepcopy(row.cells)
    return result


def source_cells(row,fallback):
    raw=getattr(row,'source',{}) or {}
    indexes=[int(k) for k in raw if k.isdigit()]
    if not indexes:return copy.deepcopy(fallback)
    return [raw.get(str(i),'') for i in range(1,max(indexes)+1)]


def project(db):
    raw=baseline(db)
    for key,(model,group,mapping) in SPECS.items():
        name=NAMES[key]
        if name not in raw[group]:
            aliases=[NAMES.get(key+'_LEGACY','')]
            name=next((n for n in aliases if n in raw[group]),name)
        rows=raw[group].get(name)
        if rows is None:continue
        header,pos=layout(rows,key)
        idpos=pos['ID']
        locations={text(row[idpos]):i for i,row in enumerate(rows[header+1:],header+1) if idpos<len(row) and text(row[idpos])}
        for obj in db.scalars(select(model).order_by(model.id)):
            if key=='EMPLOYEES' and obj.role=='LOCAL_ADMIN':continue
            i=locations.get(obj.id)
            if i is None:i=len(rows);rows.append([])
            row=source_cells(obj,rows[i])
            while len(row)<=max(pos.values()):row.append('')
            for field,attr in mapping.items():
                if field not in pos:continue
                while len(row)<=pos[field]:row.append('')
                v=getattr(obj,attr)
                # An unresolved historical reference must not become a confirmed
                # association merely because a new customer reuses that code.
                if key=='PRODUCTS' and field=='CUSTOMER_ID':v=obj.customer_id or ''
                if key=='ORDER_DETAILS' and field=='PRODUCT_ID':v=obj.product_id or obj.source_product_id
                row[pos[field]]=value(v)
            if key=='EMPLOYEES' and 'STATUS' in pos:
                row[pos['STATUS']]='Đang hoạt động' if obj.active else 'Tạm khóa'
            rows[i]=row
    books=[]
    for group,tables in raw.items():
        books.append({'id':CONFIG['ID_'+group.upper()],'sheets':[{'id':i+1,'name':n,'values':r} for i,(n,r) in enumerate(sorted(tables.items()))]})
    return books


def note_positions(books):
    positions={}
    for book in books:
        for sheet in book['sheets']:
            key=next((k for k in SPECS if sheet['name'] in [NAMES[k],NAMES.get(k+'_LEGACY')]),None)
            if key is None:continue
            header,cols=layout(sheet['values'],key)
            positions[(book['id'],sheet['name'])]={text(row[cols['ID']]):r for r,row in enumerate(sheet['values'])
               if r>header and len(row)>cols['ID'] and text(row[cols['ID']])}
    return positions


def runtime_notes(books,stored):
    positions=note_positions(books);result={}
    for bid,sheets in stored.items():
        for name,entries in sheets.items():
            for key,note in entries.items():
                if key.startswith('id:'):
                    identifier,col=key[3:].rsplit(':',1)
                    row=positions.get((bid,name),{}).get(identifier)
                    if row is None:continue
                    key=str(row)+':'+col
                result.setdefault(bid,{}).setdefault(name,{})[key]=note
    return result


def persistent_notes(books,notes,changes):
    current=copy.deepcopy(books)
    for change in changes:
        for book in current:
            if book['id']!=change['book']:continue
            for sheet in book['sheets']:
                if sheet['name']==change['name']:sheet['values']=change['values']
    positions=note_positions(current)
    rows={key:{r:identifier for identifier,r in values.items()} for key,values in positions.items()}
    result={}
    for bid,sheets in notes.items():
        for name,entries in sheets.items():
            for key,note in entries.items():
                r,c=key.split(':');identifier=rows.get((bid,name),{}).get(int(r))
                stable='id:'+identifier+':'+c if identifier else key
                result.setdefault(bid,{}).setdefault(name,{})[stable]=note
    return result


def rows_to_models(db,key,rows,before=None):
    model,group,mapping=SPECS[key]
    header,pos=layout(rows,key)
    old={}
    if before is not None:
        old_header,old_pos=layout(before,key)
        old={text(r[old_pos['ID']]):r for r in before[old_header+1:] if len(r)>old_pos['ID'] and text(r[old_pos['ID']])}
    existing={x.id:x for x in db.scalars(select(model))}
    customers={x for x in db.scalars(select(Customer.id))}
    products={x for x in db.scalars(select(Product.id))}
    staff={x for x in db.scalars(select(User.id))}
    changed_ids=[];seen=set()
    for row in rows[header+1:]:
        identifier=text(row[pos['ID']]) if pos['ID']<len(row) else ''
        if not identifier:continue
        if identifier in seen:raise ValueError('Mã bị trùng trong '+NAMES[key]+': '+identifier)
        seen.add(identifier)
        if identifier in old and row==old[identifier]:continue
        obj=existing.get(identifier)
        fresh=obj is None
        unresolved_customer=obj.source_customer_id if model is Product and obj and obj.customer_id is None else None
        if fresh:obj=model(id=identifier);db.add(obj)
        for field,attr in mapping.items():
            if field not in pos or attr=='id':continue
            v=row[pos[field]] if pos[field]<len(row) else ''
            if model in {FilmMaterial,FilmLine,FilmReceipt,FilmMovement} and attr in NUMBERS and text(v)=='':setattr(obj,attr,None)
            elif attr=='staff_id' and model is OrderLine:setattr(obj,attr,text(v) or None)
            else:setattr(obj,attr,scalar(v,attr))
        if model is Product:
            if unresolved_customer and not obj.source_customer_id:
                obj.source_customer_id=unresolved_customer
                obj.customer_id=None
                row=list(row)
                row[pos['CUSTOMER_ID']]=unresolved_customer
            else:
                obj.customer_id=obj.source_customer_id if obj.source_customer_id in customers else None
        elif model is Order:
            if obj.customer_id not in customers:raise ValueError('Khách hàng không tồn tại: '+obj.customer_id)
            if not fresh:obj.version+=1
        elif model is OrderLine:
            obj.product_id=obj.source_product_id if obj.source_product_id in products else None
            if obj.staff_id and obj.staff_id not in staff:raise ValueError('Nhân viên không tồn tại: '+obj.staff_id)
            if 'UNIT' not in pos:
                p=db.get(Product,obj.product_id) if obj.product_id else None
                obj.unit=obj.unit or (p.unit if p else '')
            if not fresh:
                order=db.get(Order,obj.order_id)
                if order:order.version+=1
        obj.source={str(i+1):v for i,v in enumerate(row) if v is not None}
        changed_ids.append(identifier)
    db.flush()
    return changed_ids


def initialize(db):
    if db.get(LegacyState,1):return {'already_initialized':True}
    raw=baseline(db);counts={}
    for key in ['FILM_SUPPLIERS','FILM_MATERIALS','FILM_PO','FILM_LINES','FILM_RECEIPTS','FILM_MOVEMENTS']:
        _,group,_=SPECS[key]
        name=NAMES[key]
        if name not in raw[group]:name=NAMES.get(key+'_LEGACY',name)
        if name not in raw[group]:raise ValueError('Thiếu dữ liệu nguồn '+name)
        counts[key]=len(rows_to_models(db,key,raw[group][name]))
    notes={}
    # Excel exports retain cell comments when Google exports them.
    from openpyxl import load_workbook
    for group in ['master','operation']:
        book=load_workbook('/app/data/source-'+group+'.xlsx',data_only=True)
        for sheet in book:
            for row in sheet:
                for cell in row:
                    if cell.comment:
                        notes.setdefault(CONFIG['ID_'+group.upper()],{}).setdefault(sheet.title,{})[str(cell.row-1)+':'+str(cell.column-1)]=cell.comment.text
    db.add(LegacyState(id=1,revision=1,properties={CONFIG['PROPERTY_KEYS'][k]:CONFIG[k] for k in ['ID_MASTER','ID_OPERATION','ID_STORAGES']},
                       metadata_entries={},cell_notes=notes))
    db.flush()
    return {'counts':counts,'note_count':sum(len(n) for b in notes.values() for n in b.values())}


if __name__=='__main__':
    from .db import Session
    with Session.begin() as db:print(json.dumps(initialize(db),ensure_ascii=False))
