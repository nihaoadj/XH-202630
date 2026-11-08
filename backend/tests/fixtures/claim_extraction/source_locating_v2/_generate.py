"""Generate disjoint synthetic source groups; refuses to overwrite frozen data."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OLD = ROOT.parent / "source_locating_v1"
SOURCES = {
    "calibration": [
        "图书整理员把借阅卡片放进标有编号7的抽屉，随后按书名核对归还记录并整理纸质索引，最后把已经检查的材料收进档案袋。",
        "陶艺学员把湿润的泥坯放在编号7的木板上，接着用海绵擦去边缘水迹并轻轻修整底座，完成后将作品移到通风架上晾干。",
        "园艺助手记录编号7花盆的土壤湿度，接着轻轻拨开表层落叶观察根部状态，再把本次养护的过程写进纸质观察手册。",
        "排练成员把编号7的乐谱摊开放在琴架旁边，接着依照指挥提示练习开头旋律并标注停顿位置，最后整理本次排练的笔记。",
        "摄影学员把编号7的镜头安装到机身上，随后检查对焦环位置并拍摄窗边静物，完成后将拍摄的文件复制到课程资料夹。",
        "织布学徒把编号7的线轴放进木盒，随后沿着织机边缘穿好引线并逐段检查纹理，结束时收起剩余的棉线与练习样布。",
    ],
    "acceptance": [
        "海岸巡查员沿着编号7的栈道寻找潮汐留下的标记，并在纸图上圈出漂流木所在区域，返程时把观察所得交给值班人员归档。",
        "面包师将编号7烤盘中的面团移入发酵柜，等待表面形成细密气孔后取出整形，并把这次制作的过程记在厨房日志中供学徒查阅。",
        "天文社成员使用编号7的星图辨认夜空中相邻的星座，并沿着图示方向调整观测位置，收工时擦净镜片并盖好仪器保护罩。",
        "河流调查小组拿着编号7的记录板观察岸边石块与水流的接触位置，绘制现场草图后比较不同河段的形状，再收齐测绘工具。",
        "修复师从编号7的纸盒取出旧照片并戴好棉质手套，先用软毛刷清扫边缘再放入透明保护袋，并在登记簿注明处理的经过。",
        "舞台工作人员检查编号7的幕布挂钩是否稳固，并把道具沿后台通道摆放整齐，演出结束后重新清点归还的物品并登记破损情况。",
    ],
}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def generate():
    splits = {}
    for split, sources in SOURCES.items():
        records = []
        for category, count in (("exact", 20), ("format", 20), ("edit", 20), ("reject", 60)):
            for i in range(count):
                index = i % len(sources)
                body = sources[index]
                text, ref, gold, start, end = body, body, body, 0, len(body)
                kind, error, accept = "paragraph", category, category != "reject"
                if category == "format":
                    text = "观察  记录：" + body if i % 2 else "操作说明：\n" + body
                    ref = text.replace("  ", " ") if i % 2 else text.replace("\n", "\r\n")
                    gold, end = text, len(text)
                elif category == "edit":
                    if i % 3 == 0:
                        ref = body.replace("的", "", 1)
                    elif i % 3 == 1:
                        ref = body[0] + body
                    else:
                        text = "他检查记录后说明：" + body
                        ref = text.replace("他", "她", 1)
                        gold, end = text, len(text)
                elif category == "reject":
                    reject = i % 10
                    error = f"boundary_{reject}"
                    if reject == 0:
                        ref = body.replace("7", "8")
                    elif reject == 1:
                        ref = "龘" + body[1:]
                    elif reject == 2:
                        text = body + "\n" + body
                    elif reject == 3:
                        text, ref = f"{split}短句", f"{split}短短句"
                    elif reject == 4:
                        text, ref = "前段。" + body, body
                        end = 3
                    elif reject == 5:
                        text = ref = ("甲" if split == "calibration" else "乙") * 2001
                    elif reject == 6:
                        text = body[:40]
                        ref = text[0] + text[:15] + text[15] + text[15:]
                    elif reject == 7:
                        ref = ("丙" if split == "calibration" else "丁") * 60
                    elif reject == 8:
                        text = "叙述  开头：" + body + "\n叙述   开头：" + body
                        ref = "叙述 开头：" + body
                    else:
                        ref = body.replace("编号", "不编号", 1)
                    gold = None
                    if reject != 4:
                        end = len(text)
                expect = {"accept": accept}
                if accept:
                    expect.update(start=start, end=end, code="accepted")
                    end = len(text)
                    expect["end"] = end
                else:
                    expect["code"] = "must_reject"
                records.append({
                    "id": f"{split}-{category}-{i:03d}",
                    "source_group": f"{split}-source-{index}",
                    "source_template": f"{split}-template-{index}",
                    "category": category, "error_class": error,
                    "text": text, "unit_start": 0, "unit_end": end,
                    "unit_kind": kind, "ref": ref,
                    "source_text_gold": gold,
                    "claim_text": "记录人员按材料中描述的步骤完成操作。",
                    "expect": expect,
                    "label_basis": "独立指定原文切片；拒绝用例由位置歧义、冻结边界或未支持编辑构造。",
                })
        splits[split] = records
    manifest = json.loads((OLD / "manifest.json").read_text(encoding="utf-8"))
    manifest["schema_version"] = "source-locating-fixtures-2.0"
    manifest["source_groups"] = [
        f"{split}-source-{i}" for split in SOURCES for i in range(6)
    ]
    manifest["splits"] = {}
    # History is referenced only within this new immutable fixture directory.
    for name in ("rules_parameters.json", "policies/estimate_2_0_baseline.json"):
        dest = ROOT / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            raise FileExistsError(dest)
        dest.write_bytes((OLD / name).read_bytes().replace(b"\r\n", b"\n"))
    manifest["legacy_snapshot"]["sha256"] = hashlib.sha256(
        (ROOT / manifest["legacy_snapshot"]["path"]).read_bytes()).hexdigest()
    for split, records in splits.items():
        path = ROOT / (split + ".json")
        if path.exists():
            raise FileExistsError(path)
        path.write_text(encoded(records), encoding="utf-8", newline="\n")
        manifest["splits"][split] = {
            "path": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "count": len(records),
        }
    dest = ROOT / "manifest.json"
    if dest.exists():
        raise FileExistsError(dest)
    dest.write_text(encoded(manifest), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    generate()
