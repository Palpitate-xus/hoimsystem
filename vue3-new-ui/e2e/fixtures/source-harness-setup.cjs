// Complete Vue / Element Plus harness compilation measured 31.1s cold on the
// shared validation host. Give that preparation its own bounded deadline;
// Playwright keeps each test body, action and assertion at its existing timeout.
function beforeSourceHarness(test, setup) {
  test.beforeAll("Compile complete source harness", async () => {
    test.setTimeout(120_000);
    await setup();
  });
}

module.exports = { beforeSourceHarness };
