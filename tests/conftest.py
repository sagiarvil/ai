import sys
from pathlib import Path

# Proje kök dizinini sys.path'in en başına ekle
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
