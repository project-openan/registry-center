# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

def build_agent_selection_prompt(task:str,agents_text:str,top_n:int)->str:
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
3. 如果多个智能体可以协同工作，最多可以选择{top_n}个智能体
4. 如果没有合适的智能体，返回空列表
    
请仅以JSON数组格式返回智能体名称。例如：
["智能体1","智能体2"] 或 []（如果没有合适的智能体）

选中的智能体："""

    return prompt