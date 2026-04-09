def build_agent_selection_prompt(task:str,agents_text:str)->str:
    """
    Build a prompt for the LLM to select the most suitable agents.

    :param task: The user's task description.
    :param agents_text: List of agent information dictionaries.
    :return: Formatted prompt string.
    """
    # Format agent information
    prompt = f"""你是一个专业的智能体选择专家。请从以下智能体列表中，选择最适合完成用户任务的智能体。
    
用户任务：“{task}”
    
可用的智能体列表：
{agents_text}
    
请分析用户任务，选择最能胜任此任务的智能体。考虑因素：
1. 智能体的描述是否匹配任务领域
2. 智能体的能力和技能是否满足任务需求
3. 如果多个智能体可以协同工作，最多可以选择3个智能体
4. 如果没有合适的智能体，返回空列表
    
请仅以JSON数组格式返回智能体名称。例如：
["智能体1","智能体2"] 或 []（如果没有合适的智能体）

选中的智能体："""

    return prompt