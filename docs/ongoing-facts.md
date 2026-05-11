# Ongoing facts

- **Python & virtual env**: Use Python 3.11 or newer locally. Example:
  ```bash
  uv venv --python 3.11 .venv
  source .venv/bin/activate
  python -m pip install --upgrade pip
  python -m pip install \
    --index-url https://artifactory.aws.amazoncorp.com/api/pypi/global-release-pypi/simple \
    --extra-index-url https://artifactory.aws.amazoncorp.com/api/pypi/global-dev-pypi/simple \
    python-dotenv requests aws vaultpythonsdk
  python -m pip install \
    --index-url https://pypi.org/simple \
    --trusted-host pypi.org --trusted-host files.pythonhosted.org \
    fastmcp
  ```
- **GenAI Agent SDK**: The AI evaluator depends on `aws.addons.adk`. Install the toolkit bundle so the module exists:
  ```bash
  uv pip install \
    --index-url https://artifactory.aws.amazoncorp.com/api/pypi/global-dev-pypi/simple \
    --extra-index-url https://artifactory.aws.amazoncorp.com/api/pypi/global-release-pypi/simple \
    --index-strategy unsafe-best-match \
    aoadevtools
  ```
- **Enable AI**: Set `CORTEX_DISABLE_AI=0` in `.env`, ensure the ADK is installed, and restart Cortex. If you still see `No module named 'aws.addons'`, the toolkit is missing from the venv.
- **Networking**: Jira, object storage, and GenAI endpoints require Amazon VPN/corporate network resolution. Stay on VPN to avoid `NameResolutionError`.
- **Passive logs & uploads**: `config/logging_mode.json` writes to `./data/logs/cortex_activity.log`; create the directory before running. Object storage uploads execute every minute when `upload_schedule.enabled=true`.
