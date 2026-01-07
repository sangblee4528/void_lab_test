docker run -it --detach --restart always --gpus all --name vllm_code_server \
-v ~/workspace/LLMS:/workspace/model_repository \
-p 8000:8000 \
--ipc=host \
vllm/vllm-openai:latest \
--model /workspace/model_repository/MODELS/Qwen2.5-Coder-32B-Instruct-AWQ \
--served-model-name keycode-q32b-v2 \
--host 0.0.0.0 --port 8000 \
--rope-scaling '{"factor": 4.0, "original_max_position_embeddings": 32768, "rope_type": "yarn"}' \
--gpu-memory-utilization 0.95 \
--dtype half \
--tensor-parallel-size 2 \
--chat-template /workspace/model_repository/TEMPLATES/template_codeqwen_chat.jinja \
--swap-space 3 \
--seed 42

