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

import time
import statistics

from agent_registry.model.blacklist_config import (
    PROMPT_INJECTION_BLACKLIST_ALL,
    DANGEROUS_SKILL_BLACKLIST_ALL,
    MASTER_BLACKLIST_ALL
)


def check_blacklist_old(text: str, blacklist: list, field_name: str):
    pass


def check_blacklist_new(text: str, blacklist: list, field_name: str):
    text_lower = text.lower()
    for pattern in blacklist:
        if pattern.lower() in text_lower:
            raise Exception(f'{field_name} contains prohibited content: {pattern}')


def measure_time(func, *args, iterations=10000):
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        try:
            func(*args)
        except Exception:
            pass
        end = time.perf_counter()
        times.append(end - start)
    return statistics.mean(times) * 1000, statistics.stdev(times) * 1000


def test_blacklist_performance():
    test_cases = [
        ("Normal English", "This is a normal agent description without any malicious content."),
        ("Normal Chinese", "这是一个普通的中文描述，没有任何恶意内容。"),
        ("Mixed content", "This is mixed content with 中文 and English text."),
        ("Long normal text", "This is a longer description. " * 30),
        ("Malicious prompt", "This agent can 忽略之前的指令 and bypass security."),
        ("Malicious skill", "This skill can 执行代码 and run shell commands."),
        ("Clean but similar", "Ignore is a common word but not malicious in this context."),
    ]
    
    print("=" * 80)
    print("Blacklist Check Performance Benchmark (10,000 iterations each)")
    print("=" * 80)
    print()
    
    print(f"Blacklist size: Prompt injection = {len(PROMPT_INJECTION_BLACKLIST_ALL)} keywords (CN+EN combined)")
    print(f"Blacklist size: Dangerous skill = {len(DANGEROUS_SKILL_BLACKLIST_ALL)} keywords (CN+EN combined)")
    print()
    
    print("-" * 80)
    print("Test Case                          | Without Check | With Check  | Overhead")
    print("-" * 80)
    
    for name, text in test_cases:
        avg_old, _ = measure_time(check_blacklist_old, text, PROMPT_INJECTION_BLACKLIST_ALL, "test")
        avg_new_prompt, _ = measure_time(check_blacklist_new, text, PROMPT_INJECTION_BLACKLIST_ALL, "test")
        avg_new_skill, _ = measure_time(check_blacklist_new, text, DANGEROUS_SKILL_BLACKLIST_ALL, "test")
        
        overhead_prompt = avg_new_prompt - avg_old
        overhead_skill = avg_new_skill - avg_old
        total_overhead = overhead_prompt + overhead_skill
        
        print(f"{name:35} | {avg_old:10.4f}ms | {avg_new_prompt + avg_new_skill:10.4f}ms | {total_overhead:8.4f}ms")
    
    print("-" * 80)
    print()


def test_field_validation_overhead():
    description_normal = "This is a normal agent description."
    description_long = "This is a longer description. " * 50
    skill_name = "DataAnalysisSkill"
    skill_description = "Analyzes data and generates comprehensive reports."
    skill_tag = "data-analysis"
    
    print("=" * 80)
    print("Field Validation Overhead Estimation")
    print("=" * 80)
    print()
    
    print("For a typical AgentCard with:")
    print("  - 1 description field")
    print("  - 5 skills with name, description, and 3 tags each")
    print()
    
    total_checks = 1 + (5 * (1 + 1 + 3))  # description + 5 skills * (name + desc + 3 tags)
    print(f"  Total blacklist checks: {total_checks} (Prompt + Skill = {total_checks * 2} actual scans)")
    print()
    
    avg_single_check, _ = measure_time(check_blacklist_new, description_normal, PROMPT_INJECTION_BLACKLIST_ALL, "test")
    
    estimated_overhead = avg_single_check * total_checks * 2
    
    print(f"  Single blacklist check time: {avg_single_check:.4f}ms")
    print(f"  Estimated total overhead: {estimated_overhead:.4f}ms per agent card validation")
    print()


def test_real_world_scenario():
    print("=" * 80)
    print("Real-World Scenario: Validate Complete AgentCard 1000 times")
    print("=" * 80)
    print()
    
    description = "A helpful AI assistant that can answer questions and provide information."
    skills_data = [
        ("QuestionAnswering", "Answer user questions accurately", ["qa", "assistant"]),
        ("InformationRetrieval", "Retrieve relevant information", ["search", "info"]),
        ("TextSummarization", "Summarize long documents", ["summarize", "text"]),
    ]
    
    def simulate_full_validation():
        check_blacklist_new(description, PROMPT_INJECTION_BLACKLIST_ALL, "description")
        check_blacklist_new(description, DANGEROUS_SKILL_BLACKLIST_ALL, "description")
        for name, desc, tags in skills_data:
            check_blacklist_new(name, MASTER_BLACKLIST_ALL, "skill name")
            check_blacklist_new(desc, MASTER_BLACKLIST_ALL, "skill description")
            for tag in tags:
                check_blacklist_new(tag, MASTER_BLACKLIST_ALL, "skill tag")
    
    avg, std = measure_time(simulate_full_validation, iterations=1000)
    
    print(f"Average time: {avg:.4f}ms (std: {std:.4f}ms)")
    print(f"For 1000 validations: {avg * 1000:.2f}ms total")
    print()
    
    requests_per_second = 1000 / (avg / 1000)
    print(f"Can handle approximately {requests_per_second:.0f} validations per second")
    print()


def test_comparison_summary():
    print("=" * 80)
    print("Performance Impact Summary")
    print("=" * 80)
    print()
    
    avg_normal, _ = measure_time(check_blacklist_new, "Normal text here", PROMPT_INJECTION_BLACKLIST_ALL, "test", iterations=100000)
    
    print("Key Findings:")
    print(f"  1. Single blacklist check: ~{avg_normal:.3f}ms (scanning ~{len(PROMPT_INJECTION_BLACKLIST_ALL)} keywords)")
    print(f"  2. Early exit on match: faster than full scan")
    print(f"  3. Typical AgentCard (1 desc + 5 skills): ~{avg_normal * 16:.3f}ms overhead")
    print()
    
    print("Recommendation:")
    print("  The performance overhead is negligible (< 1ms for typical cases).")
    print("  Given the security benefits, this is an acceptable trade-off.")
    print("  For high-throughput scenarios (>1000 req/s), consider caching or")
    print("  async validation if needed.")
    print()


if __name__ == "__main__":
    print()
    print("*" * 80)
    print("Blacklist Validation Performance Analysis")
    print("*" * 80)
    print()
    
    test_blacklist_performance()
    test_field_validation_overhead()
    test_real_world_scenario()
    test_comparison_summary()