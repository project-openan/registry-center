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
from typing import List, Tuple, Optional

from loguru import logger

from common.util.config_util import get_conf


class TagValidator:
    TAG_PATTERN = re.compile(r'^[\u4e00-\u9fa5a-zA-Z0-9_.\-]+$')
    
    def __init__(self):
        config = get_conf()
        self.max_count = int(config.get('tag.max.count', 10))
        self.max_length = int(config.get('tag.max.length', 50))
    
    def validate_single_tag(self, tag: str) -> Tuple[bool, Optional[str]]:
        if not tag:
            return False, "Tag cannot be empty"
        
        if len(tag) > self.max_length:
            return False, f"Tag length exceeds maximum {self.max_length} characters"
        
        if not self.TAG_PATTERN.match(tag):
            return False, "Tag contains invalid characters (only Chinese, letters, numbers, ., _ and - are allowed)"
        
        return True, None
    
    def validate_tags(self, tags: List[str]) -> Tuple[bool, Optional[str]]:
        if not tags:
            return True, None
        
        if len(tags) > self.max_count:
            return False, f"Number of tags exceeds maximum {self.max_count}"
        
        for tag in tags:
            valid, error = self.validate_single_tag(tag)
            if not valid:
                return False, f"Invalid tag '{tag}': {error}"
        
        return True, None
    
    def validate_add_tags(self, current_tags: List[str], new_tags: List[str]) -> Tuple[bool, Optional[str]]:
        if not new_tags:
            return True, None
        
        merged = list(set((current_tags or []) + new_tags))
        if len(merged) > self.max_count:
            return False, f"Adding these tags would exceed maximum {self.max_count} tags"
        
        return self.validate_tags(new_tags)
    
    def validate_update_tags(self, tags: List[str]) -> Tuple[bool, Optional[str]]:
        return self.validate_tags(tags)