import os
from sqlalchemy import create_engine, URL
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


url = URL.create('mysql+pymysql', username=os.environ['DB_USER'], password=os.environ['DB_PASSWORD'],
                 host=os.environ.get('DB_HOST', 'mysql'), port=int(os.environ.get('DB_PORT', '3306')),
                 database=os.environ['DB_NAME'], query={'charset': 'utf8mb4'})
engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5, echo=False,
                       isolation_level='READ COMMITTED')
Session = sessionmaker(engine, expire_on_commit=False)


def get_db():
    with Session() as session:
        yield session
