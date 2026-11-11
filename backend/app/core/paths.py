from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
# Docker puts backend files under /app; a source checkout keeps them in backend/.
PROJECT_ROOT = APP_ROOT.parent if (APP_ROOT.parent / 'frontend').is_dir() else APP_ROOT.parent.parent
FRONTEND_ROOT = PROJECT_ROOT / 'frontend'
DATA_ROOT = PROJECT_ROOT / 'data'
REPORTS_ROOT = PROJECT_ROOT / 'reports'
