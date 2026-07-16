# Importa os para ler variáveis de ambiente
import os
from typing import Any

from supabase import Client, create_client

_client: Client | None = None

def get_supabase_client() -> Client:
    global _client

    if _client is None:
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]


        # Cria o cliente Supabase usando URL e chave de serviço
        _client = create_client(url, key)

    return _client