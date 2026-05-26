function* seq(arg0) {
  yield arg0;
  yield arg0 + 1;
  return arg0 + 2;
}

function useSeq(arg0) {
  const iter = seq(arg0);
  const first = iter.next();
  const second = iter.next();
  const done = iter.next();
  return first.value + second.value + (done.done ? done.value : 0);
}

useSeq(3);
