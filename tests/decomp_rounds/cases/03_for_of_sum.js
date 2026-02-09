function sumList(arr) {
  let sum = 0;
  for (const x of arr) {
    sum += x;
  }
  return sum;
}
sumList([1, 2, 3, 4]);
