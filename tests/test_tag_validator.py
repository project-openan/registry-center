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

"""
Tag validator tests

Tests the TagValidator class for tag validation rules:
- Character validation (Chinese, letters, numbers, dot, underscore, hyphen)
- Length validation (max 50 characters)
- Count validation (max 10 tags)
"""

import pytest
from agent_registry.internal.utils.tag_validator import TagValidator


class TestTagValidator:
    """Test TagValidator class"""
    
    @pytest.fixture
    def validator(self):
        """Create TagValidator instance"""
        return TagValidator()
    
    # ========== Single Tag Validation Tests ==========
    
    def test_validate_single_tag_valid_english(self, validator):
        """Test valid English tag"""
        valid, error = validator.validate_single_tag("production")
        assert valid is True
        assert error is None
    
    def test_validate_single_tag_valid_with_dot(self, validator):
        """Test valid tag with dot"""
        valid, error = validator.validate_single_tag("v1.0")
        assert valid is True
        assert error is None
    
    def test_validate_single_tag_valid_with_underscore(self, validator):
        """Test valid tag with underscore"""
        valid, error = validator.validate_single_tag("test_tag")
        assert valid is True
        assert error is None
    
    def test_validate_single_tag_valid_with_hyphen(self, validator):
        """Test valid tag with hyphen"""
        valid, error = validator.validate_single_tag("v2.0-beta")
        assert valid is True
        assert error is None
    
    def test_validate_single_tag_valid_chinese(self, validator):
        """Test valid Chinese tag"""
        valid, error = validator.validate_single_tag("中文标签")
        assert valid is True
        assert error is None
    
    def test_validate_single_tag_valid_mixed(self, validator):
        """Test valid mixed Chinese and English tag"""
        valid, error = validator.validate_single_tag("测试.Test")
        assert valid is True
        assert error is None
    
    def test_validate_single_tag_empty(self, validator):
        """Test empty tag"""
        valid, error = validator.validate_single_tag("")
        assert valid is False
        assert "empty" in error.lower()
    
    def test_validate_single_tag_too_long(self, validator):
        """Test tag exceeding max length"""
        long_tag = "a" * 51  # 51 characters
        valid, error = validator.validate_single_tag(long_tag)
        assert valid is False
        assert "50" in error
    
    def test_validate_single_tag_max_length(self, validator):
        """Test tag at max length"""
        max_tag = "a" * 50  # 50 characters
        valid, error = validator.validate_single_tag(max_tag)
        assert valid is True
        assert error is None
    
    def test_validate_single_tag_invalid_special_chars(self, validator):
        """Test tag with invalid special characters"""
        invalid_tags = [
            "tag@name",
            "tag#1",
            "tag$name",
            "tag%value",
            "tag&test",
            "tag*name",
            "tag!value",
            "tag name",  # space not allowed
            "tag/name",
        ]
        
        for tag in invalid_tags:
            valid, error = validator.validate_single_tag(tag)
            assert valid is False
            assert "invalid characters" in error.lower()
    
    # ========== Tags List Validation Tests ==========
    
    def test_validate_tags_empty_list(self, validator):
        """Test empty tags list"""
        valid, error = validator.validate_tags([])
        assert valid is True
        assert error is None
    
    def test_validate_tags_valid_list(self, validator):
        """Test valid tags list"""
        tags = ["production", "v1.0", "test_tag"]
        valid, error = validator.validate_tags(tags)
        assert valid is True
        assert error is None
    
    def test_validate_tags_exceed_max_count(self, validator):
        """Test tags list exceeding max count"""
        tags = [f"tag{i}" for i in range(11)]  # 11 tags
        valid, error = validator.validate_tags(tags)
        assert valid is False
        assert "10" in error
    
    def test_validate_tags_at_max_count(self, validator):
        """Test tags list at max count"""
        tags = [f"tag{i}" for i in range(10)]  # 10 tags
        valid, error = validator.validate_tags(tags)
        assert valid is True
        assert error is None
    
    def test_validate_tags_with_invalid_tag(self, validator):
        """Test tags list containing invalid tag"""
        tags = ["valid_tag", "invalid@tag", "another_valid"]
        valid, error = validator.validate_tags(tags)
        assert valid is False
        assert "invalid@tag" in error
    
    # ========== Add Tags Validation Tests ==========
    
    def test_validate_add_tags_empty(self, validator):
        """Test adding empty tags list"""
        current_tags = ["existing"]
        new_tags = []
        valid, error = validator.validate_add_tags(current_tags, new_tags)
        assert valid is True
        assert error is None
    
    def test_validate_add_tags_within_limit(self, validator):
        """Test adding tags within limit"""
        current_tags = ["tag1", "tag2"]
        new_tags = ["tag3", "tag4"]
        valid, error = validator.validate_add_tags(current_tags, new_tags)
        assert valid is True
        assert error is None
    
    def test_validate_add_tags_exceed_limit(self, validator):
        """Test adding tags exceeding limit"""
        current_tags = [f"tag{i}" for i in range(8)]
        new_tags = ["tag8", "tag9", "tag10"]  # Would result in 11 tags
        valid, error = validator.validate_add_tags(current_tags, new_tags)
        assert valid is False
        assert "10" in error
    
    def test_validate_add_tags_duplicate(self, validator):
        """Test adding duplicate tags"""
        current_tags = ["production", "v1.0"]
        new_tags = ["production", "v2.0"]
        valid, error = validator.validate_add_tags(current_tags, new_tags)
        assert valid is True
        assert error is None
    
    def test_validate_add_tags_with_invalid(self, validator):
        """Test adding tags with invalid tag"""
        current_tags = ["valid"]
        new_tags = ["valid_tag", "invalid@tag"]
        valid, error = validator.validate_add_tags(current_tags, new_tags)
        assert valid is False
        assert "invalid@tag" in error
    
    # ========== Update Tags Validation Tests ==========
    
    def test_validate_update_tags_valid(self, validator):
        """Test updating with valid tags"""
        tags = ["new_tag1", "new_tag2", "new_tag3"]
        valid, error = validator.validate_update_tags(tags)
        assert valid is True
        assert error is None
    
    def test_validate_update_tags_empty(self, validator):
        """Test updating with empty tags (clearing)"""
        tags = []
        valid, error = validator.validate_update_tags(tags)
        assert valid is True
        assert error is None
    
    def test_validate_update_tags_exceed_count(self, validator):
        """Test updating with too many tags"""
        tags = [f"tag{i}" for i in range(11)]
        valid, error = validator.validate_update_tags(tags)
        assert valid is False
        assert "10" in error


class TestTagPattern:
    """Test tag regex pattern directly"""
    
    def test_pattern_matches_valid_tags(self):
        """Test pattern matches all valid tag formats"""
        import re
        pattern = re.compile(r'^[\u4e00-\u9fa5a-zA-Z0-9_.\-]+$')
        
        valid_tags = [
            "production",
            "v1.0",
            "test_tag",
            "v2.0-beta",
            "中文标签",
            "测试.Test",
            "app.service.v1",
            "Module_1",
            "feature-2",
            "ABC123",
            "123test",
        ]
        
        for tag in valid_tags:
            assert pattern.match(tag) is not None, f"Tag '{tag}' should be valid"
    
    def test_pattern_rejects_invalid_tags(self):
        """Test pattern rejects invalid tag formats"""
        import re
        pattern = re.compile(r'^[\u4e00-\u9fa5a-zA-Z0-9_.\-]+$')
        
        invalid_tags = [
            "tag@name",
            "tag#1",
            "tag space",
            "tag/name",
            "tag!value",
            "",
        ]
        
        for tag in invalid_tags:
            assert pattern.match(tag) is None, f"Tag '{tag}' should be invalid"