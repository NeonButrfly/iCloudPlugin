# Classifier Prompts

## 2026-05-25 - Stratified LightGBM seed from live index

- Issue: [#21](https://github.com/NeonButrfly/iCloudPlugin/issues/21)
- Source prompt: "300 stratified samples + mini teacher review. That gives LightGBM much better signal than 100, while still staying cheap if we later use gpt-5.1-codex-mini for labels. Pure random will mostly pick common stuff: photos/JPGs, boring PDFs, duplicates, and low-value files. Stratified sampling should force coverage. Recommended 300 split: 100 provider-balanced random docs: iCloud/google1/google2, 75 sensitive-keyword docs: medical, legal, financial, insurance, tax, bank, appeal, benefits, 50 low-confidence/unknown from current classifier, 40 category disagreement / ambiguous taxonomy cases, 35 file-type coverage: PDFs, DOCX, spreadsheets, HTML/text, images. use the current index to create the lightbgm training set then install in lightbgm"
- Interpreted requirement: build an index-driven, stratified LightGBM training set from the live corpus, keep a small teacher-review style pass for ambiguous rows, and install the resulting model artifact in the classifier config root.
- Sampling note: exclude archive files such as ZIP, RAR, TAR, and 7Z from the sample pools, then backfill those slots with ordinary document-like files so the queue stays useful for training and heuristics.
- Affected systems: live iCloud index DB, classifier retraining path, LightGBM model artifact/report, operator docs.
