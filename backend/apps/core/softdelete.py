"""Soft delete: rows are flagged as deleted instead of being removed (design doc, section 4.5).

How it works in this project:
- A model with an is_deleted field uses a manager that HIDES deleted rows as `objects`, so every ordinary lookup
  (login, the public endpoint, lists, limits, ...) ignores them without any extra code.
- `all_objects` is a plain manager that also returns deleted rows. Only the few places that must see them use it:
  the admin, restoring, and the purge job.
- Deleted rows stay for SOFT_DELETE_RETENTION_DAYS (30) and are then removed for good by `manage.py purge_deleted`.
"""


class SoftDeleteManagerMixin:
    """Add in front of a manager class to hide rows where is_deleted is true."""

    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)