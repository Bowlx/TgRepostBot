from dataclasses import dataclass, field
from typing import Optional


@dataclass
class User:
    user_id: int
    source_lang: str = "ru"
    target_lang: str = "en"
    linkedin_access_token: Optional[str] = None
    linkedin_person_urn: Optional[str] = None


@dataclass
class PendingPost:
    user_id: int
    original_text: str
    translated_text: str
    photo_file_ids: list[str] = field(default_factory=list)
