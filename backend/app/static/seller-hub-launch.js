(() => {
  'use strict';

  const form = document.getElementById('seller-hub-waitlist-form');
  if (!form) return;

  const submit = document.getElementById('waitlist-submit');
  const message = document.getElementById('waitlist-message');

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!form.reportValidity() || submit.disabled) return;

    submit.disabled = true;
    submit.textContent = 'Joining the list…';
    message.className = 'form-message';
    message.textContent = '';

    try {
      const response = await fetch('/api/v1/public/seller-hub/waitlist', {
        method: 'POST',
        credentials: 'omit',
        cache: 'no-store',
        headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
        body: JSON.stringify({
          name: document.getElementById('waitlist-name').value,
          email: document.getElementById('waitlist-email').value,
          interest: document.getElementById('waitlist-interest').value,
          consent: document.getElementById('waitlist-consent').checked,
          shopify_contact_consent: document.getElementById('waitlist-consent').checked,
          website: document.getElementById('waitlist-website').value
        })
      });

      if (!response.ok) throw new Error('Registration unavailable');
      const result = await response.json();
      if (result.status !== 'registered') throw new Error('Invalid registration response');

      form.reset();
      message.className = 'form-message success';
      message.textContent = "You're on the list! We'll be in touch with Seller Hub launch news.";
      submit.textContent = 'You’re on the list ✓';
      return;
    } catch {
      message.className = 'form-message error';
      message.textContent = "We couldn't save your registration just now. Please try again.";
      submit.disabled = false;
      submit.textContent = 'Try again →';
    }
  });
})();
