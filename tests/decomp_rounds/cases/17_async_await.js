async function fetchPair(loader, key) {
  const first = await loader(key);
  const second = await loader(`${key}:next`);
  return first.value + second.value;
}

fetchPair(async function loader(name) {
  return { value: name.length };
}, "item");
