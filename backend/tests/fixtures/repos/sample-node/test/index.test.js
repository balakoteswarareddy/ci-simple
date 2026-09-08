const { add } = require("../src/index");

test("adds numbers", () => {
  expect(add(1, 2)).toBe(3);
});
