# Snow Gloves OS Constitution

## Principles

1. **Spec before code**
   - No implementation starts without approved `spec.md`, `plan.md`, and `tasks.md`.

2. **Tenant isolation first**
   - Every connector, embedding index, policy graph, and workflow is tenant-scoped.

3. **Interpretation before automation**
   - Raw events must pass through interpretation (context + confidence + policy) before execution.

4. **Approval-gated risk**
   - Financial, legal, HR, and irreversible operations require explicit approval paths.

5. **Auditability by default**
   - Every decision and action produces traceable logs and links back to source context.

6. **Wiki as human control surface**
   - The wiki is the operator-facing truth surface; machine memory and human memory stay synced.

7. **Portable domain packs**
   - Vertical templates (hospitality, agency, ecom, healthcare, etc.) must reuse the same core architecture.
