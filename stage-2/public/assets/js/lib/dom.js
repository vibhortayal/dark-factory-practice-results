// Tiny element builder. Strings are always inserted as text nodes, never parsed as HTML,
// so notes, names and handles cannot inject markup.
export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (name === 'class') el.className = value;
    else if (name === 'testid') el.setAttribute('data-testid', value);
    else if (name.startsWith('on')) el.addEventListener(name.slice(2).toLowerCase(), value);
    else if (value === true) el.setAttribute(name, '');
    else el.setAttribute(name, String(value));
  }
  append(el, children);
  return el;
}

export function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === undefined || child === null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

export const clear = (el) => el.replaceChildren();

// A labelled input; returns { wrap, input }.
export function field({ id, label, testid, type = 'text', value = '', hint, inputmode, autocomplete, maxlength, placeholder }) {
  const input = h('input', { id, type, testid, value, inputmode, autocomplete, maxlength, placeholder, class: 'input' });
  input.value = value;
  const wrap = h('div', { class: 'field' }, h('label', { for: id, class: 'label' }, label), input, hint ? h('p', { class: 'hint', id: `${id}-hint` }, hint) : null);
  if (hint) input.setAttribute('aria-describedby', `${id}-hint`);
  return { wrap, input };
}

export function select({ id, label, testid, options, value }) {
  const el = h('select', { id, testid, class: 'input' }, options.map((o) => h('option', { value: o.value }, o.label)));
  if (value !== undefined) el.value = value;
  return { wrap: h('div', { class: 'field' }, h('label', { for: id, class: 'label' }, label), el), input: el };
}

let uid = 0;
export const nextId = (prefix) => `${prefix}-${++uid}`;

// A static icon (no user data), built by the HTML parser so no namespace URL is needed.
export function lockIcon() {
  const tpl = document.createElement('template');
  tpl.innerHTML = '<svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><path d="M5 7V5a3 3 0 016 0v2" fill="none" stroke="currentColor" stroke-width="1.6"/><rect x="3" y="7" width="10" height="7" rx="1.5" fill="currentColor"/></svg>';
  return tpl.content.firstElementChild;
}
