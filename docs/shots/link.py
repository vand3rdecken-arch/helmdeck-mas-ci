"""Junction app/node_modules -> C:\\hd\\app\\node_modules so tsc/expo resolve deps
in this worktree (the worktree never gets its own install)."""
import _winapi
import os

DST = r"C:\Users\Tien Duy Vo\Downloads\helmdeck-worktrees\1mmjd8p4\req-fix-dashboard-zu-ueberfuellt\app\node_modules"
SRC = r"C:\hd\app\node_modules"

if os.path.exists(DST):
    print("already linked")
else:
    _winapi.CreateJunction(SRC, DST)
    print("created")
