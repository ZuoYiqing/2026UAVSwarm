from __future__ import annotations

import pytest

from uavswarm_llm_lab.intent_recognizer import CatalogEntry, RuleIntentRecognizer


CATALOG = (
    CatalogEntry("pv-w", "西侧光伏区", ("园区西面一排用于发电的太阳能板",)),
    CatalogEntry("heat", "热泵机房"),
    CatalogEntry("warehouse-n", "北仓"),
    CatalogEntry("building", "中央建筑"),
)


def ids(result, role="targets"):
    return [binding.entity_id for binding in getattr(result.parameters, role)]


@pytest.mark.parametrize("prefix", ["请", "帮我", "给我", "本轮", "这一轮", "麻烦", "现在", "请帮我", "麻烦，现在"])
def test_bounded_prefixes_preserve_target(prefix):
    result = RuleIntentRecognizer(CATALOG).recognize(f"{prefix}巡检西侧光伏区")
    assert result.status == "bound" and ids(result) == ["pv-w"]
    assert result.parameters.targets[0].evidence == "西侧光伏区"


def test_preview_header_and_only_scope():
    rules = RuleIntentRecognizer(CATALOG)
    for text, target in (
        ("三机联巡任务预演：只核对西侧光伏区。", "pv-w"),
        ("本轮只核对热泵机房。", "heat"),
    ):
        r = rules.recognize(text)
        assert r.status == "bound" and ids(r) == [target] and r.parameters.only_listed_targets
    r = rules.recognize("麻烦这一轮别核对北仓，西侧光伏区之后先别执行。")
    assert not ids(r) and ids(r, "excluded_targets") == ["warehouse-n"]


@pytest.mark.parametrize(("phrase", "target"), [
    ("那排发电板", "pv-w"),
    ("园区西面那排用于发电的太阳能板", "pv-w"),
    ("北边的仓库", "warehouse-n"),
    ("机房", "heat"),
])
def test_whole_lexical_rewrite_keeps_verbatim_evidence(phrase, target):
    result = RuleIntentRecognizer(CATALOG).recognize(f"这轮检查{phrase}。")
    assert result.status == "bound" and ids(result) == [target]
    assert result.parameters.targets[0].evidence == phrase


@pytest.mark.parametrize("phrase", ["空调机房", "南边的仓库", "那排风力发电机", "光伏二区"])
def test_rewrite_does_not_match_similar_or_absent_names(phrase):
    result = RuleIntentRecognizer(CATALOG).recognize(f"核对{phrase}。")
    assert result.status == "unknown" and not ids(result)


def test_generic_names_never_pick_one_of_multiple_candidates():
    rules = RuleIntentRecognizer((
        *CATALOG,
        CatalogEntry("pv-e", "东侧光伏区", ("那排发电板",)),
        CatalogEntry("pump", "循环泵机房", ("机房",)),
    ))
    for phrase in ("那排发电板", "机房"):
        r = rules.recognize(f"巡检{phrase}。")
        assert r.status == "clarify" and r.reason_code == "TARGET_AMBIGUOUS" and not ids(r)
    assert ids(rules.recognize("巡检西面那排光伏板。")) == ["pv-w"]


@pytest.mark.parametrize(("pronoun", "referent"), [("那个", "heat"), ("这个", "heat"), ("那栋", "building"),
                                                  ("刚才说的那个", "pv-w")])
def test_pronouns_need_explicit_unique_context(pronoun, referent):
    rules = RuleIntentRecognizer(CATALOG)
    no_context = rules.recognize(f"检查{pronoun}。")
    assert no_context.reason_code == "REFERENCE_CONTEXT_REQUIRED" and not ids(no_context)
    unique = rules.recognize(f"检查{pronoun}。", referent_ids=(referent,))
    assert unique.status == "bound" and ids(unique) == [referent]
    assert unique.parameters.targets[0].evidence == pronoun


def test_ambiguous_stale_or_wrong_kind_reference_never_binds():
    rules = RuleIntentRecognizer(CATALOG)
    for context, code in (
        (("building", "heat"), "TARGET_AMBIGUOUS"),
        (("building", "other-scene"), "REFERENCE_CONTEXT_INVALID"),
        (("pv-w",), "REFERENCE_KIND_UNVERIFIED"),
        ("building", "REFERENCE_CONTEXT_INVALID"),
    ):
        r = rules.recognize("核对那栋。", referent_ids=context)
        assert r.status == "clarify" and r.reason_code == code and not ids(r)
    r = rules.recognize("中央建筑只用来定位，不用核对；核对那栋。", referent_ids=("building",))
    assert (r.status, r.reason_code, ids(r)) == ("clarify", "TARGET_ROLE_CONFLICT", [])
    assert ids(r, "reference_only") == ids(r, "excluded_targets") == ["building"]


@pytest.mark.parametrize("text", [
    "核对热泵机房之前，先核对西侧光伏区。",
    "先核对西侧光伏区，再核对热泵机房。",
    "核对西侧光伏区之后核对热泵机房。",
    "核对西侧光伏区之后，核对热泵机房。",
    "现在先核对那排发电板，再核对机房。",
    "先核对西侧光伏区，再热泵机房。",
])
def test_explicit_sequence_controls_binding_order(text):
    r = RuleIntentRecognizer(CATALOG).recognize(text)
    assert r.status == "bound" and ids(r) == ["pv-w", "heat"]
    assert r.parameters.target_order_basis == "explicit_sequence"
    assert all(b.evidence in text for b in r.parameters.targets)


def test_unordered_targets_keep_mention_order_without_claiming_sequence():
    rules = RuleIntentRecognizer(CATALOG)
    for text, expected in (
        ("巡检热泵机房和西侧光伏区。", ["heat", "pv-w"]),
        ("巡检西侧光伏区和热泵机房。", ["pv-w", "heat"]),
    ):
        r = rules.recognize(text)
        assert ids(r) == expected and r.parameters.target_order_basis == "mention_order"


@pytest.mark.parametrize("text", [
    "先核对西侧光伏区。",
    "核对热泵机房之前。",
    "先核对西侧光伏区，再核对未知机房。",
    "核对西侧光伏区之后不要核对热泵机房。",
    "先只核对西侧光伏区，再核对热泵机房。",
])
def test_incomplete_or_conflicting_order_never_returns_a_subset(text):
    r = RuleIntentRecognizer(CATALOG).recognize(text)
    assert r.status in ("clarify", "unknown") and not ids(r)
    assert r.parameters.target_order_basis is None


def test_catalog_literal_cannot_be_resplit_into_a_false_sequence():
    rules = RuleIntentRecognizer((
        *CATALOG, CatalogEntry("post", "甲之后服务区"), CatalogEntry("a", "甲"),
        CatalogEntry("service", "服务区"), CatalogEntry("recycled", "再生水机房"),
        CatalogEntry("raw", "生水机房"),
    ))
    r = rules.recognize("巡检甲之后服务区。")
    assert ids(r) == ["post"] and r.parameters.target_order_basis is None
    r = rules.recognize("先核对西侧光伏区，再生水机房。")
    assert r.reason_code == "ORDER_UNRESOLVED" and not ids(r)
