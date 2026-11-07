import json
def main(player: str, query: str, reply: str) -> dict:
    return {"payload": json.dumps({"player_id": player, "query": query, "reply": reply}, ensure_ascii=False)}
