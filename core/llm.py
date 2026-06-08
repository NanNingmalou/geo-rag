"""LLM 推理封装 - llama-cpp-python 本地推理 + DeepSeek API 云端推理"""
from llama_cpp import Llama
from openai import OpenAI

LLM_MODEL_PATH = "models/qwen2.5-7b-instruct-q4_k_m.gguf"

SYSTEM_PROMPT = """你是一个地理知识问答助手。你的知识来源于用户提供的文档。
请严格遵守以下规则：
1. 只根据提供的参考文档内容回答问题
2. 如果文档中没有相关信息，明确告知用户"根据已有文档，我无法回答这个问题"
3. 用自己的话总结、归纳文档内容，严禁直接照搬原文。要综合多个片段的信息，形成连贯、有条理的回答
4. 涉及地名时，尽量说明其位置（所在省份/国家）和相关地理特征
5. 回答使用中文
6. 回答要有层次感：先给结论，再展开细节"""

DEEPSEEK_BASE_URL = "https://api.deepseek.com"


class LLM:
    """本地 Qwen 模型推理"""
    def __init__(self, model_path: str = LLM_MODEL_PATH, n_ctx: int = 4096, n_gpu_layers: int = -1):
        self.model = Llama(
            model_path=model_path,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,  # -1 = 全部层放 GPU
            verbose=False,
        )

    def generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.5):
        """非流式生成"""
        response = self.model.create_chat_completion(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response["choices"][0]["message"]["content"]

    def stream_generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.5):
        """流式生成，逐词 yield"""
        stream = self.model.create_chat_completion(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )
        for chunk in stream:
            choices = chunk.get("choices", [])
            if choices and choices[0].get("delta", {}).get("content"):
                yield choices[0]["delta"]["content"]

    def rag_query(self, question: str, context: str, stream: bool = True, max_tokens: int = 512):
        """RAG 问答：问题 + 上下文 → 回答"""
        prompt = f"""请根据以下参考文档回答问题。请用自己的话总结和归纳，不要直接复制原文。

参考文档：
{context}

问题：{question}

回答："""

        if stream:
            return self.stream_generate(prompt, max_tokens=max_tokens)
        else:
            return self.generate(prompt, max_tokens=max_tokens)


class DeepSeekLLM:
    """DeepSeek API 云端推理（OpenAI 兼容协议）"""
    def __init__(self, api_key: str, model: str = "deepseek-chat", base_url: str = DEEPSEEK_BASE_URL):
        self.client = OpenAI(api_key=api_key, base_url=base_url)
        self.model = model

    def generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.5):
        """非流式生成"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
            stream=False,
        )
        return response.choices[0].message.content

    def stream_generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.5):
        """流式生成，逐词 yield"""
        stream = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    def rag_query(self, question: str, context: str, stream: bool = True, max_tokens: int = 512):
        """RAG 问答：问题 + 上下文 → 回答"""
        prompt = f"""请根据以下参考文档回答问题。请用自己的话总结和归纳，不要直接复制原文。

参考文档：
{context}

问题：{question}

回答："""

        if stream:
            return self.stream_generate(prompt, max_tokens=max_tokens)
        else:
            return self.generate(prompt, max_tokens=max_tokens)
