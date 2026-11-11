import json
from sqlalchemy import inspect,select,func,text
from .db import engine,Session
from .models import User,Customer,Product,Order,OrderLine
from .google_oauth import configured


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
