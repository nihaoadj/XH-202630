"""One-shot deterministic generator for source_locating_v1 fixtures (T42 P1).

Run from repo root:
    .venv/python.exe backend/tests/fixtures/claim_extraction/source_locating_v1/_generate.py

Produces manifest.json, calibration.json, acceptance.json, rules_parameters.json
and a frozen v1 (no source_locating) policy snapshot copy. Every sample is
synthetic and carries its source group, error class and label justification.

The generator is retained in-tree only for provenance; the produced JSON is the
frozen, hash-locked deliverable that the eval script and tests consume.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
POLICY_SRC = Path(__file__).resolve().parents[1] / "density_v1" / "policies" / "estimate_2_0_baseline.json"

GROUPS = ["讲义", "实操", "测试", "案例", "清单", "混合"]


def _fact_paragraph(i: int) -> str:
    return (f"在学习 Python 的第{i}个阶段，学习者需要同时掌握变量、循环和函数这三个核心概念，"
            f"并能够独立编写可运行的脚本。")


def _fact_crlf(i: int) -> str:
    return f"第一步：配置环境变量。\n第二步：运行第{i}个示例脚本并观察输出结果。"


def _fact_spaces(i: int) -> str:
    return f"注意  在调用第{i}个接口之前，必须  先完成身份验证与参数校验。"


def _fact_omit(i: int) -> str:
    return (f"第{i}章讲解了数据结构的核心概念，其中链表的特点是插入和删除操作非常高效，"
            f"而数组的随机访问速度更快。")


def _fact_dup(i: int) -> str:
    return (f"同学们在第{i}节课学习习了递归算法的基本思想，随后又通过树形结构的遍历问题对递归过程进行了巩固和复习。")


def _fact_typo(i: int) -> str:
    return (f"第{i}个实验要求同学们正确地把两种不同的溶液混合均匀，并且在操作过程中认真记录每一次测量的具体数值变化情况。")


def _fact_negation(i: int) -> str:
    return (f"在正式开始第{i}个任务之前，不能跳过任何一步安全校验，否则最终结果将被判定为无效并需要重新提交。")


def _fact_number(i: int) -> str:
    return (f"第{i}项实验的标准反应时间为{i + 3}小时，如果超过该阈值就应当立即重新校准设备参数并重新记录结果。")


def _fact_synonym(i: int) -> str:
    return (f"系统会自动保存第{i}份学习报告的全部内容，用户无需手动点击任何按钮即可完成数据备份操作。")


def _fact_short(i: int) -> str:
    return f"示例{i}号"


def _span(text: str, needle: str) -> tuple[int, int]:
    found = text.find(needle)
    assert found >= 0, "needle not found"
    assert text.find(needle, found + 1) < 0, f"needle not unique: {needle!r}"
    return found, found + len(needle)


def _sample(sample_id, group, split, category, error_class, unit_kind, text, unit_start, unit_end,
            ref, claim_text, expect, justification):
    return {
        "id": sample_id,
        "source_group": group,
        "split": split,
        "category": category,
        "error_class": error_class,
        "unit_kind": unit_kind,
        "text": text,
        "unit_start": unit_start,
        "unit_end": unit_end,
        "ref": ref,
        "claim_text": claim_text,
        "claim_type": "factual",
        "expect": expect,
        "label_justification": justification,
        "synthetic": True,
    }


def build() -> dict:
    samples = []

    def emit(group, split, category, error_class, unit_kind, text, ref, claim_text, expect, justification,
             unit_start=None, unit_end=None):
        start = 0 if unit_start is None else unit_start
        end = len(text) if unit_end is None else unit_end
        samples.append(_sample(
            f"{group}-{split}-{category}-{len(samples):03d}", group, split, category, error_class,
            unit_kind, text, start, end, ref, claim_text, expect, justification))

    exact_quota = [4, 4, 3, 3, 3, 3]
    fmt_quota = [4, 4, 3, 3, 3, 3]
    edit_quota = [4, 4, 3, 3, 3, 3]
    reject_quota = [10, 10, 10, 10, 10, 10]

    index = [0] * len(GROUPS)

    def next_i(g):
        i = index[g]
        index[g] += 1
        return i

    # ---- exact (unique verbatim copy) ----
    for split in ("calibration", "acceptance"):
        for g, group in enumerate(GROUPS):
            for _ in range(exact_quota[g]):
                i = next_i(g)
                fact = _fact_paragraph(i)
                text = f"{group}教学材料：{fact} 以上是本节的核心内容。"
                s, e = _span(text, fact)
                emit(group, split, "exact", "unique_exact", "paragraph", text, fact, fact,
                     {"accept": True, "start": s, "end": e, "code": "accepted"},
                     "唯一精确命中，模型逐字复制，服务端按 A 层唯一精确定位")

    # ---- format (controlled CRLF + narrative space folding) ----
    for split in ("calibration", "acceptance"):
        for g, group in enumerate(GROUPS):
            for k in range(fmt_quota[g]):
                i = next_i(g)
                if k % 2 == 0:
                    fact = _fact_crlf(i)
                    text = f"{group}操作说明：\n{fact}\n以上步骤完成后即可结束。"
                    ref = fact.replace("\n", "\r\n")
                    cls, just = "crlf", "CRLF→LF 受控格式恢复，规范化双方后映射回唯一原文区间"
                else:
                    fact = _fact_spaces(i)
                    text = f"{group}注意事项：{fact} 请严格遵循。"
                    ref = fact.replace("  ", " ")
                    cls, just = "space_fold", "叙述内连续 ASCII 横向空格折叠，映射回唯一原文区间"
                s, e = _span(text, fact)
                emit(group, split, "format", cls, "paragraph", text, ref, fact,
                     {"accept": True, "start": s, "end": e, "code": "accepted"}, just)

    # ---- edit (supported bounded edit: omission / duplication / typo) ----
    for split in ("calibration", "acceptance"):
        for g, group in enumerate(GROUPS):
            for k in range(edit_quota[g]):
                i = next_i(g)
                if k % 3 == 0:
                    fact = _fact_omit(i)
                    ref = fact.replace("的", "", 1)
                    cls, just = "function_word_omission", "模型漏抄白名单虚词「的」，属于 omitted_function_word"
                elif k % 3 == 1:
                    fact = _fact_dup(i)
                    ref = fact.replace("学习", "学习习", 1)
                    cls, just = "duplicated_char", "模型意外重复相邻字符「习」，属于 duplicated_char"
                else:
                    fact = _fact_typo(i)
                    ref = fact.replace("地", "的", 1)
                    cls, just = "controlled_typo", "受控错字对 地/的 替换，属于 controlled_typo"
                assert len(fact) >= 40, f"edit fact too short: {fact}"
                text = f"{group}知识点：{fact} 请结合示例理解。"
                s, e = _span(text, fact)
                emit(group, split, "edit", cls, "paragraph", text, ref, fact,
                     {"accept": True, "start": s, "end": e, "code": "accepted"}, just)

    # ---- reject (must-reject / boundary), 10 distinct rotations per group ----
    for split in ("calibration", "acceptance"):
        for g, group in enumerate(GROUPS):
            for k in range(reject_quota[g]):
                i = next_i(g)
                if k == 0:
                    fact = _fact_paragraph(i)
                    text = f"{group}重复段落：{fact} 再次强调：{fact}"
                    ref, claim, kind = fact, fact, "paragraph"
                    expect = {"accept": False, "code": "ambiguous_exact"}
                    just = "同一 target unit 内两处精确命中，A 层唯一精确必须歧义拒绝"
                    emit(group, split, "reject", "ambiguous_exact", kind, text, ref, claim, expect, just)
                elif k == 1:
                    fact = _fact_number(i)
                    changed = fact.replace(f"{i + 3}小时", f"{i + 8}小时")
                    text = f"{group}参数要求：{fact}"
                    expect = {"accept": False, "code": "protected_content_changed"}
                    just = "数字内容被改写，触及保护表，必须拒绝"
                    emit(group, split, "reject", "protected_content_changed", "paragraph", text, changed, fact, expect, just)
                elif k == 2:
                    fact = _fact_negation(i)
                    changed = fact.replace("不能", "能")
                    text = f"{group}安全规范：{fact}"
                    expect = {"accept": False, "code": "protected_content_changed"}
                    just = "否定词「不」被删除，触及保护表，必须拒绝"
                    emit(group, split, "reject", "protected_content_changed", "paragraph", text, changed, fact, expect, just)
                elif k == 3:
                    fact = _fact_synonym(i)
                    changed = fact.replace("保存", "储存")
                    text = f"{group}功能说明：{fact}"
                    expect = {"accept": False, "code": "edit_not_allowed"}
                    just = "同义词改写（保存→储存）不属于白名单编辑，必须拒绝"
                    emit(group, split, "reject", "edit_not_allowed", "paragraph", text, changed, fact, expect, just)
                elif k == 4:
                    fact = _fact_short(i)
                    changed = fact + "变"
                    text = f"{group}简例：{fact}"
                    expect = {"accept": False, "code": "no_candidate"}
                    just = "短引用含误差且长度低于 min_effective_chars，C 层直接无候选"
                    emit(group, split, "reject", "no_candidate", "paragraph", text, changed, fact, expect, just)
                elif k == 5:
                    fact = f"def compute_{i}(x):\n    return x + {i}"
                    changed = f"def compute_{i}(x):\n    return  x + {i}"
                    text = f"{group}代码示例：\n{fact}\n# end"
                    expect = {"accept": False, "code": "no_candidate"}
                    just = "代码敏感区间不套普通空格折叠，归一化后无候选"
                    emit(group, split, "reject", "no_candidate", "code", text, changed, fact, expect, just)
                elif k == 6:
                    # Neighbouring-unit uniqueness: the verbatim fact sits outside
                    # the current unit span, so locating inside it must find nothing.
                    fact = _fact_paragraph(i)
                    text = f"{group}前置：{fact}"
                    prefix = f"{group}前置："
                    expect = {"accept": False, "code": "no_candidate"}
                    just = "正文位于相邻 unit，当前 target unit 内无候选（不跨 unit 检索）"
                    emit(group, split, "reject", "no_candidate", "paragraph", text, fact, fact, expect, just,
                         unit_start=0, unit_end=len(prefix))
                elif k == 7:
                    fact = _fact_paragraph(i)
                    changed = fact.replace("变量", "变量变量")
                    text = f"{group}说明：{fact}"
                    expect = {"accept": False, "code": "edit_not_allowed"}
                    just = "意外重复一个多字符词「变量」而非相邻单字符，超出白名单，必须拒绝"
                    emit(group, split, "reject", "edit_not_allowed", "paragraph", text, changed, fact, expect, just)
                elif k == 8:
                    fact = _fact_typo(i)
                    changed = fact.replace("正确", "精确")
                    text = f"{group}要求：{fact}"
                    expect = {"accept": False, "code": "edit_not_allowed"}
                    just = "主体/对象词替换（正确→精确）超出受控错字对，必须拒绝"
                    emit(group, split, "reject", "edit_not_allowed", "paragraph", text, changed, fact, expect, just)
                else:  # k == 9
                    long_text = f"{group}{i}号超长引用" + "数据" * 1000
                    text = f"{group}长引用：{long_text}"
                    expect = {"accept": False, "code": "source_too_long"}
                    just = "引用超过 2000 字符上限，必须 source_too_long 拒绝"
                    emit(group, split, "reject", "source_too_long", "paragraph", text, long_text, long_text, expect, just)

    samples.sort(key=lambda s: (s["split"], s["source_group"], s["category"], s["id"]))
    return {"calibration": [s for s in samples if s["split"] == "calibration"],
            "acceptance": [s for s in samples if s["split"] == "acceptance"]}


if __name__ == "__main__":
    data = build()
    cal, acc = data["calibration"], data["acceptance"]
    assert len(cal) == 120 and len(acc) == 120, (len(cal), len(acc))

    def counts(samples):
        c = {"exact": 0, "format": 0, "edit": 0, "reject": 0}
        for s in samples:
            c[s["category"]] += 1
        return c

    for name, samples in (("calibration", cal), ("acceptance", acc)):
        c = counts(samples)
        assert c == {"exact": 20, "format": 20, "edit": 20, "reject": 60}, (name, c)
        assert len({s["source_group"] for s in samples}) == 6

    assert not ({s["text"] for s in cal} & {s["text"] for s in acc}), "text leaked across partitions"
    assert all(s["synthetic"] for s in cal + acc)

    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "calibration.json").write_text(json.dumps(cal, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "acceptance.json").write_text(json.dumps(acc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def sha256_file(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    legacy = json.loads(POLICY_SRC.read_text(encoding="utf-8"))
    (ROOT / "policies").mkdir(parents=True, exist_ok=True)
    (ROOT / "policies" / "estimate_2_0_baseline.json").write_text(
        json.dumps(legacy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    frozen_gates = {
        "unique_exact_span_accuracy": 1.0,
        "format_recovery_min": 0.95,
        "edit_recovery_min": 0.80,
        "must_reject_wrong_accept": 0,
        "accepted_wrong_span": 0,
    }
    try:
        from app.agents.resource_workflows.learning_documents.claim_extraction.source_locating import load_rules
        rules_hash = load_rules().hash
    except Exception:
        rules_hash = None
    rules_params = {
        "version": "source-locating-rules-v1",
        "rules_hash": rules_hash,
        "max_edits": 2,
        "max_edit_ratio": 0.04,
        "min_effective_chars": 40,
        "min_score_margin": 0.02,
        "frozen_gates": frozen_gates,
    }
    (ROOT / "rules_parameters.json").write_text(
        json.dumps(rules_params, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest = {
        "schema_version": "source-locating-fixtures-1.0",
        "synthetic": True,
        "splits": {
            "calibration": {"path": "calibration.json", "sha256": sha256_file(ROOT / "calibration.json"), "count": len(cal)},
            "acceptance": {"path": "acceptance.json", "sha256": sha256_file(ROOT / "acceptance.json"), "count": len(acc)},
        },
        "source_groups": GROUPS,
        "category_counts": {"exact": 20, "format": 20, "edit": 20, "reject": 60},
        "legacy_snapshot": {
            "path": "policies/estimate_2_0_baseline.json",
            "sha256": sha256_file(ROOT / "policies" / "estimate_2_0_baseline.json"),
            "note": "frozen v1 EstimatePolicy without source_locating; byte-compat reference",
        },
        "rules_parameters": {"path": "rules_parameters.json"},
        "frozen_gates": frozen_gates,
    }
    (ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"calibration": len(cal), "acceptance": len(acc),
                      "groups": sorted({s['source_group'] for s in cal + acc}),
                      "cal_counts": counts(cal), "acc_counts": counts(acc)},
                     ensure_ascii=False, indent=2))
