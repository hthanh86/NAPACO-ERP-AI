"""Film specifications share the purchasing VL0001 convention and ERP write lock."""
from decimal import Decimal
from sqlalchemy import select, func, cast, Integer
from app.core.models import Audit
from app.modules.materials.models import FilmMaterial
from fastapi import HTTPException


def find_specs(db,width,thickness,color='',grade=''):
    # Resin belongs to the purchasing line / production standard, not the material key.
    query=select(FilmMaterial).where(func.abs(FilmMaterial.width-width)<0.000001,
        func.abs(FilmMaterial.thickness-thickness)<0.000001)
    if color:query=query.where(func.lower(FilmMaterial.color)==color.strip().lower())
    if grade:query=query.where(func.lower(FilmMaterial.grade)==grade.strip().lower())
    return list(db.scalars(query.order_by(FilmMaterial.id).limit(21)))


def ensure_spec(db,user,data):
    """Called under the shared ERP write lock; caller commits the whole operation."""
    existing=list(db.scalars(select(FilmMaterial).where(
        FilmMaterial.width==Decimal(str(data.width)),FilmMaterial.thickness==Decimal(str(data.thickness)),
        func.lower(FilmMaterial.color)==data.color.strip().lower(),
        func.lower(FilmMaterial.grade)==data.grade.strip().lower(),FilmMaterial.esd=='').with_for_update()))
    if len(existing)>1:raise HTTPException(409,'Danh mục có nhiều NVL trùng quy cách; cần đối soát trước khi chọn.')
    if existing:return existing[0]
    highest=db.scalar(select(func.max(cast(func.substring(FilmMaterial.id,3),Integer))).where(
        FilmMaterial.id.op('REGEXP')('^VL[0-9]{4}$'))) or 0
    if highest>=9999:raise HTTPException(422,'Danh mục đã đạt giới hạn VL9999.')
    identifier=f'VL{highest+1:04d}'
    row=FilmMaterial(id=identifier,grade=data.grade,color=data.color,esd='',
        thickness=Decimal(str(data.thickness)),width=Decimal(str(data.width)),source={})
    db.add(row)
    db.add(Audit(user_id=user.id,action='PRODUCTION_MATERIAL_CREATE',entity_id=identifier,
        details={'grade':data.grade,'color':data.color,'thickness':data.thickness,'width':data.width,
                 'resin':data.resin,'basis':'confirmed_with_standard'}))
    db.flush()
    return row
