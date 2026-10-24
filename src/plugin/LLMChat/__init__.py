from . import LLMChat


def getMetaData():
    return {}


def register(app):
    return {"extension": LLMChat.LLMChat()}
