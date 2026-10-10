# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0
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

"""Cloud Run entrypoint materializes a secret-free model definition."""

import os
import subprocess
import shutil
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[1] / "bin" / "entrypoint.sh"


def _run_entrypoint(tmp_path, **extra_env):
    bash = os.environ.get("BASH_BIN") or shutil.which("bash")
    if not bash:
        pytest.skip("Bash unavailable")
    workspace = str(tmp_path)
    if os.name == "nt":
        workspace = subprocess.check_output(
            [bash, "-c", 'cygpath -u "$1"', "test", workspace], text=True).strip()
    env = {"APP_HOME": workspace, "PATH": os.environ["PATH"], **extra_env}
    return subprocess.run([bash, str(SCRIPT), "true"], env=env, capture_output=True, text=True)


@pytest.mark.skipif(os.name == "nt", reason="POSIX container entrypoint")
def test_entrypoint_generates_chat_without_writing_secret(tmp_path):
    (tmp_path / "etc" / "config").mkdir(parents=True)
    result = _run_entrypoint(
        tmp_path,
        LLM_CHAT_MODEL="model",
        LLM_CHAT_URL="https://example.invalid/chat",
        LLM_CHAT_API_KEY="secret-value",
    )
    assert result.returncode == 0, result.stderr
    path = tmp_path / "etc" / "config" / "models.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert document["models"]["chat"]["api_key_env"] == "LLM_CHAT_API_KEY"
    assert document["models"]["chat"]["provider"] == "openai_compatible"
    assert "secret-value" not in path.read_text(encoding="utf-8")


@pytest.mark.skipif(os.name == "nt", reason="POSIX container entrypoint")
def test_entrypoint_keeps_existing_model_file(tmp_path):
    config_dir = tmp_path / "etc" / "config"
    config_dir.mkdir(parents=True)
    path = config_dir / "models.yaml"
    existing = "models:\n  embed:\n    model: kept\n    url: https://example.invalid/embed\n"
    path.write_text(existing, encoding="utf-8")
    result = _run_entrypoint(
        tmp_path,
        LLM_CHAT_MODEL="model",
        LLM_CHAT_URL="https://example.invalid/chat",
    )
    assert result.returncode == 0, result.stderr
    assert path.read_text(encoding="utf-8") == existing


@pytest.mark.parametrize("provider", ["aoc_signed", "unknown"])
def test_entrypoint_rejects_provider_requiring_full_yaml(tmp_path, provider):
    (tmp_path / "etc" / "config").mkdir(parents=True)
    result = _run_entrypoint(
        tmp_path,
        LLM_CHAT_MODEL="model",
        LLM_CHAT_URL="https://example.invalid/chat",
        LLM_CHAT_PROVIDER=provider,
    )
    assert result.returncode != 0
    assert "provide a complete models.yaml" in result.stderr
    assert not (tmp_path / "etc" / "config" / "models.yaml").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX container entrypoint")
def test_entrypoint_rejects_partial_chat_configuration(tmp_path):
    (tmp_path / "etc" / "config").mkdir(parents=True)
    result = _run_entrypoint(tmp_path, LLM_CHAT_MODEL="model")
    assert result.returncode != 0
    assert "Incomplete chat model configuration" in result.stderr
    assert not (tmp_path / "etc" / "config" / "models.yaml").exists()
