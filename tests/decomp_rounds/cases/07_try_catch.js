function safeJson(s) {
  try {
    return JSON.parse(s);
  } catch (e) {
    return { ok: false };
  }
}
safeJson('{"a":1}');
