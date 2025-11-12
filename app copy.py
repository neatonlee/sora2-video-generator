import os, time, mimetypes, requests, pathlib
import streamlit as st
from tqdm import tqdm

# ===================== 基础设置 =====================
API_BASE = "https://api.openai.com/v1"

# ===================== 工具函数 =====================
def create_video_job(api_key: str, model: str, prompt: str, seconds: str, size: str, image_file):
    """向 OpenAI /videos 提交任务"""
    headers = {"Authorization": f"Bearer {api_key}"}
    if image_file:
        mime = mimetypes.guess_type(image_file.name)[0] or "application/octet-stream"
        files = {"input_reference": (image_file.name, image_file.read(), mime)}
        data = {"model": model, "prompt": prompt, "seconds": seconds, "size": size}
        resp = requests.post(f"{API_BASE}/videos", headers=headers, files=files, data=data, timeout=300)
    else:
        payload = {"model": model, "prompt": prompt, "seconds": seconds, "size": size}
        resp = requests.post(f"{API_BASE}/videos", headers=headers, json=payload, timeout=120)

    if resp.status_code >= 400:
        raise RuntimeError(f"创建任务失败: {resp.status_code} {resp.text}")
    return resp.json()

def get_video_job(api_key: str, job_id: str):
    headers = {"Authorization": f"Bearer {api_key}"}
    r = requests.get(f"{API_BASE}/videos/{job_id}", headers=headers, timeout=60)
    r.raise_for_status()
    return r.json()

def pick_mp4_asset(details: dict):
    assets = details.get("assets") or []
    for a in assets:
        url = a.get("url", "")
        typ = (a.get("type") or "").lower()
        if url.endswith(".mp4") or typ in ("video", "mp4", "video/mp4"):
            return url
    return None

def download_file(url: str, out_path: str):
    with requests.get(url, stream=True, timeout=300) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        with open(out_path, "wb") as f, tqdm(total=total, unit="B", unit_scale=True, desc="downloading") as pbar:
            for chunk in r.iter_content(chunk_size=1 << 20):
                if chunk:
                    f.write(chunk)
                    pbar.update(len(chunk))

def download_video_by_job_id(api_key: str, job_id: str, out_path: str):
    headers = {"Authorization": f"Bearer {api_key}"}
    with requests.get(f"{API_BASE}/videos/{job_id}/content", headers=headers, stream=True, timeout=300) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        with open(out_path, "wb") as f, tqdm(total=total, unit="B", unit_scale=True, desc="downloading") as pbar:
            for chunk in r.iter_content(chunk_size=1 << 20):
                if chunk:
                    f.write(chunk)
                    pbar.update(len(chunk))

# ===================== Streamlit 页面 =====================
st.set_page_config(page_title="🎬 Sora 2 视频生成器", layout="centered")
st.title("🎬 Sora 2 视频生成器")
st.caption("安全版：在页面中输入 OpenAI API Key 使用（不会泄露）")

# 输入 API Key（存储在 session，不写入磁盘）
api_key = st.text_input("请输入你的 OpenAI API Key", type="password")
if not api_key:
    st.warning("请先输入有效的 API Key。")
    st.stop()

model = st.selectbox("选择模型", ["sora-2", "sora-2-pro"])
if model == "sora-2":
    size_options = ["1280x720", "720x1280"]
else:  # sora-2-pro
    size_options = ["1280x720", "720x1280", "1024x1792", "1792x1024"]
prompt = st.text_area("Prompt（视频描述）", "一只小海獭坐在礁石上，镜头慢推近，它回头向镜头眨眼。", height=100)
seconds = st.selectbox("时长（seconds）", ["4", "8", "12"], index=0)
prev = st.session_state.get("size_value")
default_index = size_options.index(prev) if prev in size_options else 0
size = st.selectbox("分辨率（size）", size_options, index=default_index, key="size_value")
image_file = st.file_uploader("可选参考图（JPEG/PNG/WebP，分辨率需与 size 一致）", type=["jpg", "jpeg", "png", "webp"])

default_desktop = str(pathlib.Path.home() / "Desktop")
save_dir = st.text_input("保存目录", value=default_desktop)
out_name = st.text_input("输出文件名", value="sora_output.mp4")

if st.button("🚀 生成视频"):
    try:
        st.info("正在创建任务，请稍候……")
        job = create_video_job(api_key, model, prompt, seconds, size, image_file)
        job_id = job.get("id")
        if not job_id:
            st.error("未返回 job_id，请检查响应。")
            st.json(job)
            st.stop()

        # 轮询状态
        progress = st.empty()
        status = job.get("status", "queued")
        start = time.time()
        details = job
        while status not in ("completed", "failed", "canceled"):
            details = get_video_job(api_key, job_id)
            status = details.get("status", "unknown")
            progress.info(f"状态：{status}")
            if time.time() - start > 600:  # 最多等 10 分钟
                st.warning("超时未完成，请稍后再试。")
                break
            time.sleep(2)

        out_path = pathlib.Path(save_dir) / out_name

        if status == "completed":
            url = pick_mp4_asset(details)
            if url:
                st.success("任务完成！点击下方播放视频👇")
                st.video(url)
                # 云端：提供下载按钮
                import requests
                try:
                    data = requests.get(url, timeout=300).content
                    st.download_button("⬇️ 下载 MP4", data=data, file_name=out_name, mime="video/mp4")
                    st.info("云端环境不会写入本地桌面，请点击下载按钮保存到你的电脑。")
                except Exception as e:
                    st.warning(f"无法生成下载按钮：{e}")

            else:
                st.info("未返回 URL，尝试直接下载内容……")
                import io, requests
                try:
                    resp = requests.get(f"{API_BASE}/videos/{job_id}/content",
                                        headers={"Authorization": f"Bearer {api_key}"},
                                        timeout=300)
                    resp.raise_for_status()
                    buf = io.BytesIO(resp.content)
                    st.download_button("⬇️ 下载 MP4", data=buf.getvalue(), file_name=out_name, mime="video/mp4")
                    st.info("云端环境无法保存到桌面，请使用下载按钮保存到你的电脑。")
                except Exception as e:
                    st.error(f"下载失败：{e}")
        else:
            st.error(f"任务失败：{details.get('error')}")
            st.json(details)

    except Exception as e:
        st.error(f"出错：{e}")
