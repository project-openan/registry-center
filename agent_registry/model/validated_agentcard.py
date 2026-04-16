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

import re

from a2a.types import AgentCard, AgentProvider, AgentSkill, AgentCapabilities
from pydantic import field_validator, model_validator, HttpUrl

_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_]+(?:\s+[a-zA-Z0-9_]+)*$')

NAME_MAX_LENGTH = 100
ORGNIZATION_MAX_LENGTH = 100
DESCRIPTION_MAX_LENGTH = 1000
URL_MAX_LENGTH = 1024
VERSION_MAX_LENGTH = 50
INPUT_OUTPUT_MAX_LENGTH = 100
MAX_NUMBER_OF_SKILLS = 100
SKILL_MAX_LENGTH = 4096
MAX_NUMBER_OF_AGENT_EXTENSION = 10
AGENT_EXTENSION_MAX_LENGTH = 512

_DANGEROUS_CHARS = re.compile(r'[\x00-\x1F\x7F\x80-\x9F\u2028\u2029\u202D\u202E\u200B\u200C\u200D\uFEFF\u2066-\u2069]')


class ValidatedAgentCard(AgentCard):
    """
    A2A-T requires information about the agent's service provider.
    """
    provider: AgentProvider

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        if len(v) > NAME_MAX_LENGTH:
            raise ValueError(f'The agent name can contain a maximum of {NAME_MAX_LENGTH} characters.')
        """验证名称仅包含字母、数字、下划线和空格"""
        if not _NAME_PATTERN.fullmatch(v):
            raise ValueError('The name can contain only letters, digits, underscores (_), spaces.')
        return v

    @field_validator('description')
    @classmethod
    def validate_description(cls, description: str) -> str:
        if len(description) > DESCRIPTION_MAX_LENGTH:
            raise ValueError(f'The agent description can contain a maximum of {DESCRIPTION_MAX_LENGTH} characters.')
        return description

    @field_validator('url')
    @classmethod
    def validate_url(cls, url: str) -> str:
        if len(url) > URL_MAX_LENGTH:
            raise ValueError(f'The agent url can contain a maximum of {URL_MAX_LENGTH} characters.')
        try:
            HttpUrl(url)
        except Exception as e:
            raise ValueError('Provider URL must be a valid web URL.') from e
        return url

    @field_validator('version')
    @classmethod
    def validate_version(cls, version: str) -> str:
        if len(version) > VERSION_MAX_LENGTH:
            raise ValueError(f'The agent version can contain a maximum of {VERSION_MAX_LENGTH} characters.')
        return version

    @field_validator('default_input_modes')
    @classmethod
    def validate_default_input_modes(cls, default_input_modes: list[str]) -> list[str]:
        if len(default_input_modes) > INPUT_OUTPUT_MAX_LENGTH:
            raise ValueError(
                f'The agent default_input_modes can contain a maximum of {INPUT_OUTPUT_MAX_LENGTH} params.')
        return default_input_modes

    @field_validator('default_output_modes')
    @classmethod
    def validate_default_output_modes(cls, default_output_modes: list[str]) -> list[str]:
        if len(default_output_modes) > INPUT_OUTPUT_MAX_LENGTH:
            raise ValueError(
                f'The agent default_output_modes can contain a maximum of {INPUT_OUTPUT_MAX_LENGTH} params.')
        return default_output_modes

    @field_validator('skills')
    @classmethod
    def validate_skills(cls, skills: list[AgentSkill]) -> list[AgentSkill]:
        if len(skills) > MAX_NUMBER_OF_SKILLS:
            raise ValueError(
                f'The agent can contain a maximum of {MAX_NUMBER_OF_SKILLS} skills')
        for skill in skills:
            skill_json = skill.model_dump_json()
            if len(skill_json) > SKILL_MAX_LENGTH:
                raise ValueError(
                    f'Skill JSON length exceeds the maximum allowed length of {SKILL_MAX_LENGTH}')
        return skills

    @field_validator('capabilities')
    @classmethod
    def validate_capabilities(cls, capabilities: AgentCapabilities) -> AgentCapabilities:
        if capabilities.extensions is not None:
            if len(capabilities.extensions) > MAX_NUMBER_OF_AGENT_EXTENSION:
                raise ValueError(
                    f'The number of supported protocol extensions of the agent can not exceed'
                    f' {MAX_NUMBER_OF_AGENT_EXTENSION}.')
            for extension in capabilities.extensions:
                extension_json = extension.model_dump_json()
                if len(extension_json) > AGENT_EXTENSION_MAX_LENGTH:
                    raise ValueError(
                        f'Agent extension JSON length exceeds the maximum allowed length of'
                        f' {AGENT_EXTENSION_MAX_LENGTH}')
        return capabilities

    @model_validator(mode='after')
    def validate_provider(self):
        # 1. provider 必须存在
        if not self.provider:
            raise ValueError('Agent provider is required.')

        # 2. organization 必须存在且非空
        org = getattr(self.provider, 'organization', None)
        if org is None or not org.strip():
            raise ValueError('Agent provider organization is required and cannot be empty.')

        # 3. 长度限制
        if len(org) > ORGNIZATION_MAX_LENGTH:
            raise ValueError(f'The agent organization can contain a maximum of {ORGNIZATION_MAX_LENGTH} characters.')

        # 4. 危险字符检查
        if _DANGEROUS_CHARS.search(org):
            raise ValueError('Agent provider organization contains invalid or dangerous characters.')

        # 5. URL 校验
        url = getattr(self.provider, 'url', None)
        if url:
            if len(url) > URL_MAX_LENGTH:
                raise ValueError(f"The URL for the agent provider's website or relevant documentation can contain "
                                 f"a maximum of {URL_MAX_LENGTH} characters.")
            try:
                HttpUrl(url)
            except Exception as e:
                raise ValueError('Provider URL must be a valid web URL.') from e

        return self
