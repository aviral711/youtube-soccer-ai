from sqlalchemy import create_engine, text
import psycopg2

DATABASE_URL = (
    "postgresql+psycopg2://postgres:postgres@localhost:5432/soccer_ai"
)

engine = create_engine(DATABASE_URL)

## Test connection to the database
# with engine.connect() as conn:

#     result = conn.execute(text("SELECT version();"))

#     print(result.fetchone())