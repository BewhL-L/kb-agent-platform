"""
vLLM 高吞吐推理服务启动器
================================================
vLLM 用 PagedAttention 等技术大幅提升推理吞吐、降低单请求成本，
是生产环境部署开源大模型的主流选择，并提供 OpenAI 兼容接口。

【环境准备】（独立环境，建议 Linux + GPU）
  pip install vllm

【方式一：直接命令行启动】（最简单）
  vllm serve Qwen/Qwen2.5-1.5B-Instruct \
      --host 0.0.0.0 --port 8001 \
      --max-model-len 4096 --gpu-memory-utilization 0.9

  启动后即得到 OpenAI 兼容服务：
    http://localhost:8001/v1/chat/completions
  把本项目 .env 的 LLM_BASE_URL 指向 http://localhost:8001/v1 即可接入。

【方式二：运行本脚本】
  python scripts/inference/serve_vllm.py \
      --model Qwen/Qwen2.5-1.5B-Instruct --port 8001
"""
import argparse
import subprocess
import sys


def main():
    p = argparse.ArgumentParser(description="启动 vLLM 服务")
    p.add_argument("--model", required=True, help="模型名或本地合并后的路径")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8001)
    p.add_argument("--max-model-len", type=int, default=4096)
    p.add_argument("--gpu-mem", type=float, default=0.9)
    p.add_argument("--tensor-parallel", type=int, default=1, help="多卡张量并行")
    p.add_argument("--quantization", default=None,
                   help="可选 awq / gptq，加载量化模型")
    p.add_argument("--draft-model", default=None,
                   help="投机解码：小草稿模型名，可进一步降低延迟")
    args = p.parse_args()

    cmd = [
        sys.executable, "-m", "vllm.entrypoints.openai.api_server",
        "--model", args.model,
        "--host", args.host,
        "--port", str(args.port),
        "--max-model-len", str(args.max_model_len),
        "--gpu-memory-utilization", str(args.gpu_mem),
        "--tensor-parallel-size", str(args.tensor_parallel),
        "--trust-remote-code",
    ]
    if args.quantization:
        cmd += ["--quantization", args.quantization]
    if args.draft_model:
        # 投机解码：草稿模型快速猜多个 token，主模型一次验证
        cmd += ["--speculative-model", args.draft_model,
                "--num-speculative-tokens", "5"]

    print("启动命令：", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        raise SystemExit("未找到 vLLM，请先安装：pip install vllm")


if __name__ == "__main__":
    main()
