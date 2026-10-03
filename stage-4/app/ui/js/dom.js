// Tiny DOM helpers. All text goes in through textContent, never innerHTML.

export function append(el, kids) {
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

export function h(tag, props = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value == null || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key === 'testid') el.setAttribute('data-testid', value);
    else if (key === 'text') el.textContent = value;
    else if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? '' : value);
  }
  return append(el, kids);
}

export function clear(el) {
  el.replaceChildren();
  return el;
}

const ICONS = {
  lock: 'M7 10V8a5 5 0 0 1 10 0v2h1a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1h1Zm2 0h6V8a3 3 0 0 0-6 0v2Z',
  globe: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Zm6.9 8h-3a14 14 0 0 0-1.3-5A7 7 0 0 1 18.9 11ZM12 5.1c.8 1 1.6 3 1.9 5.9h-3.8c.3-2.9 1.1-4.9 1.9-5.9ZM5.1 13h3a14 14 0 0 0 1.3 5A7 7 0 0 1 5.1 13Zm3-2h-3a7 7 0 0 1 4.3-5 14 14 0 0 0-1.3 5Zm3.9 7.9c-.8-1-1.6-3-1.9-5.9h3.8c-.3 2.9-1.1 4.9-1.9 5.9Zm2.6-.9a14 14 0 0 0 1.3-5h3a7 7 0 0 1-4.3 5Z',
  arrow: 'M5 11h11.2l-4.6-4.6L13 5l7 7-7 7-1.4-1.4 4.6-4.6H5v-2Z',
  refresh: 'M12 5V2L7.5 6.5 12 11V8a5 5 0 1 1-5 5H5a7 7 0 1 0 7-8Z',
  check: 'M9.5 16.2 5.3 12l-1.4 1.4 5.6 5.6L20.1 8.4 18.7 7 9.5 16.2Z',
  alert: 'M12 3 1.5 21h21L12 3Zm1 14h-2v-2h2v2Zm0-4h-2V9h2v4Z',
  clock: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm1 5h-2v6l5 3 1-1.7-4-2.3V7Z',
};

export function icon(name) {
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('class', 'icon');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  const path = document.createElementNS(ns, 'path');
  path.setAttribute('d', ICONS[name] || ICONS.alert);
  svg.append(path);
  return svg;
}
