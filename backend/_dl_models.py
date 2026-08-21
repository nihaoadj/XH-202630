import os
os.environ.pop("HF_ENDPOINT", None)

import requests
from huggingface_hub import list_repo_files

BASE = "https://huggingface.co"
repos = ["BAAI/bge-large-zh-v1.5", "BAAI/bge-reranker-base"]
root = os.path.dirname(os.path.abspath(__file__))


def remote_size(url):
    try:
        h = requests.head(url, timeout=60, allow_redirects=True)
        return int(h.headers.get("Content-Length", "-1"))
    except Exception:
        return -1


for repo in repos:
    short = repo.split("/")[-1]
    local_dir = os.path.join(root, "models", short)
    os.makedirs(local_dir, exist_ok=True)
    files = list_repo_files(repo)
    print(f"REPO {repo} ({len(files)} files): {files}", flush=True)
    has_safetensors = "model.safetensors" in files
    for f in files:
        if f == ".gitattributes":
            continue
        # onnx/ 与 sentence-transformers CrossEncoder 无关，跳过以省流量
        if f.startswith("onnx/"):
            continue
        # 有 safetensors 时跳过冗余的 pytorch_model.bin，省一半流量
        if f == "pytorch_model.bin" and has_safetensors:
            print(f"SKIP {repo}/{f} (safetensors present)", flush=True)
            continue
        url = f"{BASE}/{repo}/resolve/main/{f}"
        dst = os.path.join(local_dir, f)
        os.makedirs(os.path.dirname(dst) or local_dir, exist_ok=True)
        rsize = remote_size(url)
        if rsize > 0 and os.path.exists(dst) and os.path.getsize(dst) == rsize:
            print(f"SKIP {repo}/{f} (already {rsize})", flush=True)
            continue
        print(f"DL {repo}/{f} size={rsize}", flush=True)
        with requests.get(url, timeout=600, stream=True) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length", "0"))
            got = 0
            with open(dst, "wb") as fp:
                for chunk in r.iter_content(1 << 20):
                    if chunk:
                        fp.write(chunk)
                        got += len(chunk)
            print(f"DONE {repo}/{f} {got}/{total}", flush=True)

print("ALL_MODELS_DONE", flush=True)
