/* Preserve dashboard filter state, scroll position, and theme across page reloads. */
(function () {
  'use strict';

  var FILTER_KEYS = [
    'start_date', 'end_date', 'exclude_business', 'use_my_share',
    'review_sort', 'review_search', 'edit_search', 'person_search'
  ];

  /* ── Theme Handling (Dark Mode default) ── */
  var themeToggle = document.getElementById('theme-toggle');
  
  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
    // Update button icon/aria-label if elements exist
    if (themeToggle) {
      themeToggle.setAttribute('aria-label', 'Switch to ' + (theme === 'dark' ? 'light' : 'dark') + ' mode');
      var moonIcon = themeToggle.querySelector('.moon-icon');
      var sunIcon = themeToggle.querySelector('.sun-icon');
      if (moonIcon && sunIcon) {
        if (theme === 'dark') {
          moonIcon.style.display = 'none';
          sunIcon.style.display = 'block';
        } else {
          moonIcon.style.display = 'block';
          sunIcon.style.display = 'none';
        }
      }
    }
  }

  // Init theme
  var savedTheme = localStorage.getItem('theme') || 'dark';
  applyTheme(savedTheme);

  // Toggle button listener
  if (themeToggle) {
    themeToggle.addEventListener('click', function () {
      var currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
      var newTheme = currentTheme === 'dark' ? 'light' : 'dark';
      applyTheme(newTheme);
    });
  }

  /* ── GET search forms: scroll back to the containing section ── */
  document.querySelectorAll('form[method=get]').forEach(function (form) {
    var section = form.closest('[id]');
    if (section && section.id) {
      form.addEventListener('submit', function () {
        form.action = '/#' + section.id;
      });
    }
  });

  /* ── POST forms: save current filters + scroll target ── */
  document.querySelectorAll('form[method=post]').forEach(function (form) {
    form.addEventListener('submit', function () {
      var params = new URLSearchParams(location.search);
      var filters = {};
      FILTER_KEYS.forEach(function (key) {
        if (params.has(key)) filters[key] = params.get(key);
      });
      sessionStorage.setItem('_ef', JSON.stringify(filters));
      var section = form.closest('[id]');
      if (section) sessionStorage.setItem('_es', section.id);
    });
  });

  /* ── After a POST redirect: restore filters + scroll ── */
  var params = new URLSearchParams(location.search);
  var isRedirect = params.has('message') || params.has('error');

  if (isRedirect) {
    var raw = sessionStorage.getItem('_ef');
    var scrollTo = sessionStorage.getItem('_es');
    sessionStorage.removeItem('_ef');
    sessionStorage.removeItem('_es');

    if (raw) {
      var filters = JSON.parse(raw);
      var changed = false;
      Object.keys(filters).forEach(function (key) {
        if (!params.has(key)) {
          params.set(key, filters[key]);
          changed = true;
        }
      });
      if (changed) {
        var hash = scrollTo ? '#' + scrollTo : '';
        location.replace('?' + params.toString() + hash);
        return;
      }
    }

    if (scrollTo) {
      var el = document.getElementById(scrollTo);
      if (el) {
        if (el.tagName === 'DETAILS') el.open = true;
        el.scrollIntoView({ behavior: 'smooth' });
      }
    }
  }

  /* ── Open and scroll to anchor on initial load ── */
  if (location.hash) {
    var target = document.getElementById(location.hash.slice(1));
    if (target) {
      if (target.tagName === 'DETAILS') target.open = true;
      target.scrollIntoView({ behavior: 'smooth' });
    }
  }
})();
