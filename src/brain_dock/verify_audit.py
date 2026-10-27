"""`python -m brain_dock.verify_audit`: check the audit log's hash chain. The code is in
brain_dock.core.agents.audit."""

import sys

from brain_dock.core.agents.audit import main

if __name__ == "__main__":
    sys.exit(main())
