import json
def main(player: str, query: str) -> dict:
    if not player or not query.strip():
        raise ValueError("玩家标识或输入为空")
    if len(query) > 1200:
        raise ValueError("每次行动限1200字")
    return {"payload": json.dumps({"player_id": player, "query": query}, ensure_ascii=False)}
