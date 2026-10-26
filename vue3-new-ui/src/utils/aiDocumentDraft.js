const documentFeatures = new Set([
  "outpatient_note", "admission_note", "progress_note", "discharge_summary", "imaging_report_assistant",
]);

export function isDocumentDraft(featureKey) {
  return documentFeatures.has(featureKey);
}

export function documentSections(result) {
  return (Array.isArray(result?.sections) ? result.sections : []).flatMap((section, index) => {
    if (typeof section?.content !== "string" || !section.content.trim()) return [];
    return [{ index, title: typeof section.title === "string" ? section.title : "", content: section.content }];
  });
}

export function documentReviewNotes(result) {
  return [...new Set([...(result?.warnings || []), ...(result?.missing_data || [])]
    .filter(value => typeof value === "string" && value.trim()))];
}

export function documentBody(result, selectedIndices = []) {
  const selection = new Set(selectedIndices.filter(Number.isInteger));
  return documentSections(result).filter(section => selection.has(section.index))
    .map(section => [section.title, section.content].filter(value => value !== "").join("\n"))
    .join("\n\n");
}
