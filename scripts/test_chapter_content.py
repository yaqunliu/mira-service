
import sys
import unittest
from unittest.mock import MagicMock, AsyncMock

# 1. Mock problematic dependencies BEFORE importing app modules
sys.modules["supabase"] = MagicMock()
sys.modules["supabase.client"] = MagicMock()
sys.modules["celery"] = MagicMock()
sys.modules["redis"] = MagicMock()
sys.modules["app.core.celery_app"] = MagicMock()

# Also mock tasks import in creation_task.py
sys.modules["app.tasks.creation_task"] = MagicMock()
sys.modules["app.tasks.novel_tasks"] = MagicMock()

# Mock auth dependency if needed
# We might need to mock other things depending on what app.main imports

import asyncio
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
import pytest

# Import the router directly to avoid full app initialization if possible, 
# but dependencies might require app context. 
# Let's try to minimal app setup.

from app.api.api_v1.endpoints import creations
from app.api.deps import get_current_user, get_async_db
from app.models.user import User
from app.models.creation import Creation
from app.models.chapter import Chapter
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.creation_async_service import CreationAsyncService
from app.services.novel_async_service import ChapterAsyncService

# Define a minimal app for testing
app = FastAPI()
app.include_router(creations.router, prefix="/api/v1/creations")

# Mock User and DB
# Mock User and DB
mock_user = User(user_id=1, username="test", email="test@test.com")
# Manually set if needed, or if it's a property/default
# mock_user.is_active = True

async def override_get_current_user():
    return mock_user

async def override_get_async_db():
    yield AsyncMock(spec=AsyncSession)

app.dependency_overrides[get_current_user] = override_get_current_user
app.dependency_overrides[get_async_db] = override_get_async_db

# Patch Services
async def mock_get_creation(db, uuid):
    if uuid == "test-uuid":
        return Creation(
            creation_id=1, 
            uuid="test-uuid", 
            owner_id=1, 
            chapter_id=10, 
            novel_id=100
        )
    return None

async def mock_get_chapter(db, chapter_id):
    if chapter_id == 10:
        return Chapter(
            chapter_id=10, 
            content_url="http://mock-url.com/content.txt"
        )
    return None

# Patch the service methods called in the endpoint
CreationAsyncService.get_creation_by_uuid = mock_get_creation
ChapterAsyncService.get_chapter_by_id = mock_get_chapter

async def run_test():
    print("Starting Integration Test...")
    
    # Mock httpx in the endpoint (it's imported inside the endpoint function or at module level)
    # Since it's 'import httpx' at module level in creations.py, we need to patch 'httpx.AsyncClient'
    
    from unittest.mock import patch
    
    with patch("httpx.AsyncClient") as MockClient:
        # Configure the mock client instance
        mock_instance = MockClient.return_value
        mock_instance.__aenter__.return_value = mock_instance
        
        # Configure get response
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "This is the mock chapter content."
        
        # client.get must be awaitable
        mock_instance.get = AsyncMock(return_value=mock_response)
        
        # Make the request
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            response = await ac.get("/api/v1/creations/test-uuid/chapter_content")
            
        print(f"Response Status: {response.status_code}")
        print(f"Response Body: {response.json()}")
        
        if response.status_code == 200 and response.json()['data']['content'] == "This is the mock chapter content.":
            print("✅ TEST PASSED")
        else:
            print("❌ TEST FAILED")

if __name__ == "__main__":
    asyncio.run(run_test())
