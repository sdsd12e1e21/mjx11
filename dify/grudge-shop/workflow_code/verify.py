import json
def main(body: str, status: int, reply: str) -> dict:
    if status != 200:
        raise ValueError("本轮记忆未保存，未返回成功回复。请检查服务运行状态。")
    result = json.loads(body)
    if not result.get("records"):
        raise ValueError("记忆服务未返回写入凭据")
    return {"answer": reply}
