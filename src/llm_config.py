"""Read deployment-specific LLM settings without embedding server addresses."""
import json
import os
from pathlib import Path
from paths import ROOT


def llm_settings(saved=None):
    path = Path(os.environ.get('SWLAB_CONFIG', str(ROOT / 'settings.local.json')))
    local = {}
    if path.is_file():
        try:
            config = json.loads(path.read_text(encoding='utf-8-sig'))
            local = config['llm']
            if not isinstance(local, dict):
                raise ValueError('llm must be an object')
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ValueError(f'LLM 로컬 설정 파일을 확인하세요: {path}') from error
    result = {}
    for key, variable in (('url', 'SWLAB_LLM_URL'), ('model', 'SWLAB_LLM_MODEL'),
                          ('api_key', 'SWLAB_LLM_API_KEY')):
        value = os.environ.get(variable)
        if value is None and saved is not None and key != 'api_key':
            value = saved.value('llm_' + key, None)
        if value is None:
            value = local.get(key, '')
        if not isinstance(value, str):
            raise ValueError(f'LLM {key} 설정은 문자열이어야 합니다.')
        result[key] = value.strip()
    return result
