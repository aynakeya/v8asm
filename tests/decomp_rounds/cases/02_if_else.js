function pick(n) {
  if (n > 10) {
    return n - 10;
  } else if (n > 5) {
    return n + 1;
  }
  return 0;
}
pick(7);
