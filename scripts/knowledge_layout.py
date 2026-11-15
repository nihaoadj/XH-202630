"""Direct, backed-up file migration; no runtime historical path aliases."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"backend"))
from app.core.retrieval.knowledge_paths import resolve_knowledge_file, LAYOUT_VERSION  # noqa: E402
KB=ROOT/"knowledge_base/rag_engineering_training"
LAYOUT={"version":LAYOUT_VERSION,"loading":"manifest_only","registry":"provenance/registry.json"}
ARCHIVES={
 "sources/registry.json":"provenance/import_batches/pilot.json",
 "sources/bulk/bulk_registry.json":"provenance/import_batches/bulk.json",
 "sources/chinese/registry.json":"provenance/import_batches/chinese.json",
 "sources/bulk_catalog.json":"provenance/catalogs/bulk.json",
 "sources/chinese_catalog.json":"provenance/catalogs/chinese.json",
}

def encoded(value):
    return (json.dumps(value,ensure_ascii=False,indent=2)+"\n").encode("utf-8")

def sha(data):
    return hashlib.sha256(data).hexdigest()

def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def physical(root,name):
    return resolve_knowledge_file(root,name,must_exist=False)

def write_atomic(path,data):
    path=Path(path)
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix="."+path.name+".",suffix=".tmp",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(6):
            try:
                os.replace(name,path)
                break
            except PermissionError:
                if attempt==5:
                    raise
                time.sleep(0.03*(attempt+1))
    finally:
        if os.path.exists(name):
            os.unlink(name)

def destination(spec):
    ident=spec["id"]
    if ident.startswith("module_"):
        return "teaching/zh/"+Path(spec["file"]).name,"zh","project"
    for prefix,lang,publisher in (
        ("source_zh_flag_","zh","flagembedding"),("source_zh_mineru_","zh","mineru"),
        ("source_zh_milvus_","zh","milvus"),("source_zh_hf_","zh","huggingface"),
        ("source_langchain_","en","langchain"),("source_sbert_","en","sentence_transformers"),
        ("source_paper_","en","papers")):
        if ident.startswith(prefix):
            slug=ident[len(prefix):]
            if not slug or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_" for c in slug):
                raise ValueError("unsafe document slug")
            return f"references/{lang}/{publisher}/{slug}/content.md",lang,publisher
    raise ValueError("unclassified document "+ident)

def reference_paths(ident,kind="markdown"):
    body,_,_=destination({"id":ident,"file":"content.md"})
    suffix={"pdf":"pdf","python":"py","py":"py","mdx":"mdx","notebook":"ipynb","ipynb":"ipynb","markdown":"md","md":"md","html_markdown":"md"}[kind]
    return (Path(body).parent/("original."+suffix)).as_posix(),body

def license_destination(path):
    if path.startswith("sources/licenses/"):
        return path.replace("sources/licenses/","licenses/",1)
    if path.startswith("sources/chinese/licenses/"):
        return path.replace("sources/chinese/licenses/","licenses/",1).replace("licenses/hf/","licenses/huggingface/")
    if path=="sources/bulk/licenses/ACL-CC-BY-4.0":
        return "licenses/acl/CC-BY-4.0"
    raise ValueError("unclassified license "+path)

def plan_layout(root=KB):
    root=Path(root).resolve()
    metadata=read_json(root/"metadata.json")
    if metadata.get("storage_layout"):
        raise ValueError("already migrated")
    pilot=read_json(root/"sources/registry.json")
    bulk={x["id"]:x for x in read_json(root/"sources/bulk_catalog.json")["sources"]}
    chinese={x["id"]:x for x in read_json(root/"sources/chinese_catalog.json")["sources"]}
    pilots={x["id"]:x for x in pilot["sources"]}
    mapping=dict(ARCHIVES)
    for doc in metadata["documents"]:
        body,_,_=destination(doc)
        mapping[doc["file"]]=body
        if doc.get("source_snapshot"):
            kind=bulk.get(doc["id"],chinese.get(doc["id"],{})).get("kind")
            if kind is None:
                kind=Path(pilots[doc["id"]]["upstream_path"]).suffix.lstrip(".")
            original,_=reference_paths(doc["id"],kind)
            mapping[doc["source_snapshot"]]=original
    for p in root.rglob("*"):
        if p.is_file() and "licenses" in p.relative_to(root).parts:
            name=p.relative_to(root).as_posix()
            mapping[name]=license_destination(name)
    expected=set(mapping)|{"metadata.json","questionnaire.json","diagnostic_questions.json","assessment_questions.json"}
    actual={p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if expected!=actual or len(set(mapping.values()))!=len(mapping):
        raise ValueError("source inventory is incomplete or ambiguous")
    moves=[]
    for old,new in sorted(mapping.items()):
        source,target=physical(root,old),physical(root,new)
        if not source.is_file() or target.exists():
            raise ValueError("source missing or target collision")
        moves.append({"old":old,"new":new,"sha256":sha(source.read_bytes())})
    return {"schema_version":2,"root":str(root),"metadata_sha256":sha((root/"metadata.json").read_bytes()),"document_count":len(metadata["documents"]),"moves":moves}

def rewrite_paths(value,mapping):
    if isinstance(value,str):
        return mapping.get(value,value)
    if isinstance(value,list):
        return [rewrite_paths(x,mapping) for x in value]
    if isinstance(value,dict):
        result={mapping.get(k,k):rewrite_paths(v,mapping) for k,v in value.items()}
        if isinstance(result.get("asset_hashes"),dict):
            result["asset_hashes"]=dict(sorted(result["asset_hashes"].items()))
        return result
    return value

def registry_payload(root=KB):
    root=Path(root)
    metadata=read_json(root/"metadata.json")
    history={}
    for name in ("pilot","bulk","chinese"):
        history.update({r["id"]:r for r in read_json(root/f"provenance/import_batches/{name}.json")["sources"]})
    documents=[]
    for doc in metadata["documents"]:
        _,lang,publisher=destination(doc)
        entry={"id":doc["id"],"title":doc["title"],"language":lang,"publisher":publisher,
               "kind":"teaching" if publisher=="project" else "authoritative_original",
               "language_origin":history.get(doc["id"],{}).get("language_origin","project_curated" if publisher=="project" else "official_original"),
               "file":doc["file"],"content_sha256":sha(resolve_knowledge_file(root,doc["file"]).read_bytes())}
        if doc.get("source_snapshot"):
            raw=resolve_knowledge_file(root,doc["source_snapshot"]).read_bytes()
            if sha(raw)!=doc["source_hash"] or entry["content_sha256"]!=doc["normalized_hash"]:
                raise ValueError("source body hash drift")
            entry.update(original=doc["source_snapshot"],original_sha256=doc["source_hash"],license=doc["license"],source_urls=doc["source_urls"])
        documents.append(entry)
    hashes={p.relative_to(root).as_posix():sha(p.read_bytes()) for p in sorted(root.rglob("*")) if p.is_file() and p.relative_to(root).as_posix()!="provenance/registry.json"}
    return {"schema_version":1,"layout_version":LAYOUT_VERSION,"document_count":len(documents),"documents":documents,"asset_hashes":hashes}

def check_layout(root=KB):
    root=Path(root)
    expected=registry_payload(root)
    if read_json(root/"provenance/registry.json")!=expected:
        raise ValueError("unified registry drift")
    if (root/"modules").exists() or (root/"sources").exists() or (root/"provenance/path_aliases.json").exists():
        raise ValueError("legacy directory or runtime alias remains")
    print("Layout verified:",len(expected["documents"]),"documents; direct physical paths")
    return expected

def empty_dirs(root):
    for p in sorted((p for p in root.rglob("*") if p.is_dir()),key=lambda p:len(p.parts),reverse=True):
        if not any(p.iterdir()):
            p.rmdir()

def apply_layout(root,plan,receipt_dir):
    root,receipt_dir=Path(root).resolve(),Path(receipt_dir)
    if plan_layout(root)!=plan:
        raise ValueError("preflight plan differs from complete source inventory")
    for name in ("README.md","provenance/registry.json"):
        if physical(root,name).exists():
            raise ValueError("generated user file collision")
    receipt_dir.mkdir(parents=True,exist_ok=False)
    before=(root/"metadata.json").read_bytes()
    (receipt_dir/"metadata-before.source").write_bytes(before)
    mapping={m["old"]:m["new"] for m in plan["moves"]}
    record={"status":"applying","plan":plan,"moved":[]}
    write_atomic(receipt_dir/"receipt.json",encoded(record))
    for move in plan["moves"]:
        source,target=physical(root,move["old"]),physical(root,move["new"])
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():
            raise ValueError("target appeared during migration")
        source.rename(target)
        record["moved"].append(move["old"])
        write_atomic(receipt_dir/"receipt.json",encoded(record))
    # Rewrite generated JSON path fields, not the raw/normalized source bytes.
    for old,new in sorted(ARCHIVES.items(),key=lambda item:0 if 'catalog' in item[1] else 1):
        payload=rewrite_paths(read_json(root/new),mapping)
        if "catalog_sha256" in payload:
            catalog="provenance/catalogs/chinese.json" if "chinese" in new else "provenance/catalogs/bulk.json"
            payload["catalog_sha256"]=sha((root/catalog).read_bytes())
        write_atomic(root/new,encoded(payload))
    metadata=rewrite_paths(json.loads(before),mapping)
    metadata["storage_layout"]=LAYOUT
    write_atomic(root/"metadata.json",encoded(metadata))
    write_atomic(root/"README.md",("# RAG知识库资料\n\n- teaching/zh：6份项目整理的中文模块。\n- references/zh：35份官方中文资料/译本。\n- references/en：21份英文官方资料（包括最初3篇短教程）。\n- 每篇original.*是原文，content.md是可检索正文。\n- licenses：许可；provenance/registry.json：统一清单。\n\n本次直接移动，旧数据库的来源路径尚未重建。换模型时须按新知识版本受控重建SQL目录与向量索引；不可直接覆盖旧版本metadata。\n").encode("utf-8"))
    empty_dirs(root)
    write_atomic(root/"provenance/registry.json",encoded(registry_payload(root)))
    record["status"]="complete"
    write_atomic(receipt_dir/"receipt.json",encoded(record))
    check_layout(root)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group()
    group.add_argument("--apply",action="store_true")
    group.add_argument("--check",action="store_true")
    parser.add_argument("--plan",type=Path,default=ROOT/"docs/update_plan/T9_mapping.json")
    parser.add_argument("--backup",type=Path)
    parser.add_argument("--receipt",type=Path,default=ROOT/"output/test-runs/kb-layout/direct-migration")
    args=parser.parse_args()
    if args.check:
        check_layout()
    elif args.apply:
        for port in (8000,8081,5173):
            with socket.socket() as sock:
                if sock.connect_ex(("127.0.0.1",port))==0:
                    raise ValueError("stop owned project services first")
        plan=read_json(args.plan)
        if plan["root"]!=str(KB.resolve()) or args.backup is None:
            raise ValueError("fixed root and source backup required")
        for item in plan["moves"]:
            path=args.backup/"sources"/item["old"]
            if not path.is_file() or sha(path.read_bytes())!=item["sha256"]:
                raise ValueError("source backup hash mismatch")
        apply_layout(KB,plan,args.receipt)
    else:
        plan=plan_layout()
        write_atomic(args.plan,encoded(plan))
        print("Dry run:",len(plan["moves"]),"assets; no file moved")

if __name__=="__main__":
    main()
