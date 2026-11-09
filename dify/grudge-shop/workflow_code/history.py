import json
def main(body: str, status: int) -> dict:
    if status != 200:
        raise ValueError("记忆服务不可用，请检查地址和凭据后重试")
    data = json.loads(body)
    if not isinstance(data, dict) or data.get("status") not in ("empty", "ready"):
        raise ValueError("记忆服务未返回有效召回状态")
    content = data.get("content")
    if data["status"] == "empty":
        if content not in (None, ""):
            raise ValueError("空记忆状态与内容不一致")
        return {"history": "暂无历史，这是初次光临。"}
    if not isinstance(content, str) or not content.strip():
        raise ValueError("记忆服务返回就绪状态但缺少历史内容")
    return {"history": content}
