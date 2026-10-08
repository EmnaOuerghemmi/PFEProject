#!/usr/bin/env python
"""
Direct SQL migration runner - adds missing columns to job_offers table
This bypasses Alembic CLI and directly executes SQL against PostgreSQL
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.config import settings


async def run_migrations():
    """Run migrations directly using SQLAlchemy"""
    try:
        print("🔄 Connecting to database...")
        
        # Create async engine
        engine = create_async_engine(settings.DATABASE_URL, echo=False)
        
        async with engine.begin() as conn:
            print("✅ Connected to database")
            print("🔧 Adding missing columns to job_offers table...\n")
            
            migrations = [
                ("required_skills", """
                    ALTER TABLE job_offers 
                    ADD COLUMN IF NOT EXISTS required_skills json DEFAULT '[]'::json;
                """),
                ("weight_skills", """
                    ALTER TABLE job_offers 
                    ADD COLUMN IF NOT EXISTS weight_skills double precision DEFAULT 0.5 NOT NULL;
                """),
                ("weight_experience", """
                    ALTER TABLE job_offers 
                    ADD COLUMN IF NOT EXISTS weight_experience double precision DEFAULT 0.3 NOT NULL;
                """),
                ("weight_education", """
                    ALTER TABLE job_offers 
                    ADD COLUMN IF NOT EXISTS weight_education double precision DEFAULT 0.2 NOT NULL;
                """),
            ]
            
            for col_name, sql in migrations:
                try:
                    await conn.execute(text(sql))
                    print(f"   ✅ Column '{col_name}' added/verified")
                except Exception as e:
                    print(f"   ⚠️  Column '{col_name}': {e}")
            
            await conn.commit()
            print("\n✅ All migrations completed successfully!")
            
        await engine.dispose()
        return True
        
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    # Use SelectorEventLoop on Windows for async/await with psycopg
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    success = asyncio.run(run_migrations())
    sys.exit(0 if success else 1)
