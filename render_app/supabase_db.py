import os
from supabase import create_client, Client

_url = os.environ.get('SUPABASE_URL', '')
_key = os.environ.get('SUPABASE_SERVICE_KEY') or os.environ.get('SUPABASE_ANON_KEY', '')

_supabase: Client | None = None


def get_db() -> Client:
    global _supabase
    if _supabase is None:
        if not _url or not _key:
            raise RuntimeError('Missing SUPABASE_URL and SUPABASE_ANON_KEY/SUPABASE_SERVICE_KEY env vars')
        _supabase = create_client(_url, _key)
    return _supabase
