import os
from sqlalchemy import create_engine, URL
from sqlalchemy import event
from time import perf_counter
from app.core.performance import record, enabled
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


url = URL.create('mysql+pymysql', username=os.environ['DB_USER'], password=os.environ['DB_PASSWORD'],
                 host=os.environ.get('DB_HOST', 'mysql'), port=int(os.environ.get('DB_PORT', '3306')),
                 database=os.environ['DB_NAME'], query={'charset': 'utf8mb4'})
engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5, echo=False,
                       isolation_level='READ COMMITTED')
Session = sessionmaker(engine, expire_on_commit=False)


@event.listens_for(engine, 'before_cursor_execute')
def qc_sql_start(conn, cursor, statement, parameters, context, executemany):
    context._qc_started = perf_counter() if enabled() else None


@event.listens_for(engine, 'after_cursor_execute')
def qc_sql_end(conn, cursor, statement, parameters, context, executemany):
    if context._qc_started is None:
        return
    # Record only the SQL verb, never SQL text or bound values.
    verb = statement.lstrip().split(None, 1)[0].upper() if statement.strip() else 'SQL'
    record('mysql.' + verb, perf_counter() - context._qc_started)


@event.listens_for(engine, 'handle_error')
def qc_sql_error(exception_context):
    context = exception_context.execution_context
    if context is not None and getattr(context, '_qc_started', None) is not None:
        record('mysql.execute_error', perf_counter() - context._qc_started, ok=False)


def get_db():
    with Session() as session:
        yield session
