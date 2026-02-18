"""
Фабрика эмбеддеров: HuggingFace или GigaChat.
Выбор определяется полем faiss.embedding_provider в config.yml.
"""

import os


def create_embeddings(config: dict):
    """Создать объект Embeddings на основе config.yml.

    faiss.embedding_provider:
        "huggingface" (default) — sentence-transformers / HuggingFaceEmbeddings
        "gigachat"              — GigaChatEmbeddings (через тот же прокси / credentials)
    """
    faiss_cfg = config.get("faiss", {})
    provider = (faiss_cfg.get("embedding_provider") or "huggingface").strip().lower()

    if provider == "gigachat":
        return _create_gigachat_embeddings(config)
    return _create_huggingface_embeddings(config)


def _create_huggingface_embeddings(config: dict):
    from langchain_community.embeddings import HuggingFaceEmbeddings

    model_name = config["faiss"]["embedding_model"]
    return HuggingFaceEmbeddings(model_name=model_name)


def _create_gigachat_embeddings(config: dict):
    from langchain_gigachat import GigaChatEmbeddings

    gc = config.get("gigachat", {})

    if gc.get("base_url"):
        token_env = gc.get("access_token_env", "JPY_API_TOKEN")
        token = os.getenv(token_env, "")
        return GigaChatEmbeddings(
            base_url=gc["base_url"],
            access_token=token,
        )

    if gc.get("credentials"):
        return GigaChatEmbeddings(
            credentials=gc["credentials"],
            verify_ssl_certs=gc.get("verify_ssl", False),
        )

    raise ValueError("GigaChat embeddings: заполните gigachat.base_url или gigachat.credentials в config.yml")
