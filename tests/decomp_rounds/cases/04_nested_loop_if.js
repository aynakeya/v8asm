function countPositives(rows) {
  let total = 0;
  for (const row of rows) {
    for (const v of row) {
      if (v > 0) total += 1;
    }
  }
  return total;
}
countPositives([[1, -1], [2, 0, 3]]);
