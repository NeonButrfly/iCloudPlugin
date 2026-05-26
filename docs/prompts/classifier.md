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
