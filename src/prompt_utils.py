import json
import os
import re
import sys
from typing import Awaitable, Callable, Optional

import aiofiles

from src.infrastructure.external.ai_client import AIClient

# The meta-prompt to instruct the AI
META_PROMPT_TEMPLATE = """
你是一位世界级的AI提示词工程大师。你的任务是根据用户提供的【购买需求】，模仿一个【参考范例】，为闲鱼监控机器人的AI分析模块（代号 EagleEye）生成一份全新的【分析标准】文本。

你的输出必须严格遵循【参考范例】的结构、语气和核心原则，但内容要完全针对用户的【购买需求】进行定制。最终生成的文本将作为AI分析模块的思考指南。

---
这是【参考范例】（`macbook_criteria.txt`）：
```text
{reference_text}
```
---

这是用户的【购买需求】：
```text
{user_description}
```
---

请现在开始生成。请注意输出格式要求：

【第一部分：分析标准】
只输出新生成的文本内容，不要包含任何额外的解释、标题或代码块标记。
保留范例中的 `[V6.3 核心升级]`、`[V6.4 逻辑修正]` 等版本标记，这有助于保持格式一致性。
将范例中所有与 "MacBook" 相关的内容，替换为与用户需求商品相关的内容。
思考并生成针对新商品类型的“一票否决硬性原则”和“危险信号清单”。

【第二部分：关键词】
在分析标准文本结束后，另起一行输出以下三行标记（标记行本身保留）：
[KEYWORDS_REQUIRED]
必须留空，不要写任何关键词（必含关键词由用户自己填写，AI 不负责生成）
[KEYWORDS_OPTIONAL]
每行一个可选关键词（与目标商品强相关的加分项，如型号变体、关键规格、版本、成色、配件特征），至少生成 5 条，不要凑数写无关词
[END]
"""

ProgressCallback = Callable[[str, str], Awaitable[None]]
# 参考标准大约一千多 token。思考模型还会先输出推理，800 会把正文截掉。
CRITERIA_MAX_OUTPUT_TOKENS = 8192
_THINK_BLOCK_RE = re.compile(
    r"<(?:think|thinking)>.*?</(?:think|thinking)>",
    re.IGNORECASE | re.DOTALL,
)
_UNCLOSED_THINK_RE = re.compile(r"<(?:think|thinking)>", re.IGNORECASE)


async def _report_progress(
    progress_callback: Optional[ProgressCallback],
    step_key: str,
    message: str,
) -> None:
    if progress_callback:
        await progress_callback(step_key, message)


def _read_reference_text(reference_file_path: str) -> str:
    try:
        with open(reference_file_path, "r", encoding="utf-8") as file:
            return file.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"参考文件未找到: {reference_file_path}")
    except IOError as exc:
        raise IOError(f"读取参考文件失败: {exc}")


def _strip_reasoning_blocks(text: str) -> str:
    stripped = _THINK_BLOCK_RE.sub("", text).strip()
    if _UNCLOSED_THINK_RE.search(stripped):
        raise RuntimeError(
            "生成分析标准时，模型的思考过程占满了输出长度，正文被截断。"
            "请换一个不输出长思考过程的模型，或提高模型服务允许的输出长度。"
        )
    if not stripped:
        raise RuntimeError("AI 没有生成分析标准正文。")
    return stripped


async def _request_generated_text(ai_client: AIClient, prompt: str) -> str:
    print("正在调用AI生成新的分析标准，请稍候...")
    try:
        generated_text = await ai_client._call_ai(
            [{"role": "user", "content": prompt}],
            temperature=0.5,
            max_output_tokens=CRITERIA_MAX_OUTPUT_TOKENS,
            enable_json_output=False,
        )
    except Exception as exc:
        print(f"调用 OpenAI API 时出错: {exc}")
        raise

    generated_text = _strip_reasoning_blocks(generated_text)
    print("AI已成功生成内容。")
    return generated_text


async def _close_ai_client(
    ai_client: AIClient,
    active_error: BaseException | None,
) -> None:
    try:
        await ai_client.close()
    except Exception as close_error:
        print(f"关闭 AI 客户端时出错: {close_error}")
        if active_error is None:
            raise


def _resolve_criteria_failover_chain():
    """解析"重新生成 AI 标准"用的模型链：[(显示名, 客户端, 模型名), ...]。

    与商品分析共用同一套档案链（启用的档案按 priority 排序），因此设置页的
    排序/切换对重新生成同样生效；任一环节失败或链为空时返回 []，
    调用方回退到旧的 .env 默认配置路径。
    """
    try:
        from src.services.ai_failover import clients_for_chain, resolve_failover_chain
    except Exception as exc:
        print(f"[标准生成] 故障转移模块不可用，回退默认 AI 配置: {exc}")
        return []
    try:
        items = resolve_failover_chain(
            env_base_url=os.getenv("OPENAI_BASE_URL") or "",
            env_model_name=os.getenv("OPENAI_MODEL_NAME") or "",
            env_api_key=os.getenv("OPENAI_API_KEY") or "",
            env_proxy=os.getenv("PROXY_URL") or "",
        )
    except Exception as exc:
        print(f"[标准生成] 读取模型档案失败，回退默认 AI 配置: {exc}")
        return []
    if os.getenv("AI_FAILOVER_ENABLED", "true").strip().lower() != "true":
        items = items[:1]
    if not items:
        return []
    try:
        return clients_for_chain(items)
    except Exception as exc:
        print(f"[标准生成] 构建档案客户端失败，回退默认 AI 配置: {exc}")
        return []


async def _request_text_via_profile(client, model_name: str, prompt: str) -> str:
    """用单个档案客户端做一次纯文本生成，参数口径与 AIClient._call_ai 一致。"""
    from src.services.ai_request_compat import (
        CHAT_COMPLETIONS_API_MODE,
        build_ai_request_params,
        create_ai_response_async,
    )
    from src.services.ai_response_parser import extract_ai_response_content

    request_params = build_ai_request_params(
        CHAT_COMPLETIONS_API_MODE,
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
        max_output_tokens=CRITERIA_MAX_OUTPUT_TOKENS,
        enable_json_output=False,
    )
    response = await create_ai_response_async(
        client, CHAT_COMPLETIONS_API_MODE, request_params
    )
    return extract_ai_response_content(response)


async def _generate_text_via_chain(chain, prompt: str) -> str:
    """按档案链顺序逐个尝试生成分析标准，首个成功即返回。

    超时/报错直接故障转移到下一个档案；空响应则对同一档案重试一次。
    全部失败时抛出最后一个异常。
    """
    from src.services.ai_response_parser import EmptyAIResponseError

    last_error: BaseException | None = None
    for label, client, model_name in chain:
        for attempt in range(2):
            try:
                print(f"[标准生成] 使用模型档案 {label}（第 {attempt + 1} 次）")
                generated_text = await _request_text_via_profile(
                    client, model_name, prompt
                )
                result = _strip_reasoning_blocks(generated_text)
            except EmptyAIResponseError as exc:
                print(f"[标准生成] {label} 返回空响应，重试: {exc}")
                last_error = exc
                continue
            except Exception as exc:
                print(f"[标准生成] {label} 调用失败，故障转移到下一个档案: {exc}")
                last_error = exc
                break
            print("[标准生成] AI已成功生成内容。")
            return result
    assert last_error is not None  # 链非空时至少有一次尝试
    raise last_error


def split_criteria_and_keywords(generated_text: str):
    """从 AI 生成文本中分离分析标准与关键词。

    返回 (criteria_text, required_keywords, optional_keywords)。
    关键词段格式：
        [KEYWORDS_REQUIRED]
        （留空）
        [KEYWORDS_OPTIONAL]
        每行一个
        [END]

    约定（用户 2026-10-21 定）：必含关键词不由 AI 生成，留给用户自己填，
    因此 REQUIRED 段即使被模型写了内容也一律丢弃，必含恒返回 []；
    可选关键词至少 5 条由元提示词约束，这里只做清洗与去重。
    """
    text = generated_text or ""
    optional: list[str] = []
    criteria = text
    req_marker = "[KEYWORDS_REQUIRED]"
    opt_marker = "[KEYWORDS_OPTIONAL]"
    end_marker = "[END]"
    # 分析标准正文在第一个关键词标记处结束
    cut = len(text)
    for marker in (req_marker, opt_marker):
        idx = text.find(marker)
        if idx != -1:
            cut = min(cut, idx)
    if cut < len(text):
        criteria = text[:cut].strip()
        rest = text[cut:]
        if opt_marker in rest:
            opt_part = rest.split(opt_marker, 1)[1]
            if end_marker in opt_part:
                opt_part = opt_part.split(end_marker, 1)[0]
            seen: set[str] = set()
            for ln in opt_part.strip().splitlines():
                kw = ln.strip()
                if kw and kw not in seen:
                    seen.add(kw)
                    optional.append(kw)
    return criteria, [], optional


async def generate_criteria(
    user_description: str,
    reference_file_path: str,
    progress_callback: Optional[ProgressCallback] = None,
) -> str:
    """
    Generates a new criteria file content using AI.
    """
    await _report_progress(progress_callback, "reference", "正在读取参考文件。")
    print(f"正在读取参考文件: {reference_file_path}")
    reference_text = _read_reference_text(reference_file_path)

    await _report_progress(progress_callback, "prompt", "正在构建发送给 AI 的指令。")
    print("正在构建发送给AI的指令...")
    prompt = META_PROMPT_TEMPLATE.format(
        reference_text=reference_text,
        user_description=user_description,
    )

    await _report_progress(progress_callback, "llm", "正在调用 AI 生成分析标准。")
    chain = _resolve_criteria_failover_chain()
    if chain:
        # 与商品分析走同一套档案链：设置页的排序/切换对"重新生成"同样生效，
        # 首个档案失败时自动故障转移到下一个，不再固定走 .env 默认配置。
        return await _generate_text_via_chain(chain, prompt)

    # 回退：无档案或故障转移不可用时，沿用旧的 .env 默认配置路径。
    ai_client = AIClient()
    active_error: BaseException | None = None
    try:
        if not ai_client.is_available():
            ai_client.refresh()
        if not ai_client.is_available():
            raise RuntimeError("AI客户端未初始化，无法生成分析标准。请检查.env配置。")

        return await _request_generated_text(ai_client, prompt)
    except Exception as exc:
        active_error = exc
        raise
    finally:
        await _close_ai_client(ai_client, active_error)


async def update_config_with_new_task(new_task: dict, config_file: str = "config.json"):
    """
    将一个新任务添加到指定的JSON配置文件中。
    """
    print(f"正在更新配置文件: {config_file}")
    try:
        # 读取现有配置
        config_data = []
        if os.path.exists(config_file):
            async with aiofiles.open(config_file, 'r', encoding='utf-8') as f:
                content = await f.read()
                # 处理空文件的情况
                if content.strip():
                    try:
                        config_data = json.loads(content)
                        print(f"成功读取现有配置，当前任务数量: {len(config_data)}")
                    except json.JSONDecodeError as e:
                        print(f"解析配置文件失败，将创建新配置: {e}")
                        config_data = []
        else:
            print(f"配置文件不存在，将创建新文件: {config_file}")

        # 追加新任务
        config_data.append(new_task)

        # 写回配置文件
        async with aiofiles.open(config_file, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(config_data, ensure_ascii=False, indent=2))
            print(f"配置文件写入完成")

        print(f"成功！新任务 '{new_task.get('task_name')}' 已添加到 {config_file} 并已启用。")
        return True
    except json.JSONDecodeError as e:
        error_msg = f"错误: 配置文件 {config_file} 格式错误，无法解析: {e}"
        sys.stderr.write(error_msg + "\n")
        print(error_msg)
        return False
    except IOError as e:
        error_msg = f"错误: 读写配置文件失败: {e}"
        sys.stderr.write(error_msg + "\n")
        print(error_msg)
        return False
    except Exception as e:
        error_msg = f"错误: 更新配置文件时发生未知错误: {e}"
        sys.stderr.write(error_msg + "\n")
        print(error_msg)
        import traceback
        print(traceback.format_exc())
        return False
