from pathlib import Path

code = """import math
_COLORS = ["#4e79a7","#f28e2b","#e15759","#76b7b2"]
def hello():
    return 42
"""

Path('presentation/render/svg_renderer.py').write_text(code)
print('done')
