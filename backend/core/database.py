"""
Enhanced database connection and session management
PostgreSQL with SQLAlchemy ORM support
"""

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import sessionmaker, Session
import os
from dotenv import load_dotenv
import logging
from contextlib import asynccontextmanager, contextmanager
from typing import AsyncGenerator, Generator

load_dotenv()

# Database configuration
DB_URL = os.getenv("DB_URL", "postgresql://postgres:password@localhost/appdb")
DB_URL_ASYNC = os.getenv("DB_URL_ASYNC", DB_URL.replace("postgresql://", "postgresql+asyncpg://"))

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Synchronous engine for compatibility (without QueuePool for asyncio compatibility)
sync_engine = create_engine(
    DB_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=False
)

# Asynchronous engine for better performance
async_engine = create_async_engine(
    DB_URL_ASYNC,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=False
)

# Session makers
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)
AsyncSessionLocal = async_sessionmaker(async_engine, expire_on_commit=False)

# Import the Base from models
from models.database_models import Base


def get_db() -> Generator[Session, None, None]:
    """Synchronous database session dependency for FastAPI"""
    db = SessionLocal()
    try:
        yield db
    except Exception as e:
        logger.error(f"Database session error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def get_sync_session() -> Generator[Session, None, None]:
    """Synchronous DB session context manager (for non-dependency usage)"""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception as e:
        logger.error(f"Database sync session error: {e}")
        db.rollback()
        raise
    finally:
        db.close()


async def get_async_db() -> AsyncGenerator[AsyncSession, None]:
    """Asynchronous database session dependency for FastAPI"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            logger.error(f"Async database session error: {e}")
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Context manager for async database sessions"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            logger.error(f"Async session error: {e}")
            await session.rollback()
            raise
        finally:
            await session.close()


def create_tables():
    """Create all tables in the database (sync)"""
    try:
        Base.metadata.create_all(bind=sync_engine)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Failed to create tables: {e}")
        raise


async def create_tables_async():
    """Create all tables in the database (async)"""
    try:
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created successfully (async)")
    except Exception as e:
        logger.error(f"Failed to create tables (async): {e}")
        raise


async def check_db_connection():
    """Check database connectivity"""
    try:
        async with get_async_session() as session:
            from sqlalchemy import text
            result = await session.execute(text("SELECT 1"))
            result.scalar()
        logger.info("Database connection successful")
        return True
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False


# Database utilities
class DatabaseManager:
    """Database manager with health checks and connection management"""
    
    def __init__(self):
        self.sync_engine = sync_engine
        self.async_engine = async_engine
        
    async def health_check(self) -> dict:
        """Perform database health check"""
        try:
            # Test async connection
            async with get_async_session() as session:
                from sqlalchemy import text
                result = await session.execute(text("SELECT version()"))
                db_version = result.scalar()
                
            # Test connection pool (simplified without accessing specific pool attributes)
            pool_status = {
                "status": "connected",
                "engine_name": str(self.async_engine.name) if hasattr(self.async_engine, 'name') else "postgresql",
            }
            
            return {
                "status": "healthy",
                "database_version": db_version,
                "pool_status": pool_status
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }
    
    async def close_connections(self):
        """Close all database connections"""
        await self.async_engine.dispose()
        self.sync_engine.dispose()
        logger.info("Database connections closed")


# Global database manager instance
db_manager = DatabaseManager()
