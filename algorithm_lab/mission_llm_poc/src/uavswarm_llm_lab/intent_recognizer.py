"""Deterministic objective recognition against a caller-supplied, offline catalog.

These are interpretation results, not a Runtime response, proposal, or plan.
Only the separate explicit-template path can name a guarded template. Neither
entry point signals that a template is supported for execution or authorized.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Collection, Iterable, Literal


TEMPLATE_KEYS = frozenset({
    "simple_takeoff_land", "inspection_snapshot", "status_only", "safe_stop", "fallback_hold",
})

Status = Literal["bound", "clarify", "unknown"]
_MAX_OBJECTIVE_LENGTH = 512
_INSPECTION_VERB = r"(?:巡检|检查|核对|复核)"
_NO = r"(?:不需要|不用|不要|无需|不必|别)"
_CLAUSES = re.compile(r"([，,；;。！？!?\r\n]+)")
_LEADING = re.compile(r"^(?:(?:请|帮我|给我|本轮|这一轮|这轮|麻烦|现在)\s*)+")
_PREVIEW_HEADER = re.compile(r"^(?:三机联巡任务预演|巡检任务预演)\s*[：:]\s*")
_INSPECTION = re.compile(rf"(?P<only>只|仅)?{_INSPECTION_VERB}(?:一下)?\s*(?P<names>.+)")
_SELECT_TARGET = re.compile(r"把\s*(?P<names>.+?)\s*列为(?:本轮)?(?:核对|巡检)?目标")
_AFTER_INLINE = re.compile(r"(.+?)之后\s*(.+)")
_THEN_INLINE = re.compile(rf"先\s*(.+?)\s*再\s*((?:只|仅)?{_INSPECTION_VERB}.+)")
_ORDER_CUE = re.compile(r"之前|之后|^(?:先|再|然后)")
_REFERENCE = re.compile(r"(?P<name>.+?)\s*(?:只|仅)(?:用来|用于|作为)(?:定位|参照|参考|背景地标)")
_EXCLUDE_BEFORE = re.compile(rf"{_NO}\s*{_INSPECTION_VERB}\s*(?P<names>.+)")
_EXCLUDE_AFTER = re.compile(rf"(?P<names>.+?)\s*{_NO}\s*{_INSPECTION_VERB}")
_REFERENCE_TAIL = re.compile(rf"{_NO}\s*核对")
_RESTRICTION = re.compile(r"不|别|禁止|避开|除外|除了|仅|只|定位|参照|参考")
_ALTERNATIVE = re.compile(r"或者|还是|或")
_TARGET_SEPARATOR = re.compile(r"以及|还有|[、和与]")
_MOVE_SEPARATOR = re.compile(r"也去|再去|又去")
_WAREHOUSE_NAME = re.compile(r"(?P<direction>[东西南北])(?:边|侧|面)?(?:的)?(?:仓库|仓)")
_PV_NAME = re.compile(
    r"(?:园区(?:的)?)?(?:(?P<direction>[东西南北])(?:面|边|侧)?(?:的)?)?"
    r"(?:(?:那|这|一)排(?:的)?)?(?:用于发电的)?(?:太阳能板|光伏板|光伏区|发电板)"
)
_PV_SUFFIXES = ("太阳能板", "光伏板", "光伏区", "发电板")
_BUILDING_REFERENCES = frozenset({"那栋", "这栋", "那栋楼", "这栋楼"})
_REFERENCES = _BUILDING_REFERENCES | {"这个", "那个", "刚才说的那个"}
_GUARDED_LANGUAGE = re.compile(r"safe_stop|fallback_hold|紧急(?:停|降落)|安全停机|迫降|悬停", re.I)
_STATUS_QUERY = re.compile(
    r"(?:只|仅)?(?:查询|查看|看看|看下|查)(?:一下)?\s*(?:当前|集群的|各节点的|各平台的|系统的)?"
    r"(?P<kind>在线状态|连接状态|运行状态|状态)"
)
_STATUS_SCOPES = {"在线状态": "online", "连接状态": "connection", "运行状态": "summary", "状态": "summary"}
_TAKEOFF_LAND_PREVIEW = re.compile(r"(?:做一次|预览)?起降验证")


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    entity_id: str
    label: str
    aliases: tuple[str, ...] = ()
    # Nonempty only when this task's catalog allows selecting at most one member.
    exclusive_group: str | None = None


@dataclass(frozen=True, slots=True)
class Binding:
    entity_id: str
    evidence: str


@dataclass(frozen=True, slots=True)
class IntentParameters:
    targets: tuple[Binding, ...] = ()
    reference_only: tuple[Binding, ...] = ()
    excluded_targets: tuple[Binding, ...] = ()
    only_listed_targets: bool = False
    status_scope: str | None = None
    target_order_basis: Literal["explicit_sequence", "mention_order"] | None = None


@dataclass(frozen=True, slots=True)
class IntentRecognition:
    status: Status
    mission_type: str | None
    parameters: IntentParameters
    reason_code: str
    clarification: str | None = None


def recognize_explicit_template(template_key: str) -> IntentRecognition:
    """Lookup for the caller's controlled legacy template selector, never free text.

    The caller, not this helper, must enforce which explicit selections are
    permitted. Returning a key is not approval to execute that template.
    """
    if not isinstance(template_key, str) or template_key not in TEMPLATE_KEYS:
        return IntentRecognition("unknown", None, IntentParameters(), "UNKNOWN_EXPLICIT_TEMPLATE")
    return IntentRecognition("bound", template_key, IntentParameters(), "EXPLICIT_TEMPLATE")


class _Unresolved(Exception):
    def __init__(self, status: Status, code: str, question: str):
        self.status, self.code, self.question = status, code, question


def _key(value: str) -> str:
    return value.strip().casefold()


def _strip_leading(clause: str) -> str:
    # Strip only enumerated leading context. In particular, leave “只”、negation
    # and target text in place for the normal restriction and binding rules.
    clause = _LEADING.sub("", clause.strip(), count=1)
    clause = _PREVIEW_HEADER.sub("", clause, count=1)
    return _LEADING.sub("", clause, count=1).strip()


def _catalog_name_keys(name: str) -> set[tuple[str, str]]:
    """Closed, word-based categories for trusted catalog names, not fuzzy features."""
    keys = set()
    if name.endswith("机房"):
        keys.add(("room", ""))
    if match := _WAREHOUSE_NAME.fullmatch(name):
        keys.add(("warehouse", match["direction"]))
    if name.endswith(_PV_SUFFIXES):
        keys.add(("pv", ""))
        if (match := _PV_NAME.fullmatch(name)) and match["direction"]:
            keys.add(("pv", match["direction"]))
    return keys


def _inspection_match(clause: str) -> re.Match | None:
    return _INSPECTION.fullmatch(clause) or _SELECT_TARGET.fullmatch(clause)


def _ordered_clauses(clauses: list[str], exact_names: Collection[str]) -> tuple[list[str], bool]:
    # Normalize only complete, bounded two-part forms. This is the requested
    # ordering of named entities, not scheduling or proof of feasible execution.
    def literal_task(clause: str) -> bool:
        match = _inspection_match(clause)
        return match is not None and _key(match["names"]) in exact_names

    def remove_cue(clause: str, cue: str) -> str:
        match = re.match(cue, clause)
        if match is None:
            return clause
        if _key(clause) in exact_names:
            raise _Unresolved("clarify", "ORDER_UNRESOLVED", "顺序词也可能是名称的一部分，请明确对象和先后。")
        return clause[match.end():].strip()

    if all(literal_task(clause) for clause in clauses):
        return clauses, False
    operands = None
    if len(clauses) == 2:
        first, second = clauses
        if first.endswith("之前") and second.startswith("先"):
            if literal_task(first):
                raise _Unresolved("clarify", "ORDER_UNRESOLVED", "「之前」也可能是名称的一部分，请明确对象和先后。")
            operands = remove_cue(second, "先"), first[:-2]
        elif first.startswith("先") and second.startswith("再"):
            operands = remove_cue(first, "先"), remove_cue(second, "再")
        elif first.endswith("之后"):
            if literal_task(first):
                raise _Unresolved("clarify", "ORDER_UNRESOLVED", "「之后」也可能是名称的一部分，请明确对象和先后。")
            operands = first[:-2], remove_cue(second, "(?:再|然后)")
    elif len(clauses) == 1:
        if match := _THEN_INLINE.fullmatch(clauses[0]):
            operands = match.groups()
        elif match := _AFTER_INLINE.fullmatch(clauses[0]):
            operands = match[1], remove_cue(match[2], "(?:再|然后)")
    if operands is not None:
        left, right = map(_strip_leading, operands)
        if (not left or not right or any(_ORDER_CUE.search(c) and not literal_task(c) for c in (left, right))
                or not any(_inspection_match(clause) for clause in (left, right))):
            raise _Unresolved("clarify", "ORDER_UNRESOLVED", "请明确要按顺序核对的两个任务。")
        # A bare noun is supported only in this complete sequence in which the
        # other operand supplies the inspection action; it must still bind exactly.
        return [clause if _inspection_match(clause) else f"核对{clause}" for clause in (left, right)], True
    if any(_ORDER_CUE.search(clause) and not literal_task(clause) for clause in clauses):
        raise _Unresolved("clarify", "ORDER_UNRESOLVED", "请明确先核对哪个对象、再核对哪个。")
    return clauses, False


class RuleIntentRecognizer:
    """Use exact names, closed lexical rewrites and bounded grammar; no implicit I/O."""

    def __init__(self, catalog: Iterable[CatalogEntry]):
        self._entries: dict[str, CatalogEntry] = {}
        aliases: dict[str, set[str]] = {}
        lexical: dict[tuple[str, str], set[str]] = {}
        for entry in catalog:
            if not entry.entity_id.strip() or entry.entity_id in self._entries or not entry.label.strip():
                raise ValueError("Each catalog entry needs a unique nonempty ID and label")
            self._entries[entry.entity_id] = entry
            keys = set()
            for alias in (entry.label, *entry.aliases):
                name = _key(alias)
                if not name:
                    raise ValueError("Catalog aliases must not be empty")
                aliases.setdefault(name, set()).add(entry.entity_id)
                keys.update(_catalog_name_keys(name))
            for family in ("pv", "warehouse"):
                directions = {key for key in keys if key[0] == family and key[1]}
                if len(directions) > 1:
                    keys.difference_update(directions)
            for key in keys:
                lexical.setdefault(key, set()).add(entry.entity_id)
        self._aliases = {name: tuple(sorted(ids)) for name, ids in aliases.items()}
        self._lexical = {name: tuple(sorted(ids)) for name, ids in lexical.items()}

    def _choices(self, name: str) -> tuple[str, ...]:
        exact = self._aliases.get(name, ())
        if name == "机房":
            return tuple(sorted(set(exact) | set(self._lexical.get(("room", ""), ()))))
        pv = _PV_NAME.fullmatch(name)
        if pv and not pv["direction"]:
            # An exact generic alias must not hide another catalog array.
            return tuple(sorted(set(exact) | set(self._lexical.get(("pv", ""), ()))))
        if exact:
            return exact
        if pv:
            return self._lexical.get(("pv", pv["direction"]), ())
        if warehouse := _WAREHOUSE_NAME.fullmatch(name):
            return self._lexical.get(("warehouse", warehouse["direction"]), ())
        return ()

    def _bind(self, phrase: str, referents: tuple[str, ...]) -> Binding:
        mention = phrase.strip()
        name = _key(mention)
        if name in _REFERENCES:
            if not referents:
                raise _Unresolved("clarify", "REFERENCE_CONTEXT_REQUIRED", f"「{mention}」指哪个目录对象？")
            if name in _BUILDING_REFERENCES and len(referents) == 1:
                entry = self._entries[referents[0]]
                if not any(_key(label).endswith(("楼", "建筑", "仓库", "仓")) for label in (entry.label, *entry.aliases)):
                    raise _Unresolved("clarify", "REFERENCE_KIND_UNVERIFIED", "请明确所指建筑的名称。")
            choices = referents
        else:
            choices = self._choices(name)
        if not choices:
            raise _Unresolved("unknown", "TARGET_NOT_IN_CATALOG", f"目录中没有「{mention}」。请明确设备或区域名称。")
        if len(choices) > 1:
            labels = [self._entries[choice].label for choice in choices]
            if len(set(labels)) != len(labels):
                labels = [f"{label}（{choice}）" for label, choice in zip(labels, choices)]
            options = "」还是「".join(labels)
            raise _Unresolved("clarify", "TARGET_AMBIGUOUS", f"「{mention}」指的是「{options}」？")
        return Binding(choices[0], mention)

    def _bind_targets(self, phrase: str, referents: tuple[str, ...]) -> list[Binding]:
        if _key(phrase) in self._aliases or _key(phrase) in _REFERENCES:
            return [self._bind(phrase, referents)]
        if _RESTRICTION.search(phrase):
            raise _Unresolved("clarify", "UNRESOLVED_RESTRICTION", "请分开说明要处理的目标和要排除或仅作参照的对象。")
        if _ALTERNATIVE.search(phrase):
            raise _Unresolved("clarify", "TARGET_ALTERNATIVES", f"「{phrase.strip()}」中本轮具体选哪一个？")
        return [self._bind(part, referents) for part in _TARGET_SEPARATOR.split(phrase)]

    def _check_exclusive(self, targets: Iterable[Binding]) -> None:
        selected: dict[str, CatalogEntry] = {}
        for target in targets:
            entry = self._entries[target.entity_id]
            group = entry.exclusive_group
            if not group:
                continue
            other = selected.get(group)
            if other is not None and other.entity_id != entry.entity_id:
                raise _Unresolved(
                    "clarify", "CONFLICTING_TARGETS",
                    f"「{other.label}」和「{entry.label}」在本轮目录中只能选一个。请确认哪一个。",
                )
            selected[group] = entry

    def recognize(self, objective: str, *, referent_ids: Iterable[str] = ()) -> IntentRecognition:
        """`referent_ids` is explicit caller context from this catalog, not implicit history."""
        if not isinstance(objective, str) or not objective.strip() or len(objective) > _MAX_OBJECTIVE_LENGTH:
            return IntentRecognition("unknown", None, IntentParameters(), "INVALID_OBJECTIVE")
        if _GUARDED_LANGUAGE.search(objective):
            return IntentRecognition(
                "clarify", None, IntentParameters(), "GUARDED_TEMPLATE",
                "普通任务原话不选择应急模板。请明确要预览的普通任务。",
            )

        targets: dict[str, Binding] = {}
        references: dict[str, Binding] = {}
        excluded: dict[str, Binding] = {}
        only: frozenset[str] | None = None
        kind: str | None = None
        status_scope: str | None = None
        try:
            try:
                referents = tuple(referent_ids) if not isinstance(referent_ids, (str, bytes)) else (None,)
            except TypeError:
                referents = (None,)
            if any(not isinstance(key, str) or key not in self._entries for key in referents):
                raise _Unresolved("clarify", "REFERENCE_CONTEXT_INVALID", "指代上下文不属于当前目录，请明确对象。")
            referents = tuple(sorted(set(referents)))
            # Scan restrictions before positive clauses. Even an earlier ambiguous
            # target must not wipe a later, resolved exclusion during clarification.
            remaining = self._read_restrictions(objective, references, excluded, referents)
            remaining, explicit_order = _ordered_clauses(remaining, self._aliases)
            for clause in remaining:
                if match := _STATUS_QUERY.fullmatch(clause):
                    proposed_kind = "status_only"
                    scope = _STATUS_SCOPES[match["kind"]]
                    if status_scope is not None and status_scope != scope:
                        raise _Unresolved("clarify", "STATUS_SCOPE_CONFLICT", "请明确只查哪一类状态。")
                    status_scope = scope
                elif _TAKEOFF_LAND_PREVIEW.fullmatch(clause):
                    proposed_kind = "simple_takeoff_land"
                elif match := _inspection_match(clause):
                    proposed_kind = "inspection_snapshot"
                    bindings = self._bind_targets(match["names"], referents)
                    ids = frozenset(entry.entity_id for entry in bindings)
                    if len(ids) != len(bindings) or not ids.isdisjoint(targets):
                        raise _Unresolved("clarify", "REPEATED_TARGET", "目标重复。请确认本轮需要核对哪些对象。")
                    if match.groupdict().get("only"):
                        if only is not None and only != ids:
                            raise _Unresolved("clarify", "CONFLICTING_RESTRICTIONS", "有多个不同的「只」选范围，请确认。")
                        only = ids
                    targets.update((entry.entity_id, entry) for entry in bindings)
                else:
                    if _RESTRICTION.search(clause):
                        raise _Unresolved("clarify", "UNRESOLVED_RESTRICTION", "请明确哪些对象要处理、哪些只作参照或明确排除。")
                    if clause.startswith("去") and _MOVE_SEPARATOR.search(clause):
                        # Understand the conflict, but do not turn a motion phrase into a template.
                        self._check_exclusive(self._bind(part, referents) for part in _MOVE_SEPARATOR.split(clause[1:]))
                        raise _Unresolved("clarify", "TASK_TYPE_REQUIRED", "请说明这些区域要核对什么，不从移动描述猜任务类型。")
                    raise _Unresolved("unknown", "UNSUPPORTED_OBJECTIVE", "请说明要查询哪类状态，或巡检哪处目录设备。")
                if kind is not None and kind != proposed_kind:
                    raise _Unresolved("clarify", "MULTIPLE_INTENTS", "这句话包含不同任务类型。请明确本轮先预览哪一项。")
                kind = proposed_kind

            if overlap := (targets.keys() & excluded.keys()):
                label = self._entries[next(key for key in targets if key in overlap)].label
                raise _Unresolved("clarify", "TARGET_ROLE_CONFLICT", f"「{label}」同时被指定为目标和排除项。请确认它的用途。")
            if only is not None and not targets.keys() <= only:
                raise _Unresolved("clarify", "CONFLICTING_RESTRICTIONS", "请求同时限定了「只」核对的对象和额外目标。请确认范围。")
            self._check_exclusive(targets.values())
            if kind is None:
                if not excluded:
                    raise _Unresolved("unknown", "INVALID_OBJECTIVE", "请填写要查询的状态，或要巡检的设备。")
                raise _Unresolved("clarify", "TASK_TYPE_REQUIRED", "已保留参照和排除项；请明确本轮要处理的任务和目标。")
            if kind != "inspection_snapshot" and excluded:
                raise _Unresolved("clarify", "RESTRICTION_NOT_EXPRESSIBLE", "当前任务类型无法表达这些参照或排除项，请明确任务。")
        except _Unresolved as issue:
            # Keep only known restrictions for clarification; no partial positive binding.
            params = IntentParameters(reference_only=tuple(references.values()), excluded_targets=tuple(excluded.values()))
            return IntentRecognition(issue.status, None, params, issue.code, issue.question)

        params = IntentParameters(
            targets=tuple(targets.values()), reference_only=tuple(references.values()),
            excluded_targets=tuple(excluded.values()), only_listed_targets=only is not None, status_scope=status_scope,
            target_order_basis=("explicit_sequence" if explicit_order else "mention_order") if len(targets) > 1 else None,
        )
        return IntentRecognition("bound", kind, params, "INTENT_BOUND")

    def _read_restrictions(
        self, objective: str, references: dict[str, Binding], excluded: dict[str, Binding], referents: tuple[str, ...],
    ) -> list[str]:
        parts = _CLAUSES.split(objective)
        remaining: list[str] = []
        first_issue: _Unresolved | None = None
        after_reference = False
        for index in range(0, len(parts), 2):
            clause = _strip_leading(parts[index])
            if not clause:
                continue
            if (after_reference and index and parts[index - 1] in {"，", ","}
                    and _REFERENCE_TAIL.fullmatch(clause)):
                # Within this phrase, “不用核对” refers back to the reference.
                # Do not consume a separate sentence or a global “不用巡检”.
                after_reference = False
                continue
            after_reference = False
            try:
                if match := _REFERENCE.fullmatch(clause):
                    entry = self._bind(match["name"], referents)
                    references.setdefault(entry.entity_id, entry)
                    excluded.setdefault(entry.entity_id, entry)
                    after_reference = True
                elif match := (_EXCLUDE_BEFORE.fullmatch(clause) or _EXCLUDE_AFTER.fullmatch(clause)):
                    for entry in self._bind_targets(match["names"], referents):
                        excluded.setdefault(entry.entity_id, entry)
                else:
                    remaining.append(clause)
            except _Unresolved as issue:
                if first_issue is None:
                    first_issue = issue
        if first_issue is not None:
            raise first_issue
        return remaining
