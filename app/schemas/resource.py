from typing import Optional
from pydantic import BaseModel
from datetime import datetime


class ResourceBase(BaseModel):
    filename: str
    original_filename: Optional[str] = None
    file_type: str
    mime_type: Optional[str] = None
    file_size: Optional[int] = None
    file_metadata: Optional[str] = None


class ResourceCreate(ResourceBase):
    file_path: Optional[str] = None
    file_url: Optional[str] = None
    creation_id: Optional[int] = None


class Resource(ResourceBase):
    id: int
    owner_id: int
    creation_id: Optional[int] = None
    file_path: Optional[str] = None
    file_url: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True
