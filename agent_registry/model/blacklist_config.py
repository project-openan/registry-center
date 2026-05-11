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

PROMPT_INJECTION_BLACKLIST = [
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

DANGEROUS_SKILL_BLACKLIST = [
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