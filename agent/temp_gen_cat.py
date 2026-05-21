"""提交 txt2img 工作流到 ComfyUI，生成卡通猫，保存到 H:/pics"""
import json, time, shutil, os, uuid, urllib.request, urllib.error

SERVER = "http://localhost:8188"
OUTPUT_DIR = "H:/pics"
CHECKPOINT = "SD1.5\\AOM3A3_orangemixs.safetensors"

# 提示词
positive = "masterpiece, best quality, high resolution, 1girl, school uniform, japanese school girl, jk, pleated skirt, sailor collar, cute, beautiful face, detailed eyes, cherry blossom petals, soft lighting, anime illustration, vibrant colors, solo, upper body, looking at viewer, smile"
negative = "low quality, worst quality, bad anatomy, extra fingers, mutated hands, poorly drawn face, disfigured, ugly, deformed, text, watermark, realistic, photo, 3D, monochrome"

# 构建工作流
workflow = {
    "1": {"inputs": {"ckpt_name": CHECKPOINT}, "class_type": "CheckpointLoaderSimple", "_meta": {"title": "加载模型"}},
    "2": {"inputs": {"text": positive, "clip": ["1", 1]}, "class_type": "CLIPTextEncode", "_meta": {"title": "正向提示词"}},
    "3": {"inputs": {"text": negative, "clip": ["1", 1]}, "class_type": "CLIPTextEncode", "_meta": {"title": "负向提示词"}},
    "4": {"inputs": {"width": 512, "height": 768, "batch_size": 1}, "class_type": "EmptyLatentImage", "_meta": {"title": "空潜空间"}},
    "5": {"inputs": {"seed": 88, "steps": 24, "cfg": 7.5, "sampler_name": "euler_ancestral", "scheduler": "normal", "denoise": 1.0, "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0]}, "class_type": "KSampler", "_meta": {"title": "KSampler"}},
    "6": {"inputs": {"samples": ["5", 0], "vae": ["1", 2]}, "class_type": "VAEDecode", "_meta": {"title": "VAE解码"}},
    "7": {"inputs": {"images": ["6", 0], "filename_prefix": "jk_portrait"}, "class_type": "SaveImage", "_meta": {"title": "保存图片"}}
}

payload = {"prompt": workflow, "client_id": str(uuid.uuid4())}

def api_req(method, endpoint, data=None):
    url = f"{SERVER}{endpoint}"
    req = urllib.request.Request(url, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(data).encode()
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"HTTP Error {e.code}: {e.reason}")
        return None
    except Exception as e:
        print(f"Error: {e}")
        return None

print("提交工作流...")
result = api_req("POST", "/api/prompt", payload)
if not result:
    print("提交失败！")
    exit(1)

prompt_id = result.get("prompt_id")
print(f"Prompt ID: {prompt_id}")

# 轮询等待完成
print("等待生成...")
max_wait = 120
for i in range(max_wait):
    time.sleep(1)
    history = api_req("GET", f"/history/{prompt_id}")
    if history and prompt_id in history:
        entry = history[prompt_id]
        if "outputs" in entry:
            outputs = entry["outputs"]
            # 找到 SaveImage 节点的输出
            for node_id, node_output in outputs.items():
                if "images" in node_output:
                    for img in node_output["images"]:
                        filename = img["filename"]
                        subfolder = img.get("subfolder", "")
                        src_dir = os.path.join("H:/comfyui/ComfyUI-aki-v3/ComfyUI/output", subfolder)
                        src_path = os.path.join(src_dir, filename)
                        print(f"生成完成: {filename}")
                        
                        # 复制到目标目录
                        os.makedirs(OUTPUT_DIR, exist_ok=True)
                        dst_path = os.path.join(OUTPUT_DIR, filename)
                        shutil.copy2(src_path, dst_path)
                        print(f"已保存到: {dst_path}")
                        exit(0)
            print("未找到图像输出")
            exit(1)
    print(f"  等待中... ({i+1}s)")

print("超时：生成未在 120 秒内完成")
exit(1)
