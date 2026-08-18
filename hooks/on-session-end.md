# Session End: Auto-Generate PICKUP.md

Before ending any session on a SACAS-managed project, follow this procedure:

## Procedure

1. **Update STATE.md Checkboxes**: Ensure all tasks and verification items completed during the session are marked as checked `[x]` in `Structure/tasks/current/STATE.md`.
2. **Run Refresh**: Run the following command to update file hashes and generate/update `PICKUP.md` based on the new checklist state:
   ```bash
   sacas refresh
   ```
3. **Verify Handoff**: Verify that `Structure/tasks/current/PICKUP.md` exists and contains the correct list of completed, pending, and priority tasks.
