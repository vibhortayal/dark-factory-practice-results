// Page data with "latest refresh wins". `sources` maps a name to an async loader; every refresh
// loads all of them together and shows them together, unless a later refresh got there first.

import { latestOnly } from './latest.js';

export function createModel({ api, sources, initial = {} }) {
  const run = latestOnly();
  const listeners = new Set();
  let state = { ...initial };

  const publish = () => listeners.forEach((fn) => fn(state));

  return {
    get state() {
      return state;
    },
    subscribe(fn) {
      listeners.add(fn);
      fn(state);
      return () => listeners.delete(fn);
    },
    /** Resolves true when this refresh's data was shown, false when a later one superseded it. */
    refresh() {
      const names = Object.keys(sources);
      return run(
        async () => Object.fromEntries(await Promise.all(names.map(async (n) => [n, await sources[n](api)]))),
        (data) => {
          state = { ...state, ...data };
          publish();
        },
      );
    },
  };
}
