"""Test script for fetch_logs function."""

import asyncio
import sys
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).resolve().parent / "backend"
sys.path.insert(0, str(backend_dir))

from app.etl import fetch_logs
from app.settings import settings


async def test_fetch_logs():
    """Test fetch_logs function."""
    print(f"Autochecker API URL: {settings.autochecker_api_url}")
    print(f"Email: {settings.autochecker_email}")
    print(f"Password: {'*' * len(settings.autochecker_password)}")
    print()

    try:
        print("Fetching logs...")
        logs = await fetch_logs()
        print(f"✓ Successfully fetched {len(logs)} logs")
        
        if logs:
            print("\nFirst log entry:")
            for key, value in logs[0].items():
                print(f"  {key}: {value}")
        
        return logs
    except Exception as e:
        print(f"Error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(test_fetch_logs())
