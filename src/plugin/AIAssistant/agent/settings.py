import os

from UM.Application import Application

DEFAULT_BASE_URL = "https://api.timeweb.ai/v1"
DEFAULT_MODEL = "dashscope/qwen3.8-flash"

PREF_BASE_URL = "ai_assistant/base_url"
PREF_API_KEY = "ai_assistant/api_key"
PREF_MODEL = "ai_assistant/model"


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
    return config
