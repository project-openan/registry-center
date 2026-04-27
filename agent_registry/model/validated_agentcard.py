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

from a2a.types import AgentCard, AgentProvider, AgentSkill, AgentCapabilities, AgentInterface
from fastapi import HTTPException, status
from google.protobuf.internal.containers import RepeatedScalarFieldContainer, RepeatedCompositeFieldContainer
from google.protobuf.json_format import MessageToJson
from pydantic import HttpUrl

_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_]+(?:\s+[a-zA-Z0-9_]+)*$')

NAME_MAX_LENGTH = 100
ORGANIZATION_MAX_LENGTH = 100
DESCRIPTION_MAX_LENGTH = 1000
URL_MAX_LENGTH = 1024
VERSION_MAX_LENGTH = 50
INPUT_OUTPUT_MAX_LENGTH = 100
MAX_NUMBER_OF_SKILLS = 100
SKILL_MAX_LENGTH = 4096
MAX_NUMBER_OF_AGENT_EXTENSION = 10
AGENT_EXTENSION_MAX_LENGTH = 512

_DANGEROUS_CHARS = re.compile(r'[\x00-\x1F\x7F\x80-\x9F\u2028\u2029\u202D\u202E\u200B\u200C\u200D\uFEFF\u2066-\u2069]')


def validate_name(v: str):
    if len(v) > NAME_MAX_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f'The agent name can contain a maximum of {NAME_MAX_LENGTH} characters.')
    if not _NAME_PATTERN.fullmatch(v):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail='The name can contain only letters, digits, underscores (_), spaces.')


def validate_description(description: str):
    if len(description) > DESCRIPTION_MAX_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f'The agent description can contain a maximum of {DESCRIPTION_MAX_LENGTH} characters.')


def validate_supported_interfaces(supported_interfaces: RepeatedCompositeFieldContainer[AgentInterface]):
    for interface in supported_interfaces:
        if len(interface.url) > URL_MAX_LENGTH:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f'The agent url can contain a maximum of {URL_MAX_LENGTH} characters.')
        try:
            HttpUrl(interface.url)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail='Provider URL must be a valid web URL.') from e


def validate_version(version: str):
    if len(version) > VERSION_MAX_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f'The agent version can contain a maximum of {VERSION_MAX_LENGTH} characters.')


def validate_default_input_modes(default_input_modes: RepeatedScalarFieldContainer[str]):
    if len(default_input_modes) > INPUT_OUTPUT_MAX_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f'The agent default_input_modes can contain a maximum of {INPUT_OUTPUT_MAX_LENGTH} params.')


def validate_default_output_modes(default_output_modes: RepeatedScalarFieldContainer[str]):
    if len(default_output_modes) > INPUT_OUTPUT_MAX_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f'The agent default_output_modes can contain a maximum of {INPUT_OUTPUT_MAX_LENGTH} params.')


def validate_skills(skills: RepeatedCompositeFieldContainer[AgentSkill]):
    if len(skills) > MAX_NUMBER_OF_SKILLS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f'The agent can contain a maximum of {MAX_NUMBER_OF_SKILLS} skills')
    for skill in skills:
        skill_json = MessageToJson(skill)
        if len(skill_json) > SKILL_MAX_LENGTH:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f'Skill JSON length exceeds the maximum allowed length of {SKILL_MAX_LENGTH}')


def validate_capabilities(capabilities: AgentCapabilities):
    if capabilities.extensions is not None:
        if len(capabilities.extensions) > MAX_NUMBER_OF_AGENT_EXTENSION:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f'The number of supported protocol extensions of the agent can not exceed'
                       f' {MAX_NUMBER_OF_AGENT_EXTENSION}.')
        for extension in capabilities.extensions:
            extension_json = MessageToJson(extension)
            if len(extension_json) > AGENT_EXTENSION_MAX_LENGTH:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f'Agent extension JSON length exceeds the maximum allowed length of'
                           f' {AGENT_EXTENSION_MAX_LENGTH}')


def validate_provider(provider: AgentProvider):
    # 1. Provider must exist
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail='Agent provider is required.')

    # 2. Organization must exist and be non-empty
    org = getattr(provider, 'organization', None)
    if org is None or not org.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail='Agent provider organization is required and cannot be empty.')

    # 3. Length limit
    if len(org) > ORGANIZATION_MAX_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f'The agent organization can contain a maximum of {ORGANIZATION_MAX_LENGTH} characters.')

    # 4. Dangerous character check
    if _DANGEROUS_CHARS.search(org):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail='Agent provider organization contains invalid or dangerous characters.')

    # 5. URL validation
    url = getattr(provider, 'url', None)
    if url:
        if len(url) > URL_MAX_LENGTH:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"The URL for the agent provider's website or relevant documentation can contain "
                       f"a maximum of {URL_MAX_LENGTH} characters.")
        try:
            HttpUrl(url)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail='Provider URL must be a valid web URL.') from e


def validate_agent_card(agent: AgentCard):
    validate_name(agent.name)
    validate_description(agent.description)
    validate_version(agent.version)
    validate_default_input_modes(agent.default_input_modes)
    validate_default_output_modes(agent.default_output_modes)
    validate_skills(agent.skills)
    validate_capabilities(agent.capabilities)
    validate_provider(agent.provider)
    validate_supported_interfaces(agent.supported_interfaces)