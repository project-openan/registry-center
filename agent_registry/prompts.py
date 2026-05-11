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
    prompt = f"""You are an expert agent selection assistant. From the list of agents below, select the most suitable agents for the user's task.

User Task: "{task}"

Available Agents:
{agents_text}

Analyze the user's task and select the best agents to fulfill it. Consider:
1. Whether the agent's description matches the task domain
2. Whether the agent's capabilities and skills meet the task requirements
3. If multiple agents can collaborate, select up to {top_n} agents
4. If no suitable agent exists, return an empty list

Return the agent names as a JSON array only. Example:
["agent1","agent2"] or [] (if no suitable agent)

Selected agents:"""

    return prompt