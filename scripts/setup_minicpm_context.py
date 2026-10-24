"""Install official MiniCPM5-2B GGUF and a pinned llama.cpp Windows runtime."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile

MODEL_REVISION = "2079a22f3beaa4e306449978533478fe0522f4b3"
MODEL_FILE = "MiniCPM5-2B-Q4_K_M.gguf"
MODEL_SHA256 = "ec2d5801640099e97d8d7e8003ad4d81f336e757811f03a26173dddf386602fd"
RUNTIME_URL = "https://github.com/ggml-org/llama.cpp/releases/download/b11669/llama-b11669-bin-win-cpu-x64.zip"


def download(url, target, expected_hash=""):
    if target.exists():
        if expected_hash:
            with target.open("rb") as source:
                if hashlib.file_digest(source, "sha256").hexdigest() != expected_hash:
                    raise ValueError("Existing model checksum mismatch")
        return
    temporary = target.with_suffix(target.suffix + ".part")
    offset = temporary.stat().st_size if temporary.exists() else 0
    headers = {"User-Agent":"FatFishLife-context-setup"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as response:
        mode = "ab" if offset and response.status == 206 else "wb"
        with temporary.open(mode) as output:
            while block := response.read(1024 * 1024):
                output.write(block)
    if expected_hash:
        with temporary.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != expected_hash:
                raise ValueError("Downloaded model checksum mismatch")
    temporary.replace(target)


def setup(root: Path):
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    report = root / "setup-status.json"
    def stage(name): report.write_text(json.dumps({"stage":name}), encoding="utf-8")
    runtime = root / "llama"
    if not (runtime / "llama-server.exe").is_file():
        stage("download_runtime")
        archive = root / "llama-b11669-win-cpu-x64.zip"
        download(RUNTIME_URL, archive)
        runtime.mkdir(exist_ok=True)
        with zipfile.ZipFile(archive) as package:
            if any(not (runtime / item.filename).resolve().is_relative_to(runtime) for item in package.infolist()):
                raise ValueError("Invalid archive member")
            package.extractall(runtime)
    stage("download_model")
    model = root / MODEL_FILE
    download(f"https://huggingface.co/openbmb/MiniCPM5-2B-GGUF/resolve/{MODEL_REVISION}/{MODEL_FILE}", model, MODEL_SHA256)
    if not (runtime / "llama-server.exe").is_file():
        raise ValueError("Runtime executable missing")
    result = {"stage":"completed", "model":str(model), "runtime":str(runtime / "llama-server.exe"),
              "model_sha256":MODEL_SHA256, "revision":MODEL_REVISION}
    report.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    args = p.parse_args()
    try:
        print(json.dumps(setup(args.root)))
    except Exception as exc:
        args.root.mkdir(parents=True, exist_ok=True)
        (args.root / "setup-status.json").write_text(json.dumps({"stage":"failed", "error_type":type(exc).__name__}), encoding="utf-8")
        raise SystemExit(1)
