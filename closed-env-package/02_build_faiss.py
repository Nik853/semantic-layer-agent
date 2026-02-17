"""
=================================================================
ПОСТРОЕНИЕ FAISS-ИНДЕКСА
=================================================================
Скрипт загружает метаданные из Cube REST API, создаёт
FAISS-индекс с эмбеддингами для семантического поиска.

Запуск: python 02_build_faiss.py
=================================================================
"""

import os
import sys
import json
import subprocess
import pickle
from pathlib import Path
from dataclasses import dataclass
from typing import List, Optional, Dict

# ============================================================
# Автоустановка зависимостей
# ============================================================

def _ensure_packages():
    """Проверить и установить недостающие пакеты (включая FAISS)"""
    # Сначала проверим наличие torch (CPU) — нужен для sentence-transformers
    required = {
        "yaml": "pyyaml",
        "httpx": "httpx",
        "faiss": "faiss-cpu",
        "langchain_core": "langchain-core",
        "langchain_community": "langchain-community",
        "langchain": "langchain",
        "sentence_transformers": "sentence-transformers",
    }
    missing = []
    for module, pip_name in required.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(pip_name)

    # Проверяем torch отдельно — ставим CPU-версию если нет
    try:
        import torch
    except ImportError:
        missing.append("torch")

    if missing:
        print(f"📦 Установка недостающих пакетов: {', '.join(missing)}")
        cmd = [sys.executable, "-m", "pip", "install", "--quiet"]
        # Если нужен torch, ставим CPU-версию для экономии места
        torch_needed = "torch" in missing
        other = [p for p in missing if p != "torch"]
        if torch_needed:
            print("   ⚡ PyTorch будет установлен в CPU-версии (без CUDA)")
            subprocess.check_call(
                cmd + ["torch", "--index-url", "https://download.pytorch.org/whl/cpu"]
            )
        if other:
            subprocess.check_call(cmd + other)
        print("✅ Все пакеты установлены")

_ensure_packages()

import yaml
import httpx

# ============================================================
# Загрузка конфигурации
# ============================================================

def load_config(config_path="config.yml"):
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


# ============================================================
# Структура метаданных
# ============================================================

@dataclass
class CubeMember:
    name: str
    title: str
    type: str
    cube_name: str
    member_type: str  # "measure" or "dimension"
    description: str = ""
    agg_type: str = ""


# ============================================================
# Загрузка метаданных Cube
# ============================================================

def load_cube_metadata(config) -> List[CubeMember]:
    """Загрузить метаданные из Cube REST API /meta"""
    cube_url = config["cube"]["api_url"]
    api_token = config["cube"].get("api_token", "")
    
    headers = {}
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
    
    url = f"{cube_url}/meta"
    print(f"🔄 Загрузка метаданных: {url}")
    
    client = httpx.Client(timeout=30.0)
    resp = client.get(url, headers=headers)
    resp.raise_for_status()
    metadata = resp.json()
    
    members = []
    for cube in metadata.get("cubes", []):
        cube_name = cube["name"]
        
        for measure in cube.get("measures", []):
            if not measure.get("isVisible", True):
                continue
            title = measure.get("shortTitle") or measure.get("title", measure["name"])
            members.append(CubeMember(
                name=measure["name"],
                title=title,
                type=measure.get("type", "number"),
                cube_name=cube_name,
                member_type="measure",
                description=measure.get("description", ""),
                agg_type=measure.get("aggType", "")
            ))
        
        for dim in cube.get("dimensions", []):
            if not dim.get("isVisible", True):
                continue
            title = dim.get("shortTitle") or dim.get("title", dim["name"])
            members.append(CubeMember(
                name=dim["name"],
                title=title,
                type=dim.get("type", "string"),
                cube_name=cube_name,
                member_type="dimension",
                description=dim.get("description", "")
            ))
    
    return members


# ============================================================
# Построение FAISS-индекса
# ============================================================

def build_faiss_index(members: List[CubeMember], config):
    """Построить FAISS-индекс с эмбеддингами метаданных"""
    
    from langchain_community.vectorstores import FAISS
    from langchain_community.embeddings import HuggingFaceEmbeddings
    from langchain_core.documents import Document
    
    model_name = config["faiss"]["embedding_model"]
    print(f"🔄 Загрузка модели эмбеддингов: {model_name}")
    
    embeddings = HuggingFaceEmbeddings(model_name=model_name)
    
    print(f"🔄 Создание документов ({len(members)} members)...")
    documents = []
    
    for m in members:
        # Текст для эмбеддинга: title + description + контекст
        parts = [m.title]
        if m.description:
            parts.append(m.description)
        parts.append(f"Куб: {m.cube_name}")
        parts.append(f"Тип: {m.member_type}, {m.type}")
        if m.agg_type:
            parts.append(f"Агрегация: {m.agg_type}")
        text = ". ".join(parts)
        
        doc = Document(
            page_content=text,
            metadata={
                "name": m.name,
                "title": m.title,
                "type": m.type,
                "cube_name": m.cube_name,
                "member_type": m.member_type,
                "agg_type": m.agg_type,
                "description": m.description
            }
        )
        documents.append(doc)
    
    print(f"🔄 Построение FAISS-индекса...")
    store = FAISS.from_documents(documents, embeddings)
    
    return store, members


def save_faiss_index(store, members, config):
    """Сохранить FAISS-индекс и метаданные на диск"""
    index_path = Path(config["faiss"]["index_path"])
    index_path.mkdir(parents=True, exist_ok=True)
    
    # Сохранить FAISS
    store.save_local(str(index_path))
    
    # Сохранить метаданные members
    members_data = []
    for m in members:
        members_data.append({
            "name": m.name,
            "title": m.title,
            "type": m.type,
            "cube_name": m.cube_name,
            "member_type": m.member_type,
            "description": m.description,
            "agg_type": m.agg_type
        })
    
    with open(index_path / "members.json", 'w', encoding='utf-8') as f:
        json.dump(members_data, f, ensure_ascii=False, indent=2)
    
    print(f"💾 Индекс сохранён: {index_path}/")
    print(f"   - index.faiss    (векторный индекс)")
    print(f"   - index.pkl      (метаданные документов)")
    print(f"   - members.json   (метаданные Cube-мемберов)")


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("  ПОСТРОЕНИЕ FAISS-ИНДЕКСА")
    print("  Cube metadata → Embeddings → FAISS")
    print("=" * 60)
    print()
    
    config = load_config()
    print("✅ Конфигурация загружена")
    
    # 1. Загрузить метаданные из Cube
    members = load_cube_metadata(config)
    print(f"✅ Загружено: {len(members)} мемберов")
    
    measures = [m for m in members if m.member_type == "measure"]
    dimensions = [m for m in members if m.member_type == "dimension"]
    cubes = set(m.cube_name for m in members)
    print(f"   Кубов: {len(cubes)}, Мер: {len(measures)}, Измерений: {len(dimensions)}")
    print()
    
    # 2. Построить индекс
    store, members = build_faiss_index(members, config)
    print("✅ FAISS-индекс построен")
    
    # 3. Сохранить
    save_faiss_index(store, members, config)
    
    # 4. Тест поиска
    print()
    print("🔍 Тестовый поиск: 'количество задач по проектам'")
    results = store.similarity_search_with_score("количество задач по проектам", k=5)
    for doc, score in results:
        print(f"   {score:.2f} | {doc.metadata['name']:40} | {doc.metadata['title']}")
    
    print()
    print("=" * 60)
    print("  ✅ ГОТОВО! Теперь откройте 03_agent.ipynb в JupyterLab")
    print("=" * 60)


if __name__ == "__main__":
    main()
