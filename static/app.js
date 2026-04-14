/* Job Search Agent – shared client-side logic */

// ---------------------------------------------------------------------------
// Toast helper
// ---------------------------------------------------------------------------
function showToast(msg, type = 'success') {
  const toast = document.getElementById('toast');
  const inner = document.getElementById('toast-inner');
  if (!toast || !inner) return;

  inner.textContent = msg;
  inner.className = 'px-4 py-3 rounded-xl shadow-lg text-sm font-medium text-white max-w-xs ' +
    (type === 'error' ? 'bg-red-600' : 'bg-gray-800');

  toast.classList.remove('hidden', 'opacity-0');
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => toast.classList.add('hidden'), 3500);
}

// ---------------------------------------------------------------------------
// Generic API fetch
// ---------------------------------------------------------------------------
async function apiFetch(url, opts = {}) {
  try {
    const res = await fetch(url, opts);
    return await res.json();
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Run Now
// ---------------------------------------------------------------------------
async function runNow() {
  const btn   = document.getElementById('run-btn');
  const icon  = document.getElementById('run-icon');
  const label = document.getElementById('run-label');
  if (!btn) return;

  btn.disabled   = true;
  icon.textContent  = '⏳';
  label.textContent = 'Running…';

  const data = await apiFetch('/api/run', { method: 'POST' });

  if (!data) {
    showToast('Could not reach server.', 'error');
  } else if (!data.ok) {
    showToast(data.message || 'Already running.', 'error');
  } else {
    showToast('Scrape started! Refresh the page once it finishes.');
    // Show running indicator
    const ind = document.getElementById('scrape-indicator');
    if (ind) ind.classList.remove('hidden');
    // Poll until done
    const poll = setInterval(async () => {
      const s = await apiFetch('/api/status');
      if (s && !s.is_running) {
        clearInterval(poll);
        if (ind) ind.classList.add('hidden');
        showToast(`Done! ${s.today_count} new job${s.today_count !== 1 ? 's' : ''} today.`);
        // Auto-refresh the page to show new results
        setTimeout(() => location.reload(), 1200);
      }
    }, 4000);
  }

  // Reset button after 3 s regardless
  setTimeout(() => {
    btn.disabled      = false;
    icon.textContent  = '▶';
    label.textContent = 'Run Now';
  }, 3000);
}

// ---------------------------------------------------------------------------
// Set job status (dashboard cards)
// ---------------------------------------------------------------------------
async function setStatus(jobId, status, btn) {
  const data = await apiFetch(`/api/job/${jobId}/status`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ status }),
  });

  if (!data || !data.ok) {
    showToast('Failed to update status.', 'error');
    return false;
  }

  // On the dashboard, remove the card with animation
  const card = btn && btn.closest('.job-card');
  if (card) {
    card.style.transition = 'opacity 0.3s, transform 0.3s';
    card.style.opacity    = '0';
    card.style.transform  = 'scale(0.95)';
    setTimeout(() => {
      card.remove();
      // Update visible count
      const countEl = document.getElementById('visible-count');
      if (countEl) {
        const remaining = document.querySelectorAll('.job-card').length;
        countEl.textContent = `${remaining} job${remaining !== 1 ? 's' : ''}`;
      }
    }, 300);
  }

  const labels = { applied: '✓ Marked as applied', ignored: 'Job ignored', new: 'Moved back to new' };
  showToast(labels[status] || 'Updated.');
  return true;
}
