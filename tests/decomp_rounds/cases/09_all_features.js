function allFeatures(rows, user, code, text) {
  let total = 0;

  for (const row of rows) {
    for (const v of row) {
      if (v > 0) total += v;
    }
  }

  const upper = user.name.toUpperCase();

  let label;
  switch (code) {
    case 1:
      label = 'one';
      break;
    case 2:
      label = 'two';
      break;
    default:
      label = 'other';
  }

  function makeAdder(base) {
    return function add(x) {
      return base + x;
    };
  }

  const add3 = makeAdder(3);
  const bumped = add3(total);

  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch (e) {
    parsed = { ok: false };
  }

  if (bumped > 10) {
    return `${label}:${upper}:${parsed.ok === false ? 'bad' : 'ok'}:${bumped}`;
  }
  return `${label}:${upper}:small:${bumped}`;
}

allFeatures([[1, -2], [3, 0, 4]], { name: 'alice' }, 2, '{"ok":true}');
