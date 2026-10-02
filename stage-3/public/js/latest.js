// "Latest refresh wins": a response from an earlier read never replaces a later read's data.

export function latestOnly() {
  let started = 0;
  let applied = 0;
  return async function run(task, apply) {
    const id = ++started;
    const result = await task();
    if (id < applied) return false; // a later refresh has already been shown
    applied = id;
    apply(result);
    return true;
  };
}
