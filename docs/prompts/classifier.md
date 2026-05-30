# Classifier Prompts

## 2026-05-25 - Stratified LightGBM seed from live index

- Issue: [#21](https://github.com/NeonButrfly/iCloudPlugin/issues/21)
- Source prompt: "300 stratified samples + mini teacher review. That gives LightGBM much better signal than 100, while still staying cheap if we later use gpt-5.1-codex-mini for labels. Pure random will mostly pick common stuff: photos/JPGs, boring PDFs, duplicates, and low-value files. Stratified sampling should force coverage. Recommended 300 split: 100 provider-balanced random docs: iCloud/google1/google2, 75 sensitive-keyword docs: medical, legal, financial, insurance, tax, bank, appeal, benefits, 50 low-confidence/unknown from current classifier, 40 category disagreement / ambiguous taxonomy cases, 35 file-type coverage: PDFs, DOCX, spreadsheets, HTML/text, images. use the current index to create the lightbgm training set then install in lightbgm"
- Interpreted requirement: build an index-driven, stratified LightGBM training set from the live corpus, keep a small teacher-review style pass for ambiguous rows, and install the resulting model artifact in the classifier config root.
- Sampling note: exclude archive files such as ZIP, RAR, TAR, and 7Z from the sample pools, then backfill those slots with ordinary document-like files so the queue stays useful for training and heuristics.
- Follow-up prompt: tighten the label map so the heuristic and LightGBM layers agree more often by training on canonical coarse labels instead of the raw fine-grained split.
- Tracking: [#22](https://github.com/NeonButrfly/iCloudPlugin/issues/22)
- Affected systems: live iCloud index DB, classifier retraining path, LightGBM model artifact/report, operator docs.

## 2026-05-26 - External taxonomy ingestion for heuristics and training

- Issue: [#23](https://github.com/NeonButrfly/iCloudPlugin/issues/23)
- Source prompt: "yes pull classification training from any external sources that might have enhancements for training the heuristics and lightbgm. I want the heuristics and lightbgm to be as well trained as possible"
- Interpreted requirement: turn the configured public taxonomy sources into a reusable local alias artifact, feed that artifact into runtime candidate generation and LightGBM feature text, and rebuild the taxonomy router so external document-class labels improve local classification coverage without adding live network dependence to the classifier path.
- External source set: Open Images class descriptions, Google Product Taxonomy, IAB Content Taxonomy 3.1, DocLayNet classes, RVL-CDIP document classes, and receipt-focused static labels derived from CORD and SROIE.
- Affected systems: classifier external taxonomy ingestion, taxonomy router training, runtime candidate selection, LightGBM feature enrichment, operator docs.

## 2026-05-26 - Weak-bucket reviewed examples and alias pruning

- Issue: [#24](https://github.com/NeonButrfly/iCloudPlugin/issues/24)
- Source prompt: "The alias layer is much stronger now, but it is still text-phrase driven. The next accuracy jump will come from adding more reviewed rows for the weaker buckets and pruning any noisy aliases that show up in real disagreement logs. Do this"
- Interpreted requirement: import a checked-in reviewed example corpus for weak raw buckets from the combined reviewed manifest, add an explicit external-taxonomy prune config based on disagreement evidence, rebuild the taxonomy router with those examples, and keep a machine-readable report of noisy vs helpful alias hits.
- Imported weak buckets: `appeal`, `benefits`, `claim`, `contract`, `invoice`, `medical-receipt`, `product-photo`, `receipt`, and `reimbursement-packet`
- Affected systems: external taxonomy prune config, reviewed examples corpus, taxonomy router training, LightGBM retraining inputs, operator docs.

## 2026-05-26 - Taxonomy expansion and 500 sanity-checked examples

- Issue: [#25](https://github.com/NeonButrfly/iCloudPlugin/issues/25)
- Source prompt: "1. pick highest value dataset to wire in 2. expand label set based on taxonomy derived from files and file directories, 3..add 500 more examples having codex do final check on the results to make sure they are sane."
- Interpreted requirement: pick the highest-value public document dataset for the current corpus, expand the raw label set using recurring file and directory patterns from the live mirror corpus, rebuild the example miner so it writes source-backed evidence fields, and regenerate a 500-row sanity-checked example corpus before retraining.
- Primary dataset choice: `rvl_cdip_static` remains the main broad document-training source because it aligns with the vault's mix of forms, invoices, letters, statements, manuals, and generic office documents.
- Taxonomy expansion added directory-driven raw labels such as `return-summary`, `consumer-report`, `utility-bill`, and `hotel-folio` alongside finer finance and insurance labels.
- Evidence note: mined examples now keep matched query terms, teacher evidence, source path, extension, and MIME type so the taxonomy router and LightGBM feature text can reuse the same provenance-rich rows.
- Runtime note: local desktop runs now default classifier config and output paths back into the repo instead of the container-style `/config` and `/output` roots, which avoids writing training artifacts outside the workspace during Codex runs.
- Affected systems: classifier runtime settings, live-index example miner, reviewed example import, taxonomy router training, LightGBM runtime training rows, config artifacts, operator docs.

## 2026-05-26 - Retrieval-first index and autonomous shadow loop

- Issue: [#26](https://github.com/NeonButrfly/iCloudPlugin/issues/26)
- Source prompt: "iterate use the classifier as ranking/context only, build stronger entity/topic extraction into the index and Obsidian vault, then improve the live heuristic/shadow loop so the model learns continuously from real usage."
- Interpreted requirement: keep the classifier as a retrieval aid rather than the source of truth, persist entity/topic/retrieval evidence for each classified file, expose that evidence through the index and Obsidian vault, and make the existing shadow worker learn continuously in bounded batches from approved live comparisons.
- Retrieval note: search now needs to find files by semantic clues even when their folder is wrong, so entity summaries, topic summaries, and retrieval terms must survive from classification into both the database index and the vault note layer.
- Self-learning note: the live shadow loop should respect runtime gating, update heuristic disagreement rules only when enabled, and retrain LightGBM only after enough new teacher-approved rows have accumulated.
- Affected systems: classifier note generation, LightGBM feature text, shadow queue processing, index search ranking, classification state persistence, operator docs.

## 2026-05-26 - OCR-first image and scanned-PDF classifier path

- Issue: [#3](https://github.com/NeonButrfly/iCloudPlugin/issues/3)
- Source prompt: "image recognition/ocr/image parsing in the pipeline" and later "is there a faster easier ocr / image recognition type package other than qwen that we can cheaply insert in the pipeline. ok go"
- Interpreted requirement: stop relying on Qwen vision as the first stop for image-heavy files, add a cheap OCR-first evidence layer for still images and scanned PDFs, and keep Qwen as the fallback when OCR is still too sparse to support the normal document classifier path.
- OCR note: the runtime now attempts optional PaddleOCR before Tesseract for still images, then routes image files with strong OCR text through the normal heuristic plus LightGBM document path instead of forcing them into the vision-only path.
- PDF note: when native PDF extraction is too sparse, scanned PDFs now fall back to page-render OCR via `pdftoppm` plus the same shared image OCR stack.
- Affected systems: index extraction, scanned PDF handling, live classifier image routing, Docker/runtime env defaults, operator docs.

## 2026-05-26 - PaddleOCR runtime install and OCR-quality feature text

- Issue: [#27](https://github.com/NeonButrfly/iCloudPlugin/issues/27)
- Source prompt: "1 and 2" after the OCR-first rollout, referring to "bake PaddleOCR into the runtime image and smoke-test it on a real scanned batch from the mirror" plus "add extraction-quality fields into LightGBM feature text so weak OCR can explicitly lower confidence instead of only shortening the text"
- Interpreted requirement: make the fast OCR engine part of the normal classifier container instead of an optional undeployed dependency, preserve OCR/extraction quality metadata across live classification and retraining rows, and verify the path on a small real mirror sample.
- Runtime note: the shipped classifier image should install `paddlepaddle` before `paddleocr` so still-image OCR uses the faster path whenever it is enabled.
- Training note: OCR evidence fields such as engine, quality, and character count must survive into LightGBM feature text, shadow comparisons, and runtime-manifest training rows so the model can learn that sparse OCR is a weaker signal than clean extracted text.
- Affected systems: classifier Docker image, live hybrid feature builder, shadow queue/training rows, operator docs.

## 2026-05-27 - Readiness bootstrap and unified self-training loop

- Issue: [#28](https://github.com/NeonButrfly/iCloudPlugin/issues/28)
- Source prompt: "rebuild/fix classifier readiness until /readiness shows real_ingestion_allowed=true" and "Make sure all classifier heuristics, lightbgm, qwen are part self-training feedback loop"
- Interpreted requirement: remove the live readiness catch-22 by letting the classifier bootstrap from the bundled reviewed corpus and bundled model artifacts, keep writable runtime artifacts outside the read-only `/config` mount, and make the autonomous feedback loop treat heuristics, LightGBM, and Qwen as one connected learning system.
- Bootstrap note: the classifier role should copy missing runtime artifacts from `/app/config` into `/output/_artifacts` so live retrains and threshold updates stay writable even when `/config` is a read-only host mount.
- Readiness note: reviewed bootstrap rows from `examples.jsonl` and `corrections.jsonl` now count toward teacher-approved coverage alongside Qwen shadow comparisons, so `/readiness` can turn green before the first large real-folder submission wave.
- Feedback-loop note: heuristics should keep learning from disagreement rules, LightGBM should retrain from the merged approved corpus, and Qwen should stay the shadow teacher through a dedicated single-runner `shadow-worker` service rather than an in-process API thread. If Qwen returns malformed non-JSON output during a shadow review, record a `shadow-error` row and drain that queue item instead of wedging the loop.
- Affected systems: classifier runtime path resolution, readiness gating, LightGBM bootstrap/retrain path, shadow-worker deployment shape, operator docs.

## 2026-05-27 - Direct source-path ingestion instead of staged real-folder uploads

- Issue: [#29](https://github.com/NeonButrfly/iCloudPlugin/issues/29)
- Source prompt: "yeah I dont think we can keep failures, staged files should be deleted immediately or maybe we should just save massive amounts of disk space, just feed the source file location into the classifier and have it read/process the file right from the source"
- Interpreted requirement: stop duplicating mirrored files into the classifier host's upload staging area during normal real-folder ingestion, add a safe source-path API that reads shared mirror files directly from a read-only mount, and delete temporary staged uploads immediately after ad hoc classifications complete.
- Runtime note: the classification worker should now send mirror-relative source paths to the classifier API, while the classifier API resolves those paths against a dedicated read-only shared-source mount such as `/source`.
- Cleanup note: one-off upload requests still stage a temp file, but that temp copy should be removed right after classification returns instead of accumulating under `/input/api`.
- Affected systems: classification submission client, classifier API endpoints, classifier role compose mounts, operator docs.

## 2026-05-29 - Repair existing source links and feed manual Obsidian edits back into training

- Issues: [#41](https://github.com/NeonButrfly/iCloudPlugin/issues/41), [#42](https://github.com/NeonButrfly/iCloudPlugin/issues/42)
- Source prompts: "fix existing notes or start over", then "repair pass", then "ok also have the classifier update on anything I create manually in obsidian"
- Interpreted requirement: repair already-generated classifier notes in place so older Windows users stop seeing Linux-style mirror links, and treat user-created or manually edited Obsidian notes as reviewed feedback that can strengthen the classifier without rerunning the original file through the live classification path.
- Repair note: the vault reconciliation layer now owns `source_link`, `attachment`, and the rendered `## Original File` section strongly enough to rewrite stale mirror links in place while leaving the rest of each note alone.
- Manual-feedback note: the shadow worker now fingerprints manual notes outside generated classifier folders, exports changed notes into a dedicated feedback jsonl artifact, and includes those rows in readiness/bootstrap plus LightGBM retraining inputs.
- Affected systems: vault reconciliation, classifier note metadata, shadow worker, readiness/bootstrap accounting, LightGBM retraining inputs, operator docs.

## 2026-05-29 - Treat Obsidian folders and manual moves as classifier training

- Issue: [#43](https://github.com/NeonButrfly/iCloudPlugin/issues/43)
- Source prompt: "ok so any changes I make in obsidian like adding categories (folders) and moving notes to those folders would act like training for heuristics, lightbgm?" followed by "1 & 2 & 3"
- Interpreted requirement: let vault folder organization become classifier supervision by treating mapped folder paths as weak labels, detecting manual relocations of generated classifier notes as stronger corrections, and introducing an explicit folder-to-canonical-label mapping file for human-friendly vault categories.
- Folder-training note: manual notes without explicit `primary_label` frontmatter can now inherit a weak classifier label from their folder path when that path maps to a known category or to an explicit override in `config/vault-folder-labels.json`.
- Move-correction note: when a classifier-generated note is manually relocated into a different category folder, the feedback export should key the correction to the original source file and preserve the old label so heuristics and LightGBM can learn from the move.
- Targeted-reclassify note: strong manual corrections now also queue a bounded backend reclassification for the matching source file when the note edit is newer than the last completed classification; weak folder hints remain training-only.
- Exact-override note: when the same source file is classified again, an exact strong reviewed correction for that source path should override the stale model guess immediately so the rewritten note follows the human move instead of waiting for broader retraining to catch up.
- Heuristic-learning note: generated notes should preserve the original source parser and heuristic hint in frontmatter so later manual moves can feed those values back into the training loop; repeated strong human corrections for the same parser plus heuristic-hint pair should teach the runtime to force inline LLM instead of trusting that fast path.
- Bootstrap-noise note: generated-note history rows where `correct_label` already matched `old_label` should not count as reviewed corrections during bootstrap import, otherwise stale no-op rewrites can inflate readiness and teach the heuristic gate from noise instead of real user corrections.
- Operator-control note: bounded cloudsync classification runs can now set
  `CLASSIFICATION_BACKFILL_ENABLED=false` or use
  `run_targeted_classification_batch.sh --targeted-feedback-only` to process
  strong manual corrections without seeding the broader backfill queue.
- Affected systems: manual note feedback export, shadow worker, classifier readiness/bootstrap inputs, operator docs, classifier config.
