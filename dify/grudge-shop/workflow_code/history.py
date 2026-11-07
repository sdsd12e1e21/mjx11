import json
def main(body: str, status: int) -> dict:
    if status != 200:
        raise ValueError("记忆服务不可用，请检查地址和凭据后重试")
    data = json.loads(body)
    return {"history": data.get("content") or "暂无历史，这是初次光临。"}
