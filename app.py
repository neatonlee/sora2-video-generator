import time, mimetypes, requests, io, streamlit as st

API_BASE = "https://api.openai.com/v1"

def create_video_job(api_key: str, model: str, prompt: str, seconds: str, size: str, image_file):
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
    for a in (details.get("assets") or []):
        url = a.get("url", "")
        typ = (a.get("type") or "").lower()
        if url.endswith(".mp4") or typ in ("video", "mp4", "video/mp4"):
            return url
    return None

def normalize_api_key(raw: str) -> str:
    raw = (raw or "").strip()
    for marker in ("sk-proj-", "sk-"):
        if marker in raw:
            return raw[raw.index(marker):].strip()
    return raw

# ===================== UI =====================
st.set_page_config(page_title="🎬 Sora 2 视频生成器（云端版）", layout="centered")
st.title("🎬 Sora 2 视频生成器（云端版）")
st.caption("在页面中输入你的 OpenAI API Key 使用（不会存储）")

api_key = st.text_input("请输入你的 OpenAI API Key", type="password")
api_key = normalize_api_key(api_key)
if not api_key or not (api_key.startswith("sk-") or "sk-" in api_key):
    st.stop()

model = st.selectbox("选择模型", ["sora-2", "sora-2-pro"])
# 动态分辨率
size_options = ["1280x720", "720x1280"] if model == "sora-2" else ["1280x720", "720x1280", "1024x1792", "1792x1024"]

prompt = st.text_area("Prompt（视频描述）", "一只小海獭坐在礁石上，镜头慢推近，它回头向镜头眨眼。", height=100)
seconds = st.selectbox("时长（seconds）", ["4", "8", "12"], index=0)
size = st.selectbox("分辨率（size）", size_options, index=0)
image_file = st.file_uploader("可选参考图（JPEG/PNG/WebP，分辨率需与 size 一致）", type=["jpg","jpeg","png","webp"])
out_name = st.text_input("下载文件名", value="sora_output.mp4")

if st.button("🚀 生成视频"):
    try:
        st.info("正在创建任务，请稍候……")
        job = create_video_job(api_key, model, prompt, seconds, size, image_file)
        job_id = job.get("id")
        if not job_id:
            st.error("未返回 job_id："); st.json(job); st.stop()

        progress = st.empty()
        status = job.get("status", "queued")
        start = time.time()
        details = job
        while status not in ("completed", "failed", "canceled"):
            details = get_video_job(api_key, job_id)
            status = details.get("status", "unknown")
            progress.info(f"状态：{status}")
            if time.time() - start > 600:
                st.warning("超时未完成，请稍后重试。")
                break
            time.sleep(2)

        if status != "completed":
            st.error(f"任务失败：{details.get('error')}")
            st.json(details)
            st.stop()

        # 完成：优先用 URL；否则拉取二进制并提供下载按钮
        url = pick_mp4_asset(details)
        if url:
            st.success("任务完成！下方可直接播放，也可下载到本地👇")
            st.video(url)
            data = requests.get(url, timeout=300).content
            st.download_button("⬇️ 下载 MP4", data=data, file_name=out_name, mime="video/mp4")
        else:
            st.info("未返回 URL，尝试直接下载内容……")
            resp = requests.get(f"{API_BASE}/videos/{job_id}/content",
                                headers={"Authorization": f"Bearer {api_key}"}, timeout=300)
            resp.raise_for_status()
            st.video(resp.content)
            st.download_button("⬇️ 下载 MP4", data=resp.content, file_name=out_name, mime="video/mp4")

    except Exception as e:
        st.error(f"出错：{e}")
