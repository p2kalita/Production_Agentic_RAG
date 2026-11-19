import hashlib
import logging
from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, sessionmaker
from src.db.interfaces.base import BaseDatabase
from src.schemas.database.config import PostgreSQLSettings

logger = logging.getLogger(__name__)

# Fixed key for pg_advisory_xact_lock that serializes schema creation across processes.
# Derived from the string "rag-api:schema-init"; must be identical in every process.
SCHEMA_INIT_LOCK_KEY = int.from_bytes(hashlib.sha256(b"rag-api:schema-init").digest()[:8], "big", signed=True)

Base = declarative_base()


class PostgreSQLDatabase(BaseDatabase):
    """PostgreSQL database implementation."""

    def __init__(self, config: PostgreSQLSettings):
        self.config = config
        self.engine: Optional[Engine] = None
        self.session_factory: Optional[sessionmaker] = None

    def startup(self) -> None:
        """Initialize the database connection."""
        try:
            # Log connection attempt
            logger.info(
                f"Attempting to connect to PostgreSQL at: {self.config.database_url.split('@')[1] if '@' in self.config.database_url else 'localhost'}"
            )

            self.engine = create_engine(
                self.config.database_url,
                echo=self.config.echo_sql,
                pool_size=self.config.pool_size,
                max_overflow=self.config.max_overflow,
                pool_pre_ping=True,  # Verify connections before use
            )

            self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

            # Test the connection
            assert self.engine is not None
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                logger.info("Database connection test successful")

            # Create missing tables under a transaction-scoped advisory lock so that
            # concurrent processes (uvicorn workers, Airflow tasks) don't race on
            # CREATE TABLE. Waiters see the tables already exist once the lock frees.
            with self.engine.begin() as conn:
                conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": SCHEMA_INIT_LOCK_KEY})

                existing_tables = inspect(conn).get_table_names()
                Base.metadata.create_all(bind=conn)
                updated_tables = inspect(conn).get_table_names()

            new_tables = set(updated_tables) - set(existing_tables)

            if new_tables:
                logger.info(f"Created new tables: {', '.join(new_tables)}")
            else:
                logger.info("All tables already exist - no new tables created")

            logger.info("PostgreSQL database initialized successfully")
            assert self.engine is not None
            logger.info(f"Database: {self.engine.url.database}")
            logger.info(f"Total tables: {', '.join(updated_tables) if updated_tables else 'None'}")
            logger.info("Database connection established")

        except Exception as e:
            logger.error(f"Failed to initialize PostgreSQL database: {e}")
            raise

    def teardown(self) -> None:
        """Close the database connection."""
        if self.engine:
            self.engine.dispose()
            logger.info("PostgreSQL database connections closed")

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """Get a database session."""
        if not self.session_factory:
            raise RuntimeError("Database not initialized. Call startup() first.")

        session = self.session_factory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
