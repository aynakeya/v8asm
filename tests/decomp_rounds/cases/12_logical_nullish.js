function choose(a, b, fallback) {
  const picked = a ?? fallback;
  if (picked && b) {
    return picked.value || "missing";
  }
  return "none";
}
choose({ value: "" }, true, { value: "fallback" });
