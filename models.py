from dataclasses import dataclass, field
from typing import Optional


@dataclass
class User:
    user_id: int
    source_lang: str = "ru"
    target_lang: str = "en"
    translate_enabled: bool = True
    approve_enabled: bool = False
    linkedin_access_token: Optional[str] = None
    linkedin_person_urn: Optional[str] = None
    linkedin_enabled: bool = True
    instagram_username: Optional[str] = None
    instagram_password_encrypted: Optional[str] = None
    instagram_totp_secret_encrypted: Optional[str] = None
    instagram_sessionid_encrypted: Optional[str] = None
    instagram_enabled: bool = True


@dataclass
class PendingPost:
    user_id: int
    original_text: str
    translated_text: str
    photo_file_ids: list[str] = field(default_factory=list)
    active_text: str = ""
    active_mode: str = "translated"
    li_enabled: bool = True
    ig_enabled: bool = True


@dataclass
class Approval:
    id: int
    user_id: int
    original_text: str
    translated_text: str
    photo_file_ids: list[str] = field(default_factory=list)
    active_text: str = ""
    active_mode: str = "translated"
    li_enabled: bool = True
    ig_enabled: bool = True