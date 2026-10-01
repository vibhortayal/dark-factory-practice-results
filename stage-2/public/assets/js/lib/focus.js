// A list re-render replaces its DOM; keep the caret where the user was typing.
export function rememberFocus() {
  const el = document.activeElement;
  const testid = el && el.getAttribute && el.getAttribute('data-testid');
  if (!testid) return null;
  return { testid, start: el.selectionStart ?? null, end: el.selectionEnd ?? null };
}

export function restoreFocus(saved) {
  if (!saved) return;
  const el = document.querySelector(`[data-testid="${CSS.escape(saved.testid)}"]`);
  if (!el) return;
  el.focus();
  if (saved.start !== null && el.setSelectionRange) {
    try { el.setSelectionRange(saved.start, saved.end); } catch { /* not a text input */ }
  }
}
