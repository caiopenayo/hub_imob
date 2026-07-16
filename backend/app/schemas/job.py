'''Define quais campos um JobLog deve ter quando for retornado pela API
'''
from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class JobLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    job_name: str
    source_id: Optional[UUID] = None
    provider_key: Optional[str] = None
    source_ids: Optional[List[str]]
    search_scope: Optional[Dict[str, object]] = None
    mode: str
    status: str
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    pages_fetched: int = 0
    listings_seen: int = 0
    new_properties: int = 0
    updated_properties: int = 0
    unchanged_properties: int = 0
    missing_properties: int = 0
    removed_properties: int = 0
    reactivated_properties: int = 0
    detail_pages_fetched: int = 0
    http_errors: Optional[List[Dict[str, object]]] = None
    parse_errors: Optional[List[Dict[str, object]]] = None
    summary: Optional[Dict[str, object]]
    error: Optional[str]
    created_at: datetime
