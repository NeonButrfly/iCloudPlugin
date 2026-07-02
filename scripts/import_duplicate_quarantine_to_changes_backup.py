from __future__ import annotations

import json

from icloud_index_service.services.file_mutation_service import (
    import_duplicate_quarantine_to_changes_backup,
)


def main() -> None:
    result = import_duplicate_quarantine_to_changes_backup(actor="operator-script")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
