(function attachSemanticPreview(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.SwarmSemanticPreview = api;
})(typeof window === "undefined" ? null : window, function semanticPreviewModel() {
  const maxFileBytes = 512 * 1024;
  const statuses = new Set(["bound", "clarify", "unknown"]);
  const isObject = value => value !== null && typeof value === "object" && !Array.isArray(value);
  const hasText = value => typeof value === "string" && value.trim().length > 0;
  const isSha256 = value => typeof value === "string" && /^[a-f0-9]{64}$/i.test(value);
  const fail = error => ({ error });

  function isEntity(entity) {
    return isObject(entity) && hasText(entity.entity_id) && hasText(entity.entity_kind);
  }

  function parse(text) {
    if (typeof text !== "string" || text.length > maxFileBytes) return fail("证据文件超过 512 KiB。");
    let record;
    try {
      record = JSON.parse(text.replace(/^\uFEFF/, ""));
    } catch {
      return fail("无法解析 JSON。");
    }

    if (record?.kind !== "uavswarm-semantic-preview" || record.schema_version !== "0.1") {
      return fail("需要 schema 0.1 的语义预览 JSON（*.preview.json）。");
    }
    if (record.execution_authorized !== false) {
      return fail("预览文件必须明确声明 execution_authorized=false。");
    }

    const { source, status, objective, bindings, candidates, clarification_question: question, limitations } = record;
    if (!statuses.has(status) || ![objective, record.scene_id, record.map_version, record.reason_code].every(hasText)
      || !Array.isArray(bindings) || !Array.isArray(candidates)
      || !Array.isArray(limitations) || !limitations.every(hasText)) {
      return fail("缺少有效的结论、场景版本、结果列表或限定条件。");
    }
    if (!isObject(source) || ![source.kind, source.evidence_file, source.catalog_file, source.catalog_review_status].every(hasText)
      || typeof source.model_executed !== "boolean" || !isSha256(source.evidence_sha256)
      || !isSha256(source.catalog_content_sha256)) {
      return fail("来源信息不完整，需要原始证据、目录和各自的 SHA-256。");
    }
    if (status === "bound" ? !bindings.length || candidates.length > 0 : bindings.length > 0) {
      return fail("结论与绑定或候选列表不一致。");
    }
    if (status === "clarify" && !hasText(question)) return fail("待澄清记录缺少问题正文。");

    for (const binding of bindings) {
      if (!isEntity(binding) || !hasText(binding.evidence) || !objective.includes(binding.evidence)
        || !hasText(binding.source_reference)) {
        return fail("绑定缺少实体 ID、原文片段或证据出处。");
      }
    }
    for (const candidate of candidates) {
      if (!isEntity(candidate) || (candidate.height_m != null && !Number.isFinite(candidate.height_m))
        || (candidate.evidence != null && (!hasText(candidate.evidence) || !objective.includes(candidate.evidence)))
        || (candidate.source_reference != null && !hasText(candidate.source_reference))) {
        return fail("候选的实体、参考高度或出处格式无效。");
      }
    }
    try {
      const scopeText = record.scope == null ? null : JSON.stringify(record.scope, null, 2);
      return { record, scopeText };
    } catch {
      return fail("限定范围的数据嵌套过深。");
    }
  }

  return { maxFileBytes, parse };
});
