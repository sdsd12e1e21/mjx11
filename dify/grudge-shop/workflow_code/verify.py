import json
def main(body: str, status: int, reply: str) -> dict:
    if status != 200:
        raise ValueError("本轮记忆未保存，未返回成功回复。请检查服务运行状态。")
    result = json.loads(body)
    if not isinstance(result, dict) or not isinstance(result.get("records"), list) or not result["records"]:
        raise ValueError("记忆服务未返回写入凭据")
    if not isinstance(result.get("scope_id"), str) or not result["scope_id"]:
        raise ValueError("记忆服务未返回玩家分区")
    for record in result["records"]:
        artifact = record.get("artifact") if isinstance(record, dict) else None
        if (not isinstance(artifact, dict)
                or artifact.get("family") != "atomic-memory"
                or not isinstance(artifact.get("artifact_id"), str)
                or not artifact["artifact_id"]
                or type(artifact.get("revision")) is not int
                or artifact["revision"] < 1):
            raise ValueError("记忆服务返回了无效写入凭据")
    if result.get("finale") and not isinstance(result["finale"], str):
        raise ValueError("结局格式无效")
    return {"answer": result.get("finale") or reply}
