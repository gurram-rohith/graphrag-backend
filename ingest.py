import git
import os
import shutil
import stat
import tempfile
from pathlib import Path

# Supported logic file extensions (case-insensitive)
ALLOWED_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", 
    ".java", ".c", ".cpp", ".h", ".hpp", 
    ".go", ".rs"
}

def force_remove_readonly(func, path, excinfo):
    """Overrides Windows read-only file permissions (like .git folders) during deletion."""
    os.chmod(path, stat.S_IWRITE)
    func(path)

def is_ignored(path: Path) -> bool:
    """Universal filter to skip build artifacts, caches, lockfiles, and IDE noise."""
    # 1. Ignored directories
    ignored_folders = {
        '.git', '.github', '.vscode', '.idea', '.vs',
        'node_modules', 'build', 'dist', '.next', 'coverage',
        '__pycache__', 'venv', 'env', '.env', '.pytest_cache',
        'target', '.gradle', 'bin', 'obj', 'out', '.meteor'
    }
    if any(part in ignored_folders for part in path.parts):
        return True

    # 2. Ignored lockfiles & OS metadata
    ignored_files = {
        'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml',
        'poetry.lock', 'Pipfile.lock', 'Cargo.lock', 'Gemfile.lock',
        '.DS_Store', 'Thumbs.db'
    }
    if path.name in ignored_files:
        return True

    # 3. Ignored minified or source map files
    if path.name.endswith('.min.js') or path.name.endswith('.min.css') or path.name.endswith('.map'):
        return True

    return False

def ingest_repository(repo_url):
    """
    Clones a repo into a unique temporary directory, applies universal 
    file filtering, and enforces a 200-file security hard-cap.
    """
    temp_dir_path = tempfile.mkdtemp()
    temp_dir = Path(temp_dir_path)
    
    print(f"--- Cloning: {repo_url} into isolated folder: {temp_dir} ---")
    
    try:
        # 1. Clone the repository
        git.Repo.clone_from(repo_url, temp_dir,depth=1)
        print("Successfully cloned.")
        
        # 2. Recursive Discovery & Filtering
        discovered_files = []
        for path in temp_dir.rglob('*'):
            if path.is_file() and not is_ignored(path) and path.suffix.lower() in ALLOWED_EXTENSIONS:
                discovered_files.append(str(path))
                
        print(f"Total logic files found: {len(discovered_files)}")
        
        # 3. Hard Cap Security Check
        if len(discovered_files) > 200:
            raise ValueError(
                f"Repository too large ({len(discovered_files)} logic files detected). "
                f"Limit is 200 files."
            )
            
        return discovered_files, str(temp_dir)

    except Exception as e:
        # GUARANTEED CLEANUP: Wipe temp directory immediately if clone or size check fails
        if os.path.exists(temp_dir_path):
            shutil.rmtree(temp_dir_path, onerror=force_remove_readonly)
            print(f"DEBUG: Wiped temporary folder on error: {temp_dir_path}")
        raise e