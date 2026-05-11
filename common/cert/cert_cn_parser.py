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
import string
from typing import Optional

from common.cert.x509_obj import CertObj


def extract_cn_from_subject(subject: str) -> Optional[str]:
    """
    Extract CN value from certificate Subject string
    
    Subject format: CN=xxx,OU=yyy,O=zzz...
    Supports multiple formats:
    - CN=agent-admin-001,OU=...
    
    Args:
        subject: RFC4514 format Subject string
        
    Returns:
        CN value, None if not present
    """
    if not subject:
        return None
    
    pattern = r'CN=([^,]+)'
    match = re.search(pattern, subject)
    if match:
        cn_value = match.group(1).strip()
        cn_value = cn_value.replace('\\,', ',')
        return cn_value
    
    return None


def extract_cn_from_cert(cert_obj: CertObj) -> Optional[str]:
    """
    Extract CN from CertObj
    
    Args:
        cert_obj: CertObj instance
        
    Returns:
        CN value
    """
    return extract_cn_from_subject(cert_obj.subject)


def validate_cn(cn: str) -> bool:
    """
    Validate CN format
    
    Rules:
    - Length: 1-64 bytes (UTF-8 encoding)
    - Allowed characters: letters, digits, hyphen, dot
    - Forbidden: special symbols, control characters, spaces, underscores
    
    Args:
        cn: CN value
        
    Returns:
        True if valid, False otherwise
    """
    if not cn:
        return False
    
    if len(cn.encode('utf-8')) > 64:
        return False
    
    allowed_chars = string.ascii_letters + string.digits + '-.'
    
    return all(c in allowed_chars for c in cn)