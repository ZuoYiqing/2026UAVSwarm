(function attachSemanticLab(root, factory) {
  const preview = root?.SwarmSemanticPreview
    ?? (typeof module === "object" && module.exports ? require("./semantic-preview.js") : null);
  const api = factory(preview);
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.SwarmSemanticLab = api;
})(typeof window === "undefined" ? null : window, function semanticLabApi(previewModel) {
  const endpoint = "http://127.0.0.1:18118/lab/semantic-preview";
  const service = "uavswarm_lab_semantic_preview";
  const timeoutMs = 25000;
  const hasText = value => typeof value === "string" && value.trim().length > 0;

  function failure(reasonCode, message, httpStatus = null) {
    return Object.assign(new Error(message), { reasonCode, httpStatus });
  }

  async function request(suffix, body) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(endpoint + suffix, {
        method: body === undefined ? "GET" : "POST",
        headers: body === undefined ? {} : { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
        credentials: "omit",
        redirect: "error",
        cache: "no-store",
      });
      const text = await response.text();
      if (text.length > previewModel.maxFileBytes * 4) {
        throw failure("LAB_RESPONSE_INVALID", "Lab 响应超过预览大小限制。", response.status);
      }
      let payload;
      try {
        payload = JSON.parse(text);
      } catch {
        throw failure("LAB_RESPONSE_INVALID", "Lab 返回的 JSON 无法解析。", response.status);
      }
      if (!response.ok) {
        const labels = {
          422: "输入超出当前限定楼栋题的范围。",
          429: "Lab 正在处理另一条请求，请稍后手动重试。",
          503: "本地模型不可用。",
          504: "本地模型响应超时。",
          502: "模型输出被算法拒绝。",
        };
        throw failure(hasText(payload?.error?.reason_code) ? payload.error.reason_code : "LAB_HTTP_ERROR",
          labels[response.status] ?? "Lab 请求失败。", response.status);
      }
      if (payload?.service !== service || payload.api_version !== "0.1" || payload.execution_authorized !== false) {
        throw failure("LAB_RESPONSE_INVALID", "Lab 响应必须标明 0.1 版本和无执行授权。");
      }
      return payload;
    } catch (error) {
      if (error.reasonCode) throw error;
      throw controller.signal.aborted
        ? failure("LAB_TIMEOUT", "等待 Lab 响应超过 25 秒。")
        : failure("LAB_UNREACHABLE", "无法读取本地 Lab，请检查服务和主控台来源地址。");
    } finally {
      clearTimeout(timer);
    }
  }

  async function health() {
    const payload = await request("/health");
    if (payload.status !== "ready" || payload.model_status !== "not_checked") {
      throw failure("LAB_RESPONSE_INVALID", "Lab 健康响应缺少模型未检查标记。");
    }
    return payload;
  }

  async function infer(objective) {
    if (!hasText(objective) || objective.length > 160) {
      throw failure("INVALID_PREVIEW_OBJECTIVE", "请输入 1–160 字的限定楼栋题。");
    }
    const payload = await request("", { objective });
    if (payload.mode !== "live" || !Number.isSafeInteger(payload.elapsed_ms) || payload.elapsed_ms < 0
      || !hasText(payload.evidence_json) || payload.evidence_json.length > previewModel.maxFileBytes) {
      throw failure("LAB_RESPONSE_INVALID", "Lab 实时响应缺少有效的耗时或原始证据。");
    }
    const preview = previewModel.parse(JSON.stringify(payload.preview));
    if (preview.error) throw failure("LAB_RESPONSE_INVALID", preview.error);
    const { record } = preview;
    if (record.objective !== objective || record.source.model_executed !== true
      || !hasText(record.scope?.model_alias) || !hasText(record.scope?.model_response)) {
      throw failure("LAB_RESPONSE_INVALID", "本次原话或模型原答与预览契约不一致。");
    }
    const bytes = new TextEncoder().encode(payload.evidence_json);
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    const hash = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
    if (hash !== record.source.evidence_sha256.toLowerCase()) {
      throw failure("LAB_EVIDENCE_MISMATCH", "原始证据的 SHA-256 与预览标注不符。");
    }
    let evidence;
    try {
      evidence = JSON.parse(payload.evidence_json);
    } catch {
      throw failure("LAB_EVIDENCE_MISMATCH", "原始证据的 JSON 无法解析。");
    }
    if (evidence?.execution_authorized !== false || evidence.objective !== objective
      || evidence.status !== record.status || evidence.model_trace?.model_raw_response !== record.scope.model_response) {
      throw failure("LAB_EVIDENCE_MISMATCH", "原始证据与本次原话、模型原答或算法结论不一致。");
    }
    return { ...preview, elapsedMs: payload.elapsed_ms, evidenceText: payload.evidence_json };
  }

  return { endpoint, health, infer };
});
