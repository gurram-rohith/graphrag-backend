# backend/utils.py
from pathlib import Path

def is_valuable_file(filepath: str) -> bool:
    path = Path(filepath)
    
    # 1. Directories to skip entirely
    blocked_dirs = {
        'node_modules', 'build', 'dist', '.next', 'coverage',
        '__pycache__', 'venv', 'env', '.env', '.pytest_cache',
        'target', '.gradle', 'bin', 'obj', 'out',
        '.git', '.github', '.vscode', '.idea', '.vs'
    }
    if any(part in blocked_dirs for part in path.parts):
        return False
        
    # 2. Specific massive files to skip
    blocked_files = {
        'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
        'poetry.lock', 'Pipfile.lock', 'Cargo.lock', 'Gemfile.lock',
        '.DS_Store', 'Thumbs.db'
    }
    if path.name in blocked_files:
        return False
        
    # 3. File extensions to skip
    blocked_extensions = {
        '.pyc', '.pyo', '.pyd', '.class', '.jar', '.war',
        '.o', '.so', '.dll', '.exe', '.a', '.lib', '.bin',
        '.map', '.min.js', '.min.css',
        '.css', '.scss', '.sass', '.less', '.styl',
        '.svg', '.png', '.jpg', '.jpeg', '.ico', '.webp', '.gif',
        '.ttf', '.woff', '.woff2', '.eot', '.otf',
        '.zip', '.tar', '.gz', '.pdf', '.log'
    }
    if path.suffix.lower() in blocked_extensions:
        return False
        
    return True