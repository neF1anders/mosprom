import os

from UM.Application import Application

DEFAULT_BASE_URL = "https://api.timeweb.ai/v1"
DEFAULT_MODEL = "dashscope/qwen3.8-flash"

PREF_BASE_URL = "ai_assistant/base_url"
PREF_API_KEY = "ai_assistant/api_key"
PREF_MODEL = "ai_assistant/model"

_session_only = {}


def data_dir(*parts):
    path = os.path.join(os.path.expanduser("~"), "Documents", "STE_AIAssistant", *parts)
    os.makedirs(path, exist_ok=True)
    return path


def load():
    prefs = Application.getInstance().getPreferences()
    config = {
        "base_url": prefs.getValue(PREF_BASE_URL),
        "api_key": prefs.getValue(PREF_API_KEY),
        "model": prefs.getValue(PREF_MODEL),
    }
    config.update(_session_only)
    return config


def save(base_url=None, api_key=None, model=None, persist=True):
    """Сохраняет настройки LLM или сессии."""
    values = {
        "base_url": base_url.strip().rstrip("/") if base_url else None,
        "api_key": api_key.strip() if api_key else None,
        "model": model.strip() if model else None,
    }
    prefs = Application.getInstance().getPreferences()
    names = {"base_url": PREF_BASE_URL, "api_key": PREF_API_KEY, "model": PREF_MODEL}
    for key, value in values.items():
        if not value:
            continue
        if persist:
            _session_only.pop(key, None)
            prefs.setValue(names[key], value)
        else:
            _session_only[key] = value


def forget_session():
    """Сбрасывает значения только сессии."""
    _session_only.clear()
