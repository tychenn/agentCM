"""Load local DeepSeek settings without executing shell expressions."""
import os
from pathlib import Path


def load_env(path=None):
    path = Path(path) if path is not None else Path(__file__).resolve().parents[2] / '.env'
    if not path.is_file():
        return
    allowed = {'DEEPSEEK_API_KEY', 'DEEPSEEK_MODEL', 'DEEPSEEK_BASE_URL'}
    for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        key, separator, value = line.partition('=')
        key, value = key.strip(), value.strip()
        if not separator:
            raise ValueError(f'.env 第 {number} 行缺少等号')
        if key not in allowed:
            continue
        if value.startswith(('"', "'")):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f'.env 第 {number} 行引号不匹配')
            value = value[1:-1]
        os.environ.setdefault(key, value)
