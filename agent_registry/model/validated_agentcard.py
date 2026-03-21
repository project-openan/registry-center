import re

from a2a.types import AgentCard, AgentProvider
from pydantic import field_validator, model_validator, HttpUrl

_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9_]+(?:\s+[a-zA-Z0-9_]+)*$')


class ValidatedAgentCard(AgentCard):
    """
    A2A-T requires information about the agent's service provider.
    """
    provider: AgentProvider

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        if len(v) > 100:
            raise ValueError('The agent name can contain a maximum of 100 characters.')
        """验证名称仅包含字母、数字和下划线"""
        if not _NAME_PATTERN.fullmatch(v):
            raise ValueError('Name must contain only alphanumeric characters and underscores.')
        return v

    @field_validator('description')
    @classmethod
    def validate_description(cls, description: str) -> str:
        if len(description) > 1000:
            raise ValueError('The agent description can contain a maximum of 1000 characters.')
        return description

    @field_validator('url')
    @classmethod
    def validate_url(cls, url: str) -> str:
        if len(url) > 1024:
            raise ValueError('The agent url can contain a maximum of 1024 characters.')
        return url

    @field_validator('version')
    @classmethod
    def validate_version(cls, version: str) -> str:
        if len(version) > 50:
            raise ValueError('The agent version can contain a maximum of 50 characters.')
        return version

    @field_validator('default_input_modes')
    @classmethod
    def validate_default_input_modes(cls, default_input_modes: list[str]) -> list[str]:
        if len(default_input_modes) > 100:
            raise ValueError('The agent default_input_modes can contain a maximum of 100 params.')
        return default_input_modes

    @field_validator('default_output_modes')
    @classmethod
    def validate_default_output_modes(cls, default_output_modes: list[str]) -> list[str]:
        if len(default_output_modes) > 100:
            raise ValueError('The agent default_output_modes can contain a maximum of 100 params.')
        return default_output_modes

    @model_validator(mode='after')
    def validate_provider(self):
        if self.provider and hasattr(self.provider, 'url') and self.provider.url:
            if len(self.provider.url) > 1024:
                raise ValueError("The URL for the agent provider's website or relevant documentation can contain "
                                 "a maximum of 1024 characters.")
            try:
                # 如果 url 不符合标准，HttpUrl 会抛出 ValidationError
                HttpUrl(self.provider.url)
            except Exception as e:
                raise ValueError('Provider URL must be a valid web URL.') from e
        if self.provider and hasattr(self.provider, 'orgnization') and self.provider.orgnization and len(
                self.provider.orgnization) > 100:
            raise ValueError('The agent orgnization can contain a maximum of 100 characters.')
        return self
