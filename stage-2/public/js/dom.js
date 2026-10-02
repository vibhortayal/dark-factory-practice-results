// A tiny DOM builder. Text always goes in as text nodes, never as markup.

function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

/** Replace the children of `host`; false/null entries (from `cond && node`) are skipped. */
export function setChildren(host, ...children) {
  host.replaceChildren();
  append(host, children);
}

export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key === 'testid') el.setAttribute('data-testid', value);
    else if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else el.setAttribute(key, value === true ? '' : String(value));
  }
  append(el, children);
  return el;
}

let counter = 0;
export const uid = (prefix) => `${prefix}-${++counter}`;

/** A labelled text input; returns {wrap, input}. */
export function textField({ label, testid, type = 'text', value = '', hint, inputmode, autocomplete, placeholder, required }) {
  const id = uid('f');
  const hintId = hint ? `${id}-hint` : null;
  const input = h('input', {
    id, type, testid, value, inputmode, autocomplete, placeholder, required,
    'aria-describedby': hintId, spellcheck: 'false', autocapitalize: 'off',
  });
  input.value = value;
  const wrap = h('div', { class: 'field' }, h('label', { for: id }, label), input, hint && h('p', { class: 'hint', id: hintId }, hint));
  return { wrap, input };
}

/** A labelled select; options are [value, label] pairs. */
export function selectField({ label, testid, options, value }) {
  const id = uid('f');
  const select = h('select', { id, testid }, options.map(([v, text]) => h('option', { value: v }, text)));
  if (value !== undefined) select.value = value;
  return { wrap: h('div', { class: 'field' }, h('label', { for: id }, label), select), input: select };
}

const NOTICE = {
  error: { cls: 'notice notice-error', icon: '!', role: 'alert' },
  uncertain: { cls: 'notice notice-uncertain', icon: '?', role: 'alert' },
  success: { cls: 'notice notice-success', icon: '✓', role: 'status' },
  info: { cls: 'notice notice-info', icon: 'i', role: 'status' },
};

/** A message box; its test id is present only while it is shown. */
export function notice(kind, text, testid) {
  const spec = NOTICE[kind];
  return h('div', { class: spec.cls, role: spec.role, testid }, h('span', { class: 'notice-icon', 'aria-hidden': 'true' }, spec.icon), h('span', { class: 'notice-text' }, text));
}

/** Holds at most one notice in `host`, with the test ids of one form. */
export function createFeedback(host, ids) {
  let current = null;
  const clear = () => {
    if (current) current.remove();
    current = null;
  };
  const show = (kind, text) => {
    clear();
    current = notice(kind, text, ids[kind]);
    host.append(current);
  };
  return { clear, show };
}

export function spinnerLabel(text) {
  return h('span', { class: 'busy' }, h('span', { class: 'spinner', 'aria-hidden': 'true' }), text);
}
