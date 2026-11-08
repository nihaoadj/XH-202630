"""T42: programmatic source locating A -> B -> C on the production ``locate`` entry."""
from types import SimpleNamespace

import pytest

from app.agents.resource_workflows.learning_documents.claim_extraction.prompts.extract_v2 import PROMPT as PROMPT_V2
from app.agents.resource_workflows.learning_documents.claim_extraction.source_locating import (
    LocateCode, WorkCounter, load_rules, locate,
)
from app.models.reviews.claim_extraction import BatchOutputV2, SourceLocatingPolicy, digest

RULES = load_rules()


def make_policy(mode="tolerant_v1", rules=None, **overrides):
    rules = rules or RULES
    locating = SourceLocatingPolicy(
        mode=mode,
        locator_algorithm_version=overrides.get("locator_algorithm_version", "locator-v2"),
        extractor_prompt_hash=digest(PROMPT_V2),
        output_schema_hash=digest(BatchOutputV2.model_json_schema()),
        rules_hash=rules.hash,
        max_edits=overrides.get("max_edits", rules.thresholds.max_edits),
        max_edit_ratio=overrides.get("max_edit_ratio", rules.thresholds.max_edit_ratio),
        min_effective_chars=overrides.get("min_effective_chars", rules.thresholds.min_effective_chars),
        min_score_margin=overrides.get("min_score_margin", rules.thresholds.min_score_margin),
        max_unit_chars=overrides.get("max_unit_chars", rules.thresholds.max_unit_chars),
        max_candidate_chars=overrides.get("max_candidate_chars", rules.thresholds.max_candidate_chars),
        max_dp_cells_per_ref=overrides.get("max_dp_cells_per_ref", rules.thresholds.max_dp_cells_per_ref),
        max_distinct_intervals=overrides.get("max_distinct_intervals", rules.thresholds.max_distinct_intervals),
        max_work_cells_per_batch=overrides.get("max_work_cells_per_batch", rules.thresholds.max_work_cells_per_batch),
    )
    return SimpleNamespace(source_locating=locating)


def unit(kind="paragraph", start=None, end=None):
    return SimpleNamespace(unit_id="u", kind=kind, start=0 if start is None else start,
                           end=end)


def run(text, ref, *, mode="tolerant_v1", kind="paragraph", start=None, end=None, work=None):
    u = unit(kind, start, end if end is not None else len(text))
    return locate(text, u, ref, make_policy(mode), RULES, work or WorkCounter(8000000))


# --- A: unique exact ---------------------------------------------------------

def test_unique_exact_match_is_accepted_at_a_layer():
    text = "这里是唯一的事实陈述句子。"
    ref = "事实陈述"
    s = text.index(ref)
    r = run(text, ref)
    assert r.accepted and r.level == "exact"
    assert (r.start, r.end) == (s, s + len(ref))
    assert text[r.start:r.end] == ref


def test_multiple_exact_matches_are_ambiguous_not_chosen():
    text = "重复内容A 和 重复内容A"
    r = run(text, "重复内容A")
    assert not r.accepted and r.code == LocateCode.AMBIGUOUS_EXACT.value


def test_exact_match_only_searches_the_target_unit():
    text = "单元一：事实陈述。 单元二：事实陈述。"
    r = run(text, "事实陈述", start=0, end=8)
    assert r.accepted and (r.start, r.end) == (4, 8)


# --- B: controlled format ----------------------------------------------------

def test_crlf_reference_is_recovered_inside_narrative():
    text = "第一步：配置环境。\n第二步：运行脚本。"
    ref = "配置环境。\r\n第二步：运行"
    s = text.index("配置环境。\n第二步：运行")
    r = run(text, ref)
    assert r.accepted and r.level == "normalized"
    assert (r.start, r.end) == (s, s + len("配置环境。\n第二步：运行"))


def test_narrative_space_folding_is_recovered():
    text = "注意  这里有两个空格。"
    r = run(text, "注意 这里有两个空格")
    assert r.accepted and r.level == "normalized"
    assert text[r.start:r.end] == "注意  这里有两个空格"


def test_code_spaces_are_not_folded():
    text = "def f(x):\n    return  x + 1"
    r = run(text, "return x + 1", kind="code")
    assert not r.accepted


# --- C: bounded edits (all references >= min_effective_chars) ----------------

def test_omitted_function_word_is_recovered():
    fact = ("这是一个关于数据结构核心概念的详细介绍，其中链表的特点是插入和删除操作非常高效，"
            "而数组的随机访问速度更快。")
    text = f"正文：{fact}"
    s = text.index(fact)
    r = run(text, fact.replace("的", "", 1))
    assert r.accepted and r.level == "approximate"
    assert (r.start, r.end) == (s, s + len(fact))
    assert text[r.start:r.end] == fact


def test_duplicated_character_is_recovered():
    fact = ("同学们在本节课学习习了递归算法的基本思想，随后又通过树形结构的遍历问题对递归过程进行了巩固和复习。")
    text = f"正文：{fact}"
    s = text.index(fact)
    r = run(text, fact.replace("学习", "学学习", 1))
    assert r.accepted and r.level == "approximate"
    assert (r.start, r.end) == (s, s + len(fact))


def test_controlled_typo_pair_is_recovered():
    fact = ("本实验要求同学们正确地把两种不同的溶液混合均匀，并且在操作过程中认真记录每一次测量的具体数值变化情况。")
    text = f"正文：{fact}"
    s = text.index(fact)
    r = run(text, fact.replace("地", "的", 1))
    assert r.accepted and r.level == "approximate"
    assert (r.start, r.end) == (s, s + len(fact))


def test_protected_number_change_is_rejected():
    fact = ("第3项实验的标准反应时间为3小时，如果超过该阈值就应当立即重新校准设备参数并重新记录结果。")
    text = f"正文：{fact}"
    r = run(text, fact.replace("3小时", "8小时"))
    assert not r.accepted and r.code == LocateCode.PROTECTED_CONTENT_CHANGED.value


def test_protected_negation_change_is_rejected():
    fact = ("在正式开始任务之前，绝对不能跳过任何一步安全校验，否则最终结果将被判定为无效并需要重新提交。")
    text = f"正文：{fact}"
    r = run(text, fact.replace("不能", "能"))
    assert not r.accepted and r.code == LocateCode.PROTECTED_CONTENT_CHANGED.value


def test_synonym_swap_is_not_allowed():
    fact = ("系统会自动保存学习报告的全部内容，用户无需手动点击任何按钮即可完成数据备份操作，"
            "学习者随后检查归档材料并核对报告。")
    text = f"正文：{fact}"
    r = run(text, fact.replace("保存", "储存"))
    assert not r.accepted and r.code == LocateCode.EDIT_NOT_ALLOWED.value


def test_subject_word_swap_is_not_allowed():
    fact = ("本实验要求同学们正确地把两种不同的溶液混合均匀，并且认真记录每一次测量的具体数值变化情况。")
    text = f"正文：{fact}"
    r = run(text, fact.replace("正确", "精确"))
    assert not r.accepted and r.code == LocateCode.EDIT_NOT_ALLOWED.value


def test_short_reference_with_error_has_no_candidate():
    text = "示例A号"
    r = run(text, "示例A号变")
    assert not r.accepted and r.code == LocateCode.NO_CANDIDATE.value


def test_overlong_reference_is_rejected():
    long_ref = "数据" * 1001
    r = run("正文：" + long_ref, long_ref)
    assert not r.accepted and r.code == LocateCode.SOURCE_TOO_LONG.value


def test_neighbouring_unit_content_is_not_searched():
    fact = "这是相邻单元里的唯一事实句子。"
    text = f"前置：{fact}"
    r = run(text, fact, start=0, end=3)
    assert not r.accepted


# --- mode / drift / limits ---------------------------------------------------

def test_exact_v1_mode_disables_b_and_c():
    fact = ("这是一个关于数据结构核心概念的详细介绍，其中链表的特点是插入和删除操作非常高效，"
            "而数组的随机访问速度更快。")
    text = f"正文：{fact}"
    r = run(text, fact.replace("的", "", 1), mode="exact_v1")
    assert not r.accepted and r.code == LocateCode.NO_CANDIDATE.value


def test_rules_drift_is_detected_before_searching():
    text = "正文：一个事实句子。"
    policy = make_policy()
    drifted = SimpleNamespace(source_locating=policy.source_locating.model_copy(update={"rules_hash": "0" * 64}))
    r = locate(text, unit(end=len(text)), "事实句子", drifted, RULES)
    assert not r.accepted and r.code == LocateCode.RULES_DRIFT.value


def test_work_limit_is_deterministically_enforced():
    fact = ("这是一个关于数据结构核心概念的详细介绍，其中链表的特点非常明显，需要认真分析其优缺点，"
            "随后记录观察结果并核对原始材料。")
    text = f"正文：{fact}"
    r = run(text, fact.replace("的", "", 1), work=WorkCounter(0))
    assert not r.accepted and r.code == LocateCode.WORK_LIMIT_EXCEEDED.value


def test_missing_source_locating_sub_contract_is_a_programming_error():
    text = "正文：一个事实句子。"
    with pytest.raises(ValueError):
        locate(text, unit(end=len(text)), "事实句子", SimpleNamespace(source_locating=None), RULES)
