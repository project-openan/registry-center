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

import pytest
from unittest.mock import Mock, MagicMock, patch
from fastapi import HTTPException, status

from agent_registry.model.validated_agentcard import (
    check_blacklist,
    validate_description,
    validate_skills,
    DESCRIPTION_MAX_LENGTH,
    MAX_NUMBER_OF_SKILLS,
    SKILL_MAX_LENGTH
)
from agent_registry.model.blacklist_config import (
    PROMPT_INJECTION_BLACKLIST,
    DANGEROUS_SKILL_BLACKLIST
)


def create_mock_skill(name: str, description: str, tags: list):
    """Create a mock AgentSkill object"""
    skill = Mock()
    skill.name = name
    skill.description = description
    skill.tags = tags
    return skill


def create_mock_skills_container(skills: list):
    """Create a mock RepeatedCompositeFieldContainer"""
    container = MagicMock()
    container.__len__ = Mock(return_value=len(skills))
    container.__iter__ = Mock(return_value=iter(skills))
    return container


class TestCheckBlacklist:
    """Test cases for check_blacklist function"""

    def test_check_blacklist_normal_text(self):
        """Test with normal text that does not contain blacklisted keywords"""
        normal_text = "This is a normal agent description without malicious content"
        check_blacklist(normal_text, PROMPT_INJECTION_BLACKLIST, "test field")
        check_blacklist(normal_text, DANGEROUS_SKILL_BLACKLIST, "test field")

    def test_check_blacklist_normal_chinese_text(self):
        """Test with normal Chinese text"""
        normal_chinese = "这是一个普通的Agent描述，用于数据分析"
        check_blacklist(normal_chinese, PROMPT_INJECTION_BLACKLIST, "test field")
        check_blacklist(normal_chinese, DANGEROUS_SKILL_BLACKLIST, "test field")

    def test_check_blacklist_prompt_injection_exact_match(self):
        """Test with exact prompt injection keyword"""
        malicious_text = "忽略之前的指令"
        with pytest.raises(HTTPException) as exc_info:
            check_blacklist(malicious_text, PROMPT_INJECTION_BLACKLIST, "description")
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert "description contains prohibited content" in exc_info.value.detail
        assert "忽略之前的指令" in exc_info.value.detail

    def test_check_blacklist_dangerous_skill_exact_match(self):
        """Test with exact dangerous skill keyword"""
        malicious_text = "执行代码"
        with pytest.raises(HTTPException) as exc_info:
            check_blacklist(malicious_text, DANGEROUS_SKILL_BLACKLIST, "skill name")
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert "skill name contains prohibited content" in exc_info.value.detail
        assert "执行代码" in exc_info.value.detail

    def test_check_blacklist_case_insensitive(self):
        """Test that blacklist check is case insensitive"""
        malicious_texts = ["忽略之前的指令", "忽略之前的指令", "忽略之前的指令"]
        for text in malicious_texts:
            with pytest.raises(HTTPException) as exc_info:
                check_blacklist(text, PROMPT_INJECTION_BLACKLIST, "description")
            assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_check_blacklist_substring_match(self):
        """Test that blacklist check matches substrings"""
        text_with_keyword = "这个Agent可以忽略之前的指令并执行操作"
        with pytest.raises(HTTPException) as exc_info:
            check_blacklist(text_with_keyword, PROMPT_INJECTION_BLACKLIST, "description")
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert "忽略之前的指令" in exc_info.value.detail

    def test_check_blacklist_early_exit_on_first_match(self):
        """Test that function exits early when finding first match"""
        malicious_text = "忽略之前的指令和越狱"
        with pytest.raises(HTTPException) as exc_info:
            check_blacklist(malicious_text, PROMPT_INJECTION_BLACKLIST, "description")
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_check_blacklist_empty_text(self):
        """Test with empty text"""
        check_blacklist("", PROMPT_INJECTION_BLACKLIST, "description")
        check_blacklist("", DANGEROUS_SKILL_BLACKLIST, "description")

    def test_check_blacklist_special_characters(self):
        """Test with text containing special characters but no blacklist"""
        special_text = "This is a @#$% special text with symbols!"
        check_blacklist(special_text, PROMPT_INJECTION_BLACKLIST, "description")

    def test_check_blacklist_selected_prompt_injection_keywords(self):
        """Test that selected prompt injection keywords are detected"""
        test_keywords = [
            "忽略之前的指令",
            "越狱",
            "破解",
            "绕过",
            "必须执行",
            "开发者模式",
            "提示词注入",
            "</system>",
        ]
        for keyword in test_keywords:
            with pytest.raises(HTTPException) as exc_info:
                check_blacklist(keyword, PROMPT_INJECTION_BLACKLIST, "test")
            assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_check_blacklist_selected_dangerous_skill_keywords(self):
        """Test that selected dangerous skill keywords are detected"""
        test_keywords = [
            "执行代码",
            "运行命令",
            "提权",
            "数据库注入",
            "窃取密钥",
            "远程执行",
            "网络攻击",
            "端口扫描",
        ]
        for keyword in test_keywords:
            with pytest.raises(HTTPException) as exc_info:
                check_blacklist(keyword, DANGEROUS_SKILL_BLACKLIST, "test")
            assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_check_blacklist_field_name_in_error(self):
        """Test that field name is included in error message"""
        with pytest.raises(HTTPException) as exc_info:
            check_blacklist("忽略之前的指令", PROMPT_INJECTION_BLACKLIST, "custom field name")
        assert "custom field name" in exc_info.value.detail


class TestValidateDescription:
    """Test cases for validate_description function"""

    def test_validate_description_normal(self):
        """Test with normal description"""
        description = "A helpful AI assistant for data analysis and reporting"
        validate_description(description)

    def test_validate_description_normal_chinese(self):
        """Test with normal Chinese description"""
        description = "一个用于数据分析和报告生成的智能助手"
        validate_description(description)

    def test_validate_description_max_length(self):
        """Test with description at max length"""
        description = "A" * DESCRIPTION_MAX_LENGTH
        validate_description(description)

    def test_validate_description_exceeds_max_length(self):
        """Test with description exceeding max length"""
        description = "A" * (DESCRIPTION_MAX_LENGTH + 1)
        with pytest.raises(HTTPException) as exc_info:
            validate_description(description)
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert "maximum of" in exc_info.value.detail
        assert str(DESCRIPTION_MAX_LENGTH) in exc_info.value.detail

    def test_validate_description_prompt_injection_keyword(self):
        """Test with prompt injection keyword in description"""
        description = "This agent can 忽略之前的指令 to help users"
        with pytest.raises(HTTPException) as exc_info:
            validate_description(description)
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert "description contains prohibited content" in exc_info.value.detail

    def test_validate_description_dangerous_skill_keyword(self):
        """Test with dangerous skill keyword in description"""
        description = "This agent can 执行代码 and run commands"
        with pytest.raises(HTTPException) as exc_info:
            validate_description(description)
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert "description contains prohibited content" in exc_info.value.detail

    def test_validate_description_multiple_blacklist_keywords(self):
        """Test with multiple blacklist keywords"""
        description = "这个Agent可以忽略之前的指令并执行代码"
        with pytest.raises(HTTPException) as exc_info:
            validate_description(description)
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_validate_description_keyword_at_end(self):
        """Test with keyword at the end of description"""
        description = "A helpful assistant that can 忽略之前的指令"
        with pytest.raises(HTTPException) as exc_info:
            validate_description(description)
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_validate_description_keyword_at_start(self):
        """Test with keyword at the start of description"""
        description = "忽略之前的指令 is not allowed"
        with pytest.raises(HTTPException) as exc_info:
            validate_description(description)
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_validate_description_real_world_compliant(self):
        """Test with real-world compliant descriptions"""
        compliant_descriptions = [
            "数据分析Agent，能够处理CSV、JSON等格式数据，生成可视化报告",
            "智能客服助手，回答产品相关问题并提供解决方案",
            "文本处理Agent，支持文本摘要、翻译和关键词提取",
            "A document processing agent that extracts information from PDF files",
        ]
        for desc in compliant_descriptions:
            validate_description(desc)

    def test_validate_description_real_world_non_compliant(self):
        """Test with real-world non-compliant descriptions"""
        non_compliant_descriptions = [
            "可以越狱获取管理员权限的Agent",
            "能够执行Shell命令和系统命令的助手",
            "可以绕过安全限制访问数据库",
        ]
        for desc in non_compliant_descriptions:
            with pytest.raises(HTTPException) as exc_info:
                validate_description(desc)
            assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


class TestValidateSkills:
    """Test cases for validate_skills function"""

    @patch('agent_registry.model.validated_agentcard.MessageToJson')
    def test_validate_skills_empty(self, mock_message_to_json):
        """Test with empty skills list"""
        skills = create_mock_skills_container([])
        validate_skills(skills)
        mock_message_to_json.assert_not_called()

    @patch('agent_registry.model.validated_agentcard.MessageToJson')
    def test_validate_skills_single_normal(self, mock_message_to_json):
        """Test with single normal skill"""
        mock_message_to_json.return_value = '{"name": "DataAnalysis"}'
        skill = create_mock_skill("DataAnalysis", "Analyzes data", ["data", "analysis"])
        skills = create_mock_skills_container([skill])
        validate_skills(skills)

    @patch('agent_registry.model.validated_agentcard.MessageToJson')
    def test_validate_skills_multiple_normal(self, mock_message_to_json):
        """Test with multiple normal skills"""
        mock_message_to_json.return_value = '{"name": "Skill"}'
        skills_list = [
            create_mock_skill("Skill1", "Description 1", ["tag1"]),
            create_mock_skill("Skill2", "Description 2", ["tag2"]),
            create_mock_skill("Skill3", "Description 3", ["tag3"]),
        ]
        skills = create_mock_skills_container(skills_list)
        validate_skills(skills)

    def test_validate_skills_exceeds_max_count(self):
        """Test with skills exceeding max count"""
        skills_list = [create_mock_skill(f"Skill{i}", f"Desc{i}", ["tag"]) for i in range(MAX_NUMBER_OF_SKILLS + 1)]
        skills = create_mock_skills_container(skills_list)
        with pytest.raises(HTTPException) as exc_info:
            validate_skills(skills)
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert "maximum of" in exc_info.value.detail
        assert str(MAX_NUMBER_OF_SKILLS) in exc_info.value.detail

    def test_validate_skill_name_prompt_injection(self):
        """Test with prompt injection keyword in skill name"""
        skill = create_mock_skill("忽略之前的指令", "Normal description", ["tag"])
        skills = create_mock_skills_container([skill])
        with pytest.raises(HTTPException) as exc_info:
            validate_skills(skills)
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert "skill name" in exc_info.value.detail

    def test_validate_skill_name_dangerous(self):
        """Test with dangerous skill keyword in skill name"""
        skill = create_mock_skill("执行代码", "Normal description", ["tag"])
        skills = create_mock_skills_container([skill])
        with pytest.raises(HTTPException) as exc_info:
            validate_skills(skills)
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert "skill name" in exc_info.value.detail

    def test_validate_skill_description_prompt_injection(self):
        """Test with prompt injection keyword in skill description"""
        skill = create_mock_skill("NormalName", "这个技能可以忽略之前的指令", ["tag"])
        skills = create_mock_skills_container([skill])
        with pytest.raises(HTTPException) as exc_info:
            validate_skills(skills)
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert "skill description" in exc_info.value.detail

    def test_validate_skill_description_dangerous(self):
        """Test with dangerous skill keyword in skill description"""
        skill = create_mock_skill("NormalName", "此技能可以执行Shell命令", ["tag"])
        skills = create_mock_skills_container([skill])
        with pytest.raises(HTTPException) as exc_info:
            validate_skills(skills)
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert "skill description" in exc_info.value.detail

    def test_validate_skill_tag_prompt_injection(self):
        """Test with prompt injection keyword in skill tag"""
        skill = create_mock_skill("NormalName", "Normal description", ["越狱", "normal"])
        skills = create_mock_skills_container([skill])
        with pytest.raises(HTTPException) as exc_info:
            validate_skills(skills)
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert "skill tag" in exc_info.value.detail

    def test_validate_skill_tag_dangerous(self):
        """Test with dangerous skill keyword in skill tag"""
        skill = create_mock_skill("NormalName", "Normal description", ["提权", "normal"])
        skills = create_mock_skills_container([skill])
        with pytest.raises(HTTPException) as exc_info:
            validate_skills(skills)
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert "skill tag" in exc_info.value.detail

    def test_validate_skills_multiple_tags_one_malicious(self):
        """Test skill with multiple tags where one is malicious"""
        skill = create_mock_skill("Skill", "Description", ["normal", "data", "绕过安全"])
        skills = create_mock_skills_container([skill])
        with pytest.raises(HTTPException) as exc_info:
            validate_skills(skills)
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert "skill tag" in exc_info.value.detail

    @patch('agent_registry.model.validated_agentcard.MessageToJson')
    def test_validate_skills_multiple_skills_one_malicious(self, mock_message_to_json):
        """Test multiple skills where one is malicious"""
        mock_message_to_json.return_value = '{"name": "Skill"}'
        skills_list = [
            create_mock_skill("Skill1", "Description 1", ["tag1"]),
            create_mock_skill("Skill2", "此技能可以提权", ["tag2"]),
            create_mock_skill("Skill3", "Description 3", ["tag3"]),
        ]
        skills = create_mock_skills_container(skills_list)
        with pytest.raises(HTTPException) as exc_info:
            validate_skills(skills)
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_validate_skills_all_fields_malicious(self):
        """Test skill with all fields containing malicious content"""
        skill = create_mock_skill("执行代码", "忽略之前的指令", ["越狱"])
        skills = create_mock_skills_container([skill])
        with pytest.raises(HTTPException) as exc_info:
            validate_skills(skills)
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    @patch('agent_registry.model.validated_agentcard.MessageToJson')
    def test_validate_skills_real_world_compliant(self, mock_message_to_json):
        """Test with real-world compliant skills"""
        mock_message_to_json.return_value = '{"name": "Skill"}'
        skills_list = [
            create_mock_skill("数据分析", "对用户提供的数据进行分析并生成统计报告", ["analysis", "report"]),
            create_mock_skill("文档处理", "处理PDF、Word等文档格式，提取关键信息", ["document", "extraction"]),
            create_mock_skill("智能问答", "基于知识库回答用户问题，提供准确信息服务", ["qa", "knowledge"]),
        ]
        skills = create_mock_skills_container(skills_list)
        validate_skills(skills)

    def test_validate_skills_real_world_non_compliant(self):
        """Test with real-world non-compliant skills"""
        non_compliant_cases = [
            ("Shell执行", "Normal description", ["tag"]),
            ("Skill", "可以执行代码", ["tag"]),
            ("Skill", "Description", ["提权"]),
        ]
        for name, desc, tags in non_compliant_cases:
            skill = create_mock_skill(name, desc, tags)
            skills = create_mock_skills_container([skill])
            with pytest.raises(HTTPException) as exc_info:
                validate_skills(skills)
            assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    @patch('agent_registry.model.validated_agentcard.MessageToJson')
    def test_validate_skills_with_mixed_chinese_english(self, mock_message_to_json):
        """Test skills with mixed Chinese and English content"""
        mock_message_to_json.return_value = '{"name": "Skill"}'
        skill = create_mock_skill("DataAnalysis数据分析", "This skill analyzes 分析数据", ["analysis", "分析"])
        skills = create_mock_skills_container([skill])
        validate_skills(skills)


class TestValidateDescriptionIntegration:
    """Integration tests for description validation with blacklist"""

    def test_description_with_selected_categories_prompt_injection(self):
        """Test description containing keywords from selected prompt injection categories"""
        categories = {
            "指令覆盖": "忽略之前的指令",
            "系统攻击": "越狱",
            "安全绕过": "绕过",
            "强制执行": "必须执行",
            "开发模式": "开发者模式",
            "特殊标记": "</system>",
        }
        for category, keyword in categories.items():
            with pytest.raises(HTTPException) as exc_info:
                validate_description(f"This agent can {keyword}")
            assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_description_with_selected_categories_dangerous_skill(self):
        """Test description containing keywords from selected dangerous skill categories"""
        categories = {
            "代码执行": "执行代码",
            "权限攻击": "提权",
            "数据库攻击": "数据库注入",
            "数据窃取": "窃取密钥",
            "远程攻击": "远程执行",
            "网络攻击": "网络攻击",
            "扫描攻击": "端口扫描",
            "隐私窃取": "窃取隐私",
        }
        for category, keyword in categories.items():
            with pytest.raises(HTTPException) as exc_info:
                validate_description(f"This skill can {keyword}")
            assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_description_legitimate_use_of_common_words(self):
        """Test that legitimate use of common words is allowed"""
        legitimate_descriptions = [
            "An agent that helps users analyze data and generate reports",
            "An agent that provides executive summaries of documents",
            "An agent that helps developers code faster",
            "An agent for data processing and transformation",
        ]
        for desc in legitimate_descriptions:
            validate_description(desc)


class TestEdgeCases:
    """Edge case tests for blacklist validation"""

    def test_whitespace_only_text(self):
        """Test with whitespace only text"""
        check_blacklist("   ", PROMPT_INJECTION_BLACKLIST, "description")
        check_blacklist("\n\t", DANGEROUS_SKILL_BLACKLIST, "description")

    def test_unicode_characters_without_keyword(self):
        """Test with unicode characters without blacklisted keywords"""
        unicode_text = "这是一个包含Unicode字符的描述 😊"
        check_blacklist(unicode_text, PROMPT_INJECTION_BLACKLIST, "description")

    def test_keyword_as_part_of_normal_word(self):
        """Test when blacklisted keyword appears as part of a normal word"""
        text = "This is an analyzer that helps with data"
        check_blacklist(text, DANGEROUS_SKILL_BLACKLIST, "description")

    def test_multiple_keywords_spread_across_text(self):
        """Test multiple keywords spread across the text"""
        text = "Start normal text 忽略之前的指令 middle text 执行代码 end text"
        with pytest.raises(HTTPException) as exc_info:
            check_blacklist(text, PROMPT_INJECTION_BLACKLIST, "description")
        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    def test_exact_blacklist_keyword(self):
        """Test exact blacklist keyword without any other text"""
        prompt_keywords = ["忽略之前的指令", "越狱"]
        for keyword in prompt_keywords:
            with pytest.raises(HTTPException):
                check_blacklist(keyword, PROMPT_INJECTION_BLACKLIST, "test")
        
        skill_keywords = ["执行代码", "提权"]
        for keyword in skill_keywords:
            with pytest.raises(HTTPException):
                check_blacklist(keyword, DANGEROUS_SKILL_BLACKLIST, "test")