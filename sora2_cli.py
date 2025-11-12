import argparse, os, time, sys, json, mimetypes, pathlib
import requests
from dotenv import load_dotenv
from tqdm import tqdm

API_BASE = "https://api.openai.com/v1"

def download_video_by_job_id(api_key: str, job_id: str, out_path: str):
    """
    某些响应不会返回 assets/url，需要直接 GET /videos/{id}/content 拉取二进制 MP4。
    """
    headers = {"Authorization": f"Bearer {api_key}"}
    with requests.get(f"{API_BASE}/videos/{job_id}/content", headers=headers, stream=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        with open(out_path, "wb") as f, tqdm(total=total, unit="B", unit_scale=True, desc="downloading") as pbar:
            for chunk in r.iter_content(chunk_size=1 << 20):
                if chunk:
                    f.write(chunk)
                    pbar.update(len(chunk))

def create_video_job(api_key: str, prompt: str, seconds: int, size: str, image_path: str | None):
    headers = {"Authorization": f"Bearer {api_key}"}

    if image_path:
        mime = mimetypes.guess_type(image_path)[0] or "application/octet-stream"
        files = {
            "input_reference": (os.path.basename(image_path), open(image_path, "rb"), mime)
        }
        data = {
            "model": "sora-2",
            "prompt": prompt,
            "seconds": str(seconds),
            "size": size,
        }
        resp = requests.post(f"{API_BASE}/videos", headers=headers, files=files, data=data, timeout=300)
    else:
        payload = {
            "model": "sora-2",
            "prompt": prompt,
            "seconds": str(seconds),   # ← 注意这里加了 str()
            "size": size,
        }
        resp = requests.post(f"{API_BASE}/videos", headers=headers, json=payload, timeout=120)

    if resp.status_code >= 400:
        raise RuntimeError(f"Create failed: {resp.status_code} {resp.text}")
    return resp.json()

def get_video_job(api_key: str, job_id: str):
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = requests.get(f"{API_BASE}/videos/{job_id}", headers=headers, timeout=60)
    if resp.status_code >= 400:
        raise RuntimeError(f"Fetch failed: {resp.status_code} {resp.text}")
    return resp.json()

def pick_mp4_asset(details: dict):
    assets = details.get("assets") or []
    for a in assets:
        u = a.get("url") or ""
        t = (a.get("type") or "").lower()
        if u.endswith(".mp4") or t in ("video/mp4", "mp4", "video"):
            return u
    return None

def download_file(url: str, out_path: str):
    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        with open(out_path, "wb") as f, tqdm(total=total, unit="B", unit_scale=True, desc="downloading") as pbar:
            for chunk in r.iter_content(chunk_size=1 << 20):
                if chunk:
                    f.write(chunk)
                    pbar.update(len(chunk))

def main():
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("OPENAI_API_KEY 未设置（.env）", file=sys.stderr)
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Sora 2 video generation (local CLI)")
    parser.add_argument("--prompt", required=True, help="文案/镜头描述")
    parser.add_argument("--seconds", type=int, default=4, help="时长（常用 4/8/12）")
    parser.add_argument("--size", default="1280x720", help="分辨率，如 1280x720 或 720x1280")
    parser.add_argument("--image", help="可选参考图路径（分辨率需与 size 一致，jpeg/png/webp）")
    parser.add_argument("--out", default="output.mp4", help="输出 MP4 文件名")
    parser.add_argument("--timeout", type=int, default=600, help="最大等待秒数（轮询）")
    parser.add_argument("--interval", type=float, default=2.0, help="轮询间隔秒")
    args = parser.parse_args()

    print("creating job...")
    job = create_video_job(api_key, args.prompt, args.seconds, args.size, args.image)
    job_id = job.get("id")
    if not job_id:
        print("未返回 job id:\n", json.dumps(job, ensure_ascii=False, indent=2))
        sys.exit(2)

    print(f"job id: {job_id}\npolling...")
    start = time.time()
    status = job.get("status", "queued")
    details = job

    while time.time() - start < args.timeout:
        details = get_video_job(api_key, job_id)
        status = details.get("status")
        print(f"status: {status}")
        if status in ("completed", "failed", "canceled"):
            break
        time.sleep(args.interval)

    if status != "completed":
        print("未在超时时间内完成，返回最后状态：")
        print(json.dumps(details, ensure_ascii=False, indent=2))
        sys.exit(3)

    out_path = pathlib.Path(args.out).resolve()
    url = pick_mp4_asset(details)

    if url:
        print(f"downloading mp4 to {out_path} ...")
        download_file(url, str(out_path))
        print("done:", out_path)
    else:
        # 没有 assets/url，直接用 /videos/{id}/content 获取二进制
        job_id = details.get("id")
        if not job_id:
            print("完成但没有 job_id，详情：\n", json.dumps(details, ensure_ascii=False, indent=2))
            sys.exit(4)
        print(f"no URL in response; fetching binary from /videos/{job_id}/content ...")
        download_video_by_job_id(os.getenv("OPENAI_API_KEY"), job_id, str(out_path))
        print("done:", out_path)

if __name__ == "__main__":
    main()
