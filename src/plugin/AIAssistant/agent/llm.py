"""OpenAI-compatible Chat Completions client with tool calling."""
import json
import urllib.error
import urllib.request


class LLMError(Exception):
    pass


HINTS = {
    401: "the API key was rejected",
    403: "access is denied for this key",
    404: "the address or the model name was not found",
    429: "too many requests or the quota is used up",
}


def chat(base_url, api_key, model, messages, mcp_tools):
    if not api_key:
        raise LLMError("The API key is not set. Enter it in the settings of the chat.")
    body = {"model": model, "messages": messages}
    if mcp_tools:
        body["tools"] = [{"type": "function", "function": {
            "name": t["name"], "description": t["description"], "parameters": t["inputSchema"]}} for t in mcp_tools]
    request = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions", data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key})
    try:
        response = urllib.request.urlopen(request, timeout=180)
        data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:400]
        raise LLMError("LLM error %d (%s): %s" % (error.code, HINTS.get(error.code, "request failed"), detail))
    except urllib.error.URLError as error:
        raise LLMError("No connection to the LLM at %s: %s" % (base_url, error.reason))
    except ValueError:
        raise LLMError("The LLM returned a response that is not JSON")
    try:
        return data["choices"][0]["message"]
    except (KeyError, IndexError):
        raise LLMError("Unexpected LLM response: %s" % json.dumps(data, ensure_ascii=False)[:300])
