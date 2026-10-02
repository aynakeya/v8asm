function literalArrayContent() {
  const first = 7;
  const second = 8;
  return [first, second, "r0", "r1", "r2", "ACCU", "r0.r1", "\"r0\"", "$r0", "r0Tail"];
}

function literalPropertyContent() {
  const holder = { r0: 7, r1: 8 };
  const key = "r1";
  return [holder[key], holder.r0, { r0: key }];
}

function literalArgumentContent() {
  const first = "prefix";
  function combine(left, right) { return left + right; }
  return combine(first, "r0 r1 r2");
}

function literalLookupContent() {
  const holder = { r0: 7, r1: 8 };
  const key = "r1";
  return holder[key];
}

function literalReturnContent() {
  let value = 7;
  return "r0";
}

globalThis.__semantic_result = [
  literalArrayContent(), literalPropertyContent(), literalArgumentContent(), literalReturnContent(),
  literalLookupContent(),
];
