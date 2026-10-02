function describeNumericArray(array) {
  const result = [];
  for (let index = 0; index < array.length; index++) {
    result[index] = index in array
      ? [typeof array[index], String(array[index]), array[index] === 0 && 1 / array[index] === -Infinity]
      : ["absent-element"];
  }
  return result;
}
function literalArrays() {
  return [
    [1.25, -2.5, -0, 5e-324, 1.7976931348623157e308],
    [, 1.25, , undefined, -0, NaN, Infinity, -Infinity, ,],
    [, 13, ,],
    [, "stored-value", , undefined,],
    [NaN, Infinity, -Infinity],
    [,,],
    [,,,,,,,,,,,,,,,,,,,,,],
    ["repeat-value", "repeat-value", "repeat-value"],
  ];
}
function numericLiterals() {
  const arrays = literalArrays();
  const other = literalArrays();
  arrays[0][0] = 99;
  const described = [];
  for (let index = 0; index < other.length; index++) {
    described[index] = describeNumericArray(other[index]);
  }
  const scalar = 1.125e100;
  const object = { decimal: 13.75, negativeZero: -0 };
  return {
    described,
    independent: other[0][0] === 1.25,
    scalar: String(scalar),
    object: describeNumericArray([object.decimal, object.negativeZero, 1e400, -1e400]),
  };
}
globalThis.__semantic_result = numericLiterals();
