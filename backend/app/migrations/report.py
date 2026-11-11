import json
from sqlalchemy import inspect,select,func,text
from app.core.database import engine, Session
from app.auth.models import User
from app.modules.customers.models import Customer
from app.modules.products.models import Product
from app.modules.orders.models import Order, OrderLine
from app.integrations.google.oauth import configured


if __name__=='__main__':
    with Session() as db:
        tables=inspect(engine).get_table_names()
        counts={name:db.scalar(text('SELECT COUNT(*) FROM `'+name+'`')) for name in tables}
        residuals={model.__tablename__:db.scalar(select(func.count()).select_from(model).where(model.id.startswith('_TEST_',autoescape=True)))
                   for model in [User,Customer,Product,Order,OrderLine]}
        result={'database':db.scalar(text('SELECT VERSION()')),
          'migration':db.scalar(text('SELECT version_num FROM alembic_version')),
          'counts':counts,'test_residuals':residuals,'google_configured':configured(),
          'interface':'original HTML/CSS/JS, local RPC adapter, relational MySQL persistence',
          'google_live_verification':'pending OAuth client and user consent',
          'source_google_sheets_modified':False}
        print(json.dumps(result,ensure_ascii=False,indent=2))
