# Codex / coding agent instructions

This file is the **canonical repository-level instruction file** for coding agents. Read [README.md](README.md) first for the complete project overview, installation, usage, output schema, and history. The user-facing documentation is primarily in Korean; prefer Korean for explanations and new docs. `AGENT.md` is a compatibility pointer to this file.

## Project mission and current reality

- Convert scanned traditional vertical Chinese-character Korean genealogy (`족보`) pages into structured, human-reviewed people, source occurrences, and parent/child edges. The source edition currently being reviewed was published in **1987**; future editions may be linked to the same people.
- Runtime pipeline: **OpenCV + PaddleOCR + deterministic Python rules + PySide6 desktop review UI**. No LLM is required or desired in the OCR/extraction pipeline.
- A database has **not** been implemented. The persisted workflow uses JSON/CSV and `person_registry.json`. Do not describe the future DB schema in README §8.5 as production code.
- `scan/` contains many scanned pages. Prefer **one-page tests** with `scan/001.jpg`; do not process the entire corpus or publish additional scanned/person data without explicit need.

## Where to look first

| Task | Entry point |
|---|---|
| OCR CLI, layout, name/relationship candidates, engine optimizations | `ocr/jokbo_ocr.py` |
| Page JSON persistence and legacy OCR loading | `ocr/storage.py` |
| Desktop review workflow and overlays | `review/desktop_review.py` |
| Review state and JSON/CSV exports | `review/core.py` |
| Cross-page continuations and recovered candidates | `review/extensions.py` |
| Person-record OCR draft and evidence bounding boxes | `review/person_info.py` |
| Stable `person_uid`, source occurrences, raw/reviewed records | `review/data_model.py` |
| Tests and regression examples | `tests/` |
| Setup, CLI, data formats, review steps, user workflow | README §§3–12, 17–19 |

Run package entry points with `python -m ocr.jokbo_ocr` and `python -m review.desktop_review` from the repository root.

## Non-negotiable domain and data invariants

1. **Raw OCR is evidence, not verified truth.** Preserve original image references, unmodified name OCR, full record OCR, token/column bbox, confidence and sources. Keep `raw_data` separate from `reviewed_data`. Automated extraction populates **unverified drafts** and must not overwrite human edits.
2. **Name markers:** leading `子` and `女` represent son/daughter and must be removed from the reviewed name while preserving the **exact raw OCR string** and the marker/sex field. Do not strip arbitrary Chinese characters from a name.
3. **Lineage:** a parent has 0..N children. Store each confirmed pair as an edge, never a single child field. Use stable `parent_person_uid` and `child_person_uid` for export/DB linkage; the page-local `person_id` is not a global key. Keep cycle checks and duplicate detection.
4. **Page geometry is a heuristic:** OCR text runs vertically; columns read **right-to-left**. The eldest son may be below the father at a similar x, later sons appear to the left, and daughters can appear to the right. The geometry suggests candidates; **it does not prove kinship**. `親族也` is a phrase, not a person.
5. **Multiple partners:** a person may have multiple wives and/or concubines. Preserve an array of separately typed partner entries; do not collapse it into a single authoritative string.
6. **Stable identity vs source:** `PER_<UUID>` remains constant across revised editions; publication year, printed page, scan page, row, right-to-left column, ordinal, and bbox are stored separately in `source_occurrences`. Never derive the permanent UID from edition/year/page/column or merge namesakes automatically.
7. **Review status:** preserve `needs_review`, `confirmed`, `rejected` semantics. OCR confidence is **not** calibrated probability.
8. **Source provenance:** OCR field evidence must retain original-image coordinate bbox. A crop/ROI can have an offset; ensure coordinate transforms are correct and test both offset and no-offset paths.

## Review UI expectations

- Reviewer can click people directly in the scan; labels `1, 2, 3...` must match relationship list numbers for that page.
- Relationship creation is **1:N**: select parent once, add multiple children; allow cancel/undo, show pre-existing confirmed/unreviewed edges. Connect parent bbox **bottom-center** to child bbox **top-center**, avoiding text overlap.
- Use visibly distinct overlay colors **plus clear status labels**; do not rely on nearly identical shades of blue/green/orange.
- Scanned page stays visible while the independent right-hand panel scrolls. Keep zoom/pan responsive and preserve image coordinates across selection and page changes.
- Clicking an individual or choosing a birth/death/office/partner/burial/name field should expose the **correct OCR evidence bbox**. Use real source columns when available, and make missing evidence explicit rather than fabricating a precise bbox.
- A page with **no selected person** must render normally; keep a first-load desktop regression test.
- Maintain existing `review_state.json` compatibility. Protect reviewer edits and avoid resetting UUID mappings or re-generating registry data during a cosmetic UI change.

## Suggested workflow for every task

1. Read **README.md §§17–19** and this file; inspect `git status` and the current head before editing. **Preserve existing user modifications.**
2. Reproduce on `scan/001.jpg` or a small synthetic fixture. Do not run OCR on the whole `scan/` tree merely to test a UI tweak.
3. Edit only relevant modules; add a regression test for each bug, including first-load/no-selection behavior and geometry offsets when appropriate.
4. Run:
   ```bash
   python -m unittest discover -s tests -v
   python -m compileall -q ocr review tests
   ```
   For UI edits, manually verify in the desktop app if a display environment is available. Never claim actual GUI interaction or PaddleOCR inference testing when it was not performed.
5. Verify input vs output and no data loss. Test on an isolated OCR output directory; `review_state.json` and `person_registry.json` are valuable state. **The repository already tracks a root `person_registry.json`** — do not accidentally commit incidental changes to it. Review `git status` and staged diffs before any push.
6. Update the **single consolidated README.md** (especially workflow/code map and change history) for meaningful behavior changes; do not add versioned README clones. Follow **Development history** below to decide whether a WORKLOG entry is warranted.
7. If the user requests GitHub updates, commit only intended files and push after tests; do not force-push, overwrite others' work, or claim success before verifying the remote branch/commit. Report precise tests and unverified areas. Include the resulting commit SHA in the worklog when practical; see the guidance below.

## Development history

The **Git history is the source of truth for what changed**; [docs/WORKLOG.md](docs/WORKLOG.md) explains **why decisions were made**, failed approaches, evidence, and remaining risks. README.md describes **how the project currently works**, not a chronological diary.

- Before architectural changes, nontrivial bug investigations, data-model changes, or OCR/performance tuning, consult relevant entries in `docs/WORKLOG.md`. For routine edits, do not read the entire growing log just to begin.
- After **significant** work, append a dated entry: problem/context, root cause or hypothesis, approach and trade-offs, tests and measurements (with environment/conditions), unresolved limitations, and related Git commit SHA or link.
- Record rejected approaches and their reasons when they could prevent repeated investigation. Do not claim an unrun test passed; distinguish unit tests, actual OCR inference, and manual desktop UI testing.
- Do **not** add a worklog entry for every typo, formatting fix, or trivial change already clear from the commit message. Keep entries concise and searchable; use headings and paths/symbols.
- Preserve earlier entries as historical records. If a conclusion becomes outdated, add a dated correction or superseding entry rather than silently rewriting or deleting history.
- Avoid duplicate release notes: user-facing features and current instructions go in `README.md`; detailed technical rationale belongs in `docs/WORKLOG.md`; concise change summaries belong in Git commit messages.
- When a commit SHA is not yet known because the worklog is part of the same commit, link to the related commit in a **subsequent** entry or use a stable reference such as `same commit as this entry`. Do not amend or make an extra commit solely to fill in the SHA.
- Never log private family/person data, secrets, or large raw OCR excerpts unnecessarily. The tracked `person_registry.json` must not be modified as a side effect of documenting work.

## Fast commands

```bash
# From the repository root; see README §3 for environment setup
python -m unittest discover -s tests -v
python -m ocr.jokbo_ocr --help

# OCR only after installing PaddleOCR; inspect a single sample
python -m ocr.jokbo_ocr ./scan/001.jpg --rows 6 --output output/

# Review OCR output containing */page.json (legacy ocr_results.json also supported)
python -m review.desktop_review output/
```

## Open questions / safe defaults

- Text, character, and column OCR segmentation can miss characters and mix adjacent people's biographies. Do not silently treat keywords or name strings as verified; surface evidence and review status.
- User preferences: avoid LLM dependency, favor efficient OCR inference and responsive local UI, retain review history and provenance, use the existing **main** branch workflow, and communicate technical changes in Korean.
- See README §13 for oneDNN/PIR compatibility; keep a desktop first-load test.
- New OCR evidence is stored once per page in `<stem>/page.json` (`schema_version: 1`). Root aggregate OCR JSON and old per-page JSON are read-only compatibility inputs; prefer new page files when both exist. Do not delete or auto-migrate reviewer state or legacy evidence.
