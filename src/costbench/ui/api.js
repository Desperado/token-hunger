/* costbench UI ↔ backend.
 *
 * Thin fetch wrappers over the JSON API served by `costbench serve`
 * (src/costbench/server.py). Every number the UI renders comes from here:
 *   bootstrap() — default task + cases, live pricing models, fingerprints.
 *   estimate()  — keyless cost estimate for the selected targets.
 *   run()       — stream per-case progress, then return the leaderboard.
 */
(function () {
  async function jpost(path, body) {
    const resp = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const data = await resp.json().catch(() => ({ error: "bad response" }));
    if (!resp.ok || data.error) throw new Error(data.error || `HTTP ${resp.status}`);
    return data;
  }

  async function jget(path) {
    const resp = await fetch(path);
    const data = await resp.json().catch(() => ({ error: "bad response" }));
    if (!resp.ok || data.error) throw new Error(data.error || `HTTP ${resp.status}`);
    return data;
  }

  async function runStream(payload, onEvent) {
    const resp = await fetch("/api/run-stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {}),
    });
    if (!resp.ok) {
      const data = await resp.json().catch(() => ({ error: `HTTP ${resp.status}` }));
      throw new Error(data.error || `HTTP ${resp.status}`);
    }
    if (!resp.body) throw new Error("This browser cannot read streamed run progress.");

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        if (event.type === "error") throw new Error(event.error || "Run failed");
        onEvent(event);
      }
      if (done) break;
    }
    if (buffer.trim()) {
      const event = JSON.parse(buffer);
      if (event.type === "error") throw new Error(event.error || "Run failed");
      onEvent(event);
    }
  }

  window.CostbenchAPI = {
    bootstrap: () => jget("/api/bootstrap"),
    estimate: (payload) => jpost("/api/estimate", payload),
    run: (payload, onEvent) => runStream(payload, onEvent),
    suggestCases: (payload) => jpost("/api/suggest-cases", payload),
  };
})();
