'use strict';
// Fragments stay out of HTTP access logs; no automatic activation on GET.
const activationParameters = new URLSearchParams(window.location.hash.slice(1));
const activationCode = activationParameters.get('code');
if (activationCode && /^[A-Za-z0-9_-]{30,100}$/.test(activationCode)) {
  const field = document.querySelector('input[name="code"]');
  if (field) field.value = activationCode;
  history.replaceState(null, '', window.location.pathname);
}
