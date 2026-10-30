import json
import re


# Use Unicode escapes to avoid any parser conflicts with <think>/</think> markers
THINK_OPEN = "\u003cthink\u003e"
THINK_CLOSE = "\u003c/think\u003e"


def get_text_from_response(response) -> str:
    """
    Extract plain text from LLM response, handling various LangChain message formats.

    Supports:
    - LangChain AIMessage objects (with content, lc_content, text attributes)
    - Dict objects (with content, text, lc_content keys)
    - Plain strings
    """
    # Handle AIMessage / message objects
    if hasattr(response, 'content'):
        content = response.content
        if isinstance(content, str):
            return content
        # content might be a list of content blocks (newer LangChain format)
        if isinstance(content, list):
            # Try to extract text from content blocks
            for block in content:
                if isinstance(block, dict) and block.get('type') == 'text':
                    return block.get('text', '')
                if isinstance(block, str):
                    return block
            # Return first block that has text
            return str(content[0]) if content else ''

    # Handle dict responses with 'messages' key (LangChain agent graph output)
    # raw_output = {'messages': [HumanMessage(...), AIMessage(content='...')]}
    if isinstance(response, dict) and 'messages' in response:
        messages = response['messages']
        if isinstance(messages, list) and len(messages) > 0:
            last_message = messages[-1]
            return get_text_from_response(last_message)

    # Handle dict responses
    if isinstance(response, dict):
        # Direct text field
        if response.get('text'):
            return response['text']
        # Direct content field
        if response.get('content'):
            content = response['content']
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get('text'):
                        return block['text']
        # LangChain lc_content format
        lc_content = response.get('lc_content')
        if isinstance(lc_content, list):
            for item in lc_content:
                if isinstance(item, dict):
                    if item.get('text'):
                        return item['text']
                    if item.get('content'):
                        return item['content']
        # Output as string
        return str(response)

    # Handle plain strings
    if isinstance(response, str):
        return response

    # Fallback
    return str(response)


def extract_think_and_result(text: str):
    """Extract <think>...</think> content and the remaining result from model output."""
    pattern = re.compile(
        rf"{re.escape(THINK_OPEN)}(.*?){re.escape(THINK_CLOSE)}",
        re.DOTALL
    )
    think_match = pattern.search(text)
    think_content = think_match.group(1).strip() if think_match else ""
    result_content = pattern.sub("", text).strip()
    return think_content, result_content


def convert_json_output(text: str) -> dict | list:
    """Parse LLM output as JSON, handling various formats (raw, markdown code blocks, etc.)."""
    text = text.strip()

    # 0. 预处理：去掉可能的 markdown 代码块包裹
    code_block_match = re.match(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if code_block_match:
        text = code_block_match.group(1).strip()

    # 1. 直接解析（已经是干净 JSON）
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. 输出本身以 { / [ 开头：只从开头解析/修复，绝不向内漂移去捡正文碎片。
    #    此前这里直接进滑动窗口：当整段 JSON 被 max_tokens 截断时（外层括号永不闭合），
    #    窗口会一路内移，最终返回正文里恰好合法的 [1,2,3] 之类片段——形状错误却"看起来成功"。
    if text[:1] in ("{", "["):
        # 2a. raw_decode：返回从开头起的第一个完整 JSON，容忍尾部多余内容（JSON 后跟说明文字）
        try:
            obj, _ = json.JSONDecoder().raw_decode(text)
            return obj
        except json.JSONDecodeError:
            pass
        # 2b. 尝试补全被截断的括号
        fixed_text = _fix_truncated_json(text)
        if fixed_text:
            try:
                return json.loads(fixed_text)
            except json.JSONDecodeError:
                pass
        # 2c. 无法修复：明确失败交给上层，而不是返回一个形状错误的碎片
        raise json.JSONDecodeError(
            f"JSON appears truncated and could not be repaired: {text[:200]}", text, 0
        )

    # 3. 前后有散文包裹：滑动窗口提取其中第一个完整 JSON（保持原有行为）
    for start in range(len(text)):
        if text[start] not in ("{", "["):
            continue
        for end in range(start + 1, len(text) + 1):
            candidate = text[start:end]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

    # 4. 找不到有效 JSON，抛出明确错误供上层捕获
    raise json.JSONDecodeError(f"Could not parse as JSON: {text[:200]}", text, 0)


def _fix_truncated_json(text: str) -> str | None:
    """尝试修复被截断的 JSON 字符串。
    
    当 LLM 输出被截断时，JSON 可能缺少结尾的 } 或 ]。
    这里尝试智能补全缺失的括号。
    """
    if not text:
        return None
    
    text = text.strip()
    
    # 检查是否以 { 或 [ 开头
    if text[0] not in ('{', '['):
        return None
    
    # 统计开括号和闭括号的数量
    open_braces = text.count('{')
    close_braces = text.count('}')
    open_brackets = text.count('[')
    close_brackets = text.count(']')
    
    # 计算缺失的括号
    missing_braces = open_braces - close_braces
    missing_brackets = open_brackets - close_brackets
    
    if missing_braces == 0 and missing_brackets == 0:
        return None  # 括号已经匹配，不需要修复
    
    fixed = text
    
    # 添加缺失的闭括号
    # 先补全 } 再补全 ]（因为嵌套顺序）
    for _ in range(missing_braces):
        fixed = fixed.rstrip() + '}'
    for _ in range(missing_brackets):
        fixed = fixed.rstrip() + ']'
    
    # 验证修复后的 JSON 是否有效
    try:
        json.loads(fixed)
        return fixed
    except json.JSONDecodeError:
        return None


def preprocess_response(response, only_text=True, exclude_think=False, json_output=False):
    if only_text or exclude_think or json_output:
        response = get_text_from_response(response)
    if exclude_think:
        think_content, result_content = extract_think_and_result(response)
        response = result_content
    if json_output:
        try:
            response = convert_json_output(response)
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON output: {e}")
            response = {"error": "Invalid JSON output", "raw_content": response}
            raise e
    return response
