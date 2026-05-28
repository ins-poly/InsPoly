from __future__ import annotations

import sys

from app import case_reviewer as _case_reviewer


if __name__ == "__main__":
    _case_reviewer.main()
else:
    sys.modules[__name__] = _case_reviewer
