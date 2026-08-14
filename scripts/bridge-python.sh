#!/usr/bin/env bash
# =============================================================================
# 定位运行 bridge 的 Python 解释器 —— 与具体用户名无关，任何 Linux 用户都能用。
#
# 被 start.sh 与 update.sh 共同 source，保持单一实现：
#   . "${REPO}/scripts/bridge-python.sh"     # 之后即可调用 resolve_bridge_python
#
# 优先级：
#   1. BRIDGE_PYTHON 环境变量（显式指定）
#   2. PATH 上带 aiohttp 的 python3 / python / python3.11 / python3.10
#   3. $HOME 下常见 conda 环境（miniforge3 / miniconda3 / miniforge / miniconda）
#      里带 aiohttp 的 python
#   4. 都没有则回退到 PATH 上的 python3 并返回非 0（调用方可据此给出提示）
#
# aiohttp 是硬依赖，setup.sh / update.sh 安装时通过 pip 一并装到同一个 Python 里。
# =============================================================================

resolve_bridge_python() {
    local c p env_root env_py
    if [ -n "${BRIDGE_PYTHON:-}" ]; then
        echo "${BRIDGE_PYTHON}"
        return 0
    fi
    for c in python3 python python3.11 python3.10; do
        p="$(command -v "$c" 2>/dev/null)" || continue
        if "$p" -c "import aiohttp" >/dev/null 2>&1; then
            echo "$p"
            return 0
        fi
    done
    for env_root in "$HOME"/miniforge3/envs "$HOME"/miniconda3/envs "$HOME"/miniforge/envs "$HOME"/miniconda/envs; do
        [ -d "$env_root" ] || continue
        for env_py in "$env_root"/*/bin/python3; do
            [ -x "$env_py" ] || continue
            if "$env_py" -c "import aiohttp" >/dev/null 2>&1; then
                echo "$env_py"
                return 0
            fi
        done
    done
    echo "$(command -v python3 2>/dev/null || echo python3)"
    return 1
}
