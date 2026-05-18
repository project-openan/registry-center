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

PROMPT_INJECTION_BLACKLIST_CN = [
    "忽略之前的指令",
    "忽略所有指令",
    "忽略上述指令",
    "无视指令",
    "忽略限制",
    "忽略规则",
    "忽略约束",
    "忽略安全",
    "覆盖指令",
    "覆盖规则",
    "覆盖系统",
    "忘记之前",
    "忘记所有",
    "忘记指令",
    "越狱",
    "破解",
    "绕过",
    "突破限制",
    "开发者模式",
    "管理员模式",
    "超级用户",
    "提示词注入",
    "必须执行",
    "必须输出",
    "必须回答",
    "无论如何",
    "不管怎样",
    "一定要",
    "无条件执行",
    "强制执行",
    "立即执行",
    "编码绕过",
    "</system>",
    "</instruction>",
    "</prompt>",
    "[END]",
    "[DONE]",
    "[FINISHED]",
    "assistant:",
    "system:",
    "user:",
]

PROMPT_INJECTION_BLACKLIST_EN = [
    # Instruction Override (14 items)
    "ignore previous instructions",
    "ignore previous commands",
    "ignore all instructions",
    "ignore all commands",
    "ignore above instructions",
    "disregard instructions",
    "ignore limits",
    "ignore restrictions",
    "ignore rules",
    "ignore constraints",
    "ignore security",
    "override instructions",
    "overwrite instructions",
    "override rules",
    "override system",
    "forget previous",
    "forget all",
    "forget instructions",
    
    # System Attack (8 items)
    "jailbreak",
    "crack",
    "bypass",
    "break limits",
    "break restrictions",
    "developer mode",
    "admin mode",
    "administrator mode",
    "superuser",
    "prompt injection",
    
    # Force Execution (9 items)
    "must execute",
    "must output",
    "must answer",
    "no matter what",
    "regardless",
    "must",
    "definitely",
    "unconditional execution",
    "force execute",
    "forced execution",
    "execute immediately",
    
    # Special Markers (12 items)
    "encoding bypass",
    "</system>",
    "</instruction>",
    "</prompt>",
    "[END]",
    "[DONE]",
    "[FINISHED]",
    "assistant:",
    "system:",
    "user:",
]

DANGEROUS_SKILL_BLACKLIST_CN = [
    "提权",
    "提升权限",
    "获取权限",
    "权限提升",
    "绕过安全",
    "绕过防护",
    "绕过验证",
    "突破安全",
    "突破防护",
    "安全绕过",
    "非法管理员权限",
    "非法超级权限",
    "非法root权限",
    "数据库注入",
    "SQL注入",
    "窃取密钥",
    "窃取密码",
    "窃取凭证",
    "非法获取密钥",
    "非法获取密码",
    "非法获取凭证",
    "网络攻击",
    "网络渗透",
    "网络入侵",
    "端口扫描",
    "漏洞扫描",
    "攻击扫描",
    "窃取数据",
    "盗取数据",
    "数据泄露",
    "窃取隐私",
    "非法获取隐私",
]

DANGEROUS_SKILL_BLACKLIST_EN = [
    # Privilege Attack (12 items)
    "privilege escalation",
    "escalate privileges",
    "elevate privileges",
    "raise privileges",
    "gain privileges",
    "obtain privileges",
    "bypass security",
    "bypass protection",
    "bypass authentication",
    "bypass verification",
    "break security",
    "break protection",
    "security bypass",
    "illegal admin privileges",
    "unauthorized admin privileges",
    "illegal superuser privileges",
    "illegal root privileges",
    
    # Database Attack (2 items)
    "database injection",
    "SQL injection",
    
    # Data Theft (11 items)
    "steal keys",
    "steal secret keys",
    "steal passwords",
    "steal credentials",
    "illegally obtain keys",
    "illegally obtain passwords",
    "illegally obtain credentials",
    "steal data",
    "data exfiltration",
    "data leak",
    "steal privacy",
    "steal private data",
    "illegally obtain privacy",
    
    # Network Attack (6 items)
    "network attack",
    "network penetration",
    "network intrusion",
    "port scan",
    "port scanning",
    "vulnerability scan",
    "attack scan",
]

# Combined blacklist (CN + EN) for efficient checking
PROMPT_INJECTION_BLACKLIST_ALL = PROMPT_INJECTION_BLACKLIST_CN + PROMPT_INJECTION_BLACKLIST_EN
DANGEROUS_SKILL_BLACKLIST_ALL = DANGEROUS_SKILL_BLACKLIST_CN + DANGEROUS_SKILL_BLACKLIST_EN

# Super combined blacklist for maximum performance in skills validation
MASTER_BLACKLIST_ALL = PROMPT_INJECTION_BLACKLIST_ALL + DANGEROUS_SKILL_BLACKLIST_ALL

DANGEROUS_SKILL_BLACKLIST_CN = [
    "提权",
    "提升权限",
    "获取权限",
    "权限提升",
    "绕过安全",
    "绕过防护",
    "绕过验证",
    "突破安全",
    "突破防护",
    "安全绕过",
    "非法管理员权限",
    "非法超级权限",
    "非法root权限",
    "数据库注入",
    "SQL注入",
    "窃取密钥",
    "窃取密码",
    "窃取凭证",
    "非法获取密钥",
    "非法获取密码",
    "非法获取凭证",
    "网络攻击",
    "网络渗透",
    "网络入侵",
    "端口扫描",
    "漏洞扫描",
    "攻击扫描",
    "窃取数据",
    "盗取数据",
    "数据泄露",
    "窃取隐私",
    "非法获取隐私",
]