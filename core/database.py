from supabase import create_client, Client
from core.config import settings

def get_db() -> Client:
    if not settings.supabase_url or not settings.supabase_key:
        return None
    return create_client(settings.supabase_url, settings.supabase_key)

db = get_db()
