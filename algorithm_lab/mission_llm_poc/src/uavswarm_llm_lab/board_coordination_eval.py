"""B-v0.2: separate agents, a public turn history and a synthetic score referee."""
from __future__ import annotations

from .contracts import ContractError


FILES = "benchmarks/board_coordination_b_v0_2.json"
METHODS = ("independent", "shared", "history", "model-independent", "model-shared", "model-history",
           "model-shared-explicit")
PASS = "PASS"
SYSTEM = (
    "你是抽象记分牌桌上本队的一枚棋子。只选自己本轮的一张牌或 PASS，不代替队友选择。"
    "每轮牌重置；同队同牌只算一次；两队同选一张牌则都不得这张牌的分；"
    "选无效牌不得分。目标是提高本队累计得分。"
    "如给出队友本轮意向，可以用来分工；如给出对手往轮公开选择，可以参考，但不知道对手本轮选什么。"
    "只输出含字符串 choice 的 JSON，不使用棋盘外的动作。"
)


def score_round(cards: dict, picks: list, opponent: list) -> dict:
    if len(picks) != 2 or len(opponent) != 2:
        raise ContractError("BOARD_EXPECTS_TWO_AGENTS_PER_SIDE")
    legal = lambda pick: isinstance(pick, str) and (pick == PASS or pick in cards)
    valid = [legal(pick) for pick in picks]
    rival_valid = [legal(pick) for pick in opponent]
    ours = {pick for ok, pick in zip(valid, picks) if ok and pick != PASS}
    theirs = {pick for ok, pick in zip(rival_valid, opponent) if ok and pick != PASS}
    contested = ours & theirs
    return {
        "our_score": sum(cards[pick] for pick in ours - contested),
        "opponent_score": sum(cards[pick] for pick in theirs - contested),
        "legal": valid, "opponent_legal": rival_valid, "contested": sorted(contested),
        "duplicate": all(valid) and picks[0] == picks[1] and picks[0] != PASS,
        # Use only the public deck and teammate pick, not the hidden opponent move.
        "pass_choices": picks.count(PASS),
        "avoidable_passes": sum(pick == PASS and any(card != picks[1 - i] for card in cards)
                               for i, pick in enumerate(picks)),
        "distinct_scoring_cards": len(ours - contested),
    }


def observation(cards: dict, turn: int, agent: int, teammate: str | None, history: list | None) -> dict:
    return {
        "cards": [{"id": key, "points": value} for key, value in cards.items()],
        "round": turn, "your_piece": f"piece-{agent+1}", "teammate_intent": teammate,
        "opponent_public_history": history,
    }


def rule_pick(view: dict) -> str:
    history = view["opponent_public_history"]
    previous_opponent = set(history[-1]) if history else set()
    options = [card for card in view["cards"] if card["id"] != view["teammate_intent"]]
    if not options:
        return PASS
    # Local heuristic: avoid last round's revealed choices, then prefer more points.
    return max(options, key=lambda card: (card["id"] not in previous_opponent, card["points"]))["id"]


def fraction(numerator: int, denominator: int):
    return round(numerator / denominator, 4) if denominator else None


def evaluate(bench: dict, method: str, model_call=None) -> dict:
    uses_model = method.startswith("model-")
    if method not in METHODS or (model_call is not None) != uses_model:
        raise ContractError("BOARD_METHOD_AND_MODEL_DISAGREE")
    variant = method.removeprefix("model-")
    cards = bench["cards"]
    share = variant != "independent"
    history_visible = variant == "history"
    explicit_intent = variant == "shared-explicit"
    schema = {"type": "object", "required": ["choice"], "additionalProperties": False,
              "properties": {"choice": {"type": "string", "enum": [*cards, PASS]}}}
    rows = []
    sums = []
    for match in bench["matches"]:
        per_match = []
        for index, opponent in enumerate(match["opponent_choices"], 1):
            picks = []
            decisions = []
            # The two policies get different observations. Neither sees the current opposition choices.
            history = [list(row["opponent_choices"]) for row in per_match] if history_visible else None
            for agent in range(2):
                teammate = picks[0] if agent == 1 and share and picks[0] in cards else None
                view = observation(cards, index, agent, teammate, history)
                trace = None
                if model_call is None:
                    picked = rule_pick(view)
                else:
                    system = SYSTEM
                    if explicit_intent and teammate is not None:
                        system += f"队友这轮已打算选 {teammate}。为避免本队重复计分，请优先选另一张合法牌或 PASS。"
                    proposed, trace = model_call(system, view, schema, 32)
                    picked = (proposed["choice"] if isinstance(proposed, dict) and set(proposed) == {"choice"}
                              and isinstance(proposed["choice"], str) else None)
                picks.append(picked)
                decisions.append({"input": view, "choice": picked, "model_trace": trace})
            outcome = score_round(cards, picks, opponent)
            opportunities = repeats = avoided_previous = 0
            if per_match:
                prev = per_match[-1]
                for old, new in zip(prev["our_choices"], picks):
                    if old in prev["contested"]:
                        opportunities += 1
                        repeats += int(old == new)
                        avoided_previous += int(isinstance(new, str) and new in cards
                                                and new not in prev["opponent_choices"])
            per_match.append({
                "match_id": match["match_id"], "round": index, "our_choices": picks,
                "opponent_choices": opponent, "agent_decisions": decisions, **outcome,
                "contested_on_prior_turn": opportunities, "repeated_after_contest": repeats,
                "switched_off_last_opponent_choices": avoided_previous,
            })
        rows.extend(per_match)
        sums.append({
            "match_id": match["match_id"],
            "our_score": sum(row["our_score"] for row in per_match),
            "opponent_score": sum(row["opponent_score"] for row in per_match),
            "duplicate_rounds": sum(row["duplicate"] for row in per_match),
        })
    legal = sum(sum(row["legal"]) for row in rows)
    duplicate = sum(row["duplicate"] for row in rows)
    repeat = sum(row["repeated_after_contest"] for row in rows)
    prior_contested = sum(row["contested_on_prior_turn"] for row in rows)
    return {"rounds": rows, "matches": sums, "conditions": {
        "teammate_intent_visible": share, "opponent_history_visible": history_visible,
        "teammate_intent_also_explained_as_text": explicit_intent,
        "opponent_policy": "fixed test scripts, current move hidden",
    }, "metrics": {
        "rounds": len(rows), "our_score": sum(row["our_score"] for row in rows),
        "opponent_score": sum(row["opponent_score"] for row in rows),
        "legal_choices": legal, "choice_attempts": 2 * len(rows), "legal_choice_rate": fraction(legal, 2 * len(rows)),
        "duplicate_rounds": duplicate, "same_team_duplicate_rate": fraction(duplicate, len(rows)),
        "pass_choices": sum(row["pass_choices"] for row in rows),
        "avoidable_passes": sum(row["avoidable_passes"] for row in rows),
        "distinct_scoring_cards": sum(row["distinct_scoring_cards"] for row in rows),
        "previously_contested_choices": prior_contested, "repeated_after_contest": repeat,
        "repeat_after_contest_rate": fraction(repeat, prior_contested),
        "switched_off_last_opponent_choices": sum(row["switched_off_last_opponent_choices"] for row in rows),
    }}
