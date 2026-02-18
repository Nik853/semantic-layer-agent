"""
Kerberos-авторизация для источников данных (Greenplum, Hive).
Создание и сохранение TGT, установка KRB5CCNAME для использования клиентами.
"""

import os
from pathlib import Path
from typing import Optional


def get_or_create_kerberos_ticket(
    username: str,
    password: str,
    ticket_path: Optional[str] = None,
    krb5_config_path: str = "krb5.conf"
) -> str:
    """Создаёт новый Kerberos-тикет и сохраняет его на диск.
    Устанавливает KRB5_CONFIG и возвращает путь к файлу кэша тикетов.
    Пути (ticket_path, krb5_config_path) должны быть заданы абсолютно — resolve не используется.
    """
    try:
        import gssapi
    except ImportError:
        raise ImportError(
            "Для Kerberos требуется gssapi. Установите: pip install gssapi"
        )

    os.environ["KRB5_CONFIG"] = str(Path(krb5_config_path))

    if ticket_path is None:
        raise ValueError("ticket_path обязателен — укажите абсолютный путь к файлу тикета")
    ticket_path = Path(ticket_path)
    ticket_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"→ Создаём новый Kerberos-тикет для {username}")
    cname = gssapi.Name(username, name_type=gssapi.NameType.user)
    res = gssapi.raw.acquire_cred_with_password(cname, password.encode())
    creds = gssapi.Credentials(res.creds)

    gssapi.raw.store_cred_into(
        {b"ccache": str(ticket_path).encode()},
        creds,
        usage="initiate",
        overwrite=True,
    )

    print(f"✓ Тикет сохранён: {ticket_path}")
    return str(ticket_path)


def set_kerberos_env(ticket_path: str, krb5_config_path: Optional[str] = None) -> None:
    """Устанавливает переменные окружения для использования тикета клиентами. Пути без resolve."""
    os.environ["KRB5CCNAME"] = str(Path(ticket_path))
    if krb5_config_path is not None:
        os.environ["KRB5_CONFIG"] = str(Path(krb5_config_path))
